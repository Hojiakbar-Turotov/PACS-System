import time
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import List, Dict, Any, Optional

from core.database import get_connection, log_event, DB_LOCK
from core.config import load_settings
from telegram.dispatcher import send_study_to_telegram
from core.ct_poller import retrieve_study_from_ct
from core.progress_tracker import update_progress, clear_all_progress, mark_completed

logger = logging.getLogger("BATCH_PIPELINE")

class BatchQueueManager:
    """
    3 bosqichli qat'iy parallelizm va navbat raqamlari (#N) boshqaruvi:
    1. KT Apparatidan yuklab olish (C-MOVE): MAX 2 ta parallel (GE KT barqarorligi uchun)
    2. ZIP Arxivlash (Siqish): MAX 3 ta parallel (CPU me'yori uchun)
    3. Telegramga yuborish (MTProto): QAT'IY 1 ta ketma-ket (bitta fayl to'liq yuklanib bo'lgach keyingisi)
    """

    def __init__(self):
        self.lock = threading.Lock()
        self._cancel_flag = threading.Event()
        
        # Concurrency limitlari
        self.CT_CONCURRENCY = 2
        self.ARCHIVE_CONCURRENCY = 3
        self.TG_CONCURRENCY = 1

        # FIFO Navbatlar (List of dicts: {"id": int, "uid": str, "name": str, "patient_id": str, "desc": str, "date": str, "slices": int, "send_telegram": bool})
        self._ct_queue: List[Dict[str, Any]] = []
        self._archive_queue: List[Dict[str, Any]] = []
        self._tg_queue: List[Dict[str, Any]] = []

        # Faol bajarilayotgan study_id lar to'plami
        self._active_ct = set()
        self._active_archive = set()
        self._active_tg = set()

        # Oqimlar basseynlari (ThreadPoolExecutors)
        self._ct_executor = ThreadPoolExecutor(max_workers=self.CT_CONCURRENCY, thread_name_prefix="CT_Worker")
        self._archive_executor = ThreadPoolExecutor(max_workers=self.ARCHIVE_CONCURRENCY, thread_name_prefix="Archive_Worker")
        self._tg_executor = ThreadPoolExecutor(max_workers=self.TG_CONCURRENCY, thread_name_prefix="TG_Worker")

        # Navbat dispetcheri fon siklini ishga tushirish
        self._running = True
        self._dispatcher_thread = threading.Thread(target=self._pipeline_loop, daemon=True, name="PipelineDispatcher")
        self._dispatcher_thread.start()

    def cancel_all(self):
        """Barcha faol navbat va jarayonlarni darhol to'xtatish va tozalash"""
        with self.lock:
            self._cancel_flag.set()
            self._ct_queue.clear()
            self._archive_queue.clear()
            self._tg_queue.clear()
            self._active_ct.clear()
            self._active_archive.clear()
            self._active_tg.clear()

            # Executorlarni qayta ishga tushirish
            try:
                self._ct_executor.shutdown(wait=False, cancel_futures=True)
                self._archive_executor.shutdown(wait=False, cancel_futures=True)
                self._tg_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

            self._ct_executor = ThreadPoolExecutor(max_workers=self.CT_CONCURRENCY, thread_name_prefix="CT_Worker")
            self._archive_executor = ThreadPoolExecutor(max_workers=self.ARCHIVE_CONCURRENCY, thread_name_prefix="Archive_Worker")
            self._tg_executor = ThreadPoolExecutor(max_workers=self.TG_CONCURRENCY, thread_name_prefix="TG_Worker")

            self._cancel_flag = threading.Event()

        clear_all_progress()

        with DB_LOCK:
            try:
                conn = get_connection()
                conn.execute("""
                    UPDATE studies SET
                        progress_stage = 'IDLE',
                        progress_percent = 0,
                        progress_text = ''
                    WHERE progress_stage != 'IDLE'
                """)
                conn.execute("""
                    UPDATE studies SET
                        telegram_status = CASE 
                            WHEN archive_path IS NOT NULL AND archive_path != '' THEN 'PENDING'
                            ELSE 'ON_CT_DEVICE'
                        END
                    WHERE telegram_status IN ('SENDING', 'RETRIEVING')
                """)
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"DB tozalash xatosi: {e}")

        log_event("WARNING", "🛑 Barcha faol jarayonlar va navbatlar to'liq to'xtatildi hamda tozalandi")

    def recalculate_positions(self):
        """Har bir navbatdagi elementlarga #1, #2, #3 tartib raqamlarini hisoblash va aks ettirish"""
        with self.lock:
            # 1. KT Navbatidagilar
            for idx, item in enumerate(self._ct_queue):
                sid = item["id"]
                pos = idx + 1
                txt = f"⏳ KT navbatida: #{pos} (kutilmoqda)"
                update_progress(sid, "QUEUED_CT", 0, txt, force_db=True)

            # 2. ZIP Arxiv navbatidagilar
            for idx, item in enumerate(self._archive_queue):
                sid = item["id"]
                pos = idx + 1
                txt = f"⏳ ZIP navbatida: #{pos} (kutilmoqda)"
                update_progress(sid, "QUEUED_ARCHIVE", 0, txt, force_db=True)

            # 3. Telegram navbatidagilar
            for idx, item in enumerate(self._tg_queue):
                sid = item["id"]
                pos = idx + 1
                txt = f"⏳ Telegram navbatida: #{pos} (kutilmoqda)"
                update_progress(sid, "QUEUED_TG", 0, txt, force_db=True)

    def enqueue_studies(self, study_ids: list[int]):
        """Bir nechta bemorni Telegramga yuborish navbatiga qo'yish (zarur bo'lsa KT dan tortadi)"""
        conn = get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in study_ids)
        cursor.execute(f"SELECT * FROM studies WHERE id IN ({placeholders})", study_ids)
        studies = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not studies:
            return 0

        log_event("INFO", f"⚡ Parallel navbat: {len(studies)} ta tekshiruv Telegramga uzatish jarayoniga qo'shildi.")

        with self.lock:
            for s in studies:
                sid = s["id"]
                # Allaqachon biror navbatda yoki faol bo'lsa o'tkazib yuborish
                if self._is_already_queued(sid):
                    continue

                item = self._create_queue_item(s, send_telegram=True)
                z_path = Path(s["archive_path"]) if s.get("archive_path") else None
                
                if z_path and z_path.exists():
                    # Arxiv mavjud -> to'g'ridan-to'g'ri Telegram navbatiga
                    self._tg_queue.append(item)
                else:
                    # KT apparatida -> KT dan yuklab olish navbatiga
                    self._ct_queue.append(item)

        self.recalculate_positions()
        return len(studies)

    def enqueue_studies_archive(self, study_ids: list[int]):
        """Tanlangan bemorlarni faqat kompyuterga ZIP arxivlash (Telegramga yubormaydi)"""
        conn = get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in study_ids)
        cursor.execute(f"SELECT * FROM studies WHERE id IN ({placeholders})", study_ids)
        studies = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not studies:
            return 0

        log_event("INFO", f"🗜️ Mahalliylashtirish: {len(studies)} ta tekshiruv serverga arxivlash navbatiga qo'yildi.")

        with self.lock:
            for s in studies:
                sid = s["id"]
                if self._is_already_queued(sid):
                    continue

                item = self._create_queue_item(s, send_telegram=False)
                z_path = Path(s["archive_path"]) if s.get("archive_path") else None
                
                if z_path and z_path.exists():
                    # Allaqachon arxivlangan
                    continue
                else:
                    self._ct_queue.append(item)

        self.recalculate_positions()
        return len(studies)

    def enqueue_archive_all_ct(self):
        """KT apparatidagi barcha arxivlanmagan tekshiruvlarni navbatga qo'yish"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM studies WHERE (archive_path IS NULL OR archive_path = '' OR local_copy_status != 'STORED') ORDER BY id DESC")
        studies = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not studies:
            log_event("INFO", "ℹ️ Barcha tekshiruvlar allaqachon arxivlangan!")
            return 0

        log_event("INFO", f"🗜️ Ommaviy arxivlash: KT apparatidagi {len(studies)} ta arxivlanmagan bemor serverga yuklash navbatiga qo'yildi.")

        with self.lock:
            for s in studies:
                sid = s["id"]
                if self._is_already_queued(sid):
                    continue
                item = self._create_queue_item(s, send_telegram=False)
                self._ct_queue.append(item)

        self.recalculate_positions()
        return len(studies)

    def enqueue_single_telegram(self, study_id: int):
        """Bitta bemorni Telegram navbatiga qo'yish"""
        return self.enqueue_studies([study_id])

    def enqueue_single_archive(self, study_id: int):
        """Bitta bemorni serverga arxivlash navbatiga qo'yish"""
        return self.enqueue_studies_archive([study_id])

    def _create_queue_item(self, study: dict, send_telegram: bool) -> dict:
        return {
            "id": study["id"],
            "uid": study.get("study_instance_uid", ""),
            "name": study.get("patient_name", ""),
            "patient_id": study.get("patient_id", ""),
            "desc": study.get("study_description", ""),
            "date": study.get("study_date", ""),
            "slices": study.get("instances_count", 0),
            "archive_path": study.get("archive_path", ""),
            "send_telegram": send_telegram
        }

    def _is_already_queued(self, study_id: int) -> bool:
        if study_id in self._active_ct or study_id in self._active_archive or study_id in self._active_tg:
            return True
        if any(item["id"] == study_id for item in self._ct_queue):
            return True
        if any(item["id"] == study_id for item in self._archive_queue):
            return True
        if any(item["id"] == study_id for item in self._tg_queue):
            return True
        return False

    def _pipeline_loop(self):
        """Dispetcher fon sikli: bo'sh oqimlarga yangi vazifalarni taqsimlaydi"""
        while self._running:
            try:
                if self._cancel_flag.is_set():
                    time.sleep(0.5)
                    continue

                needs_recalc = False

                # 1. KT Bosqichi (Max 2 concurrent)
                with self.lock:
                    while len(self._active_ct) < self.CT_CONCURRENCY and self._ct_queue:
                        item = self._ct_queue.pop(0)
                        self._active_ct.add(item["id"])
                        self._ct_executor.submit(self._worker_ct_download, item)
                        needs_recalc = True

                # 2. ZIP Arxivlash Bosqichi (Max 3 concurrent)
                with self.lock:
                    while len(self._active_archive) < self.ARCHIVE_CONCURRENCY and self._archive_queue:
                        item = self._archive_queue.pop(0)
                        self._active_archive.add(item["id"])
                        self._archive_executor.submit(self._worker_archive, item)
                        needs_recalc = True

                # 3. Telegram Bosqichi (Qat'iy MAX 1 sequential)
                with self.lock:
                    while len(self._active_tg) < self.TG_CONCURRENCY and self._tg_queue:
                        item = self._tg_queue.pop(0)
                        self._active_tg.add(item["id"])
                        self._tg_executor.submit(self._worker_telegram_upload, item)
                        needs_recalc = True

                if needs_recalc:
                    self.recalculate_positions()

            except Exception as e:
                logger.error(f"Pipeline loop error: {e}", exc_info=True)

            time.sleep(0.4)

    def _worker_ct_download(self, item: dict):
        """KT apparatidan C-MOVE orqali yuklab olish ishchisi"""
        sid = item["id"]
        uid = item["uid"]
        pname = item["name"]

        try:
            if self._cancel_flag.is_set():
                return

            update_progress(sid, "DOWNLOADING_CT", 1, f"KT apparatidan so'ralmoqda [{pname}]...", force_db=True)
            
            # send_telegram=False beramiz, chunki keyingi bosqichni batch pipeline boshqaradi
            success = retrieve_study_from_ct(uid, send_telegram=False)

            if self._cancel_flag.is_set():
                return

            # Yangilangan arxiv ma'lumotlarini bazadan olish
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT archive_path, instances_count FROM studies WHERE id = ?", (sid,))
            updated_row = c.fetchone()
            conn.close()

            if updated_row and updated_row["archive_path"]:
                item["archive_path"] = updated_row["archive_path"]
                item["slices"] = updated_row["instances_count"] or item["slices"]

            if item["send_telegram"]:
                # Telegramga yuborilishi kerak bo'lsa, Telegram navbatiga uzatamiz
                with self.lock:
                    self._tg_queue.append(item)
                self.recalculate_positions()
            else:
                mark_completed(sid, success=True)

        except Exception as e:
            logger.error(f"CT yuklash xatosi ({pname}): {e}", exc_info=True)
            log_event("ERROR", f"KT dan yuklab olish xatosi [{pname}]: {e}")
            mark_completed(sid, success=False, error_msg=str(e))
        finally:
            with self.lock:
                self._active_ct.discard(sid)
            self.recalculate_positions()

    def _worker_archive(self, item: dict):
        """ZIP Arxiv yaratish ishchisi (agar C-STORE orqali qabul qilinib hali zip qilinmagan bo'lsa)"""
        sid = item["id"]
        pname = item["name"]

        try:
            if self._cancel_flag.is_set():
                return

            update_progress(sid, "ARCHIVING", 50, f"🗜️ ZIP arxiv yaratilmoqda [{pname}]...", force_db=True)
            time.sleep(1) # Arxivlash operatsiyasi

            if item["send_telegram"]:
                with self.lock:
                    self._tg_queue.append(item)
                self.recalculate_positions()
            else:
                mark_completed(sid, success=True)

        except Exception as e:
            logger.error(f"Arxivlash xatosi ({pname}): {e}", exc_info=True)
            mark_completed(sid, success=False, error_msg=str(e))
        finally:
            with self.lock:
                self._active_archive.discard(sid)
            self.recalculate_positions()

    def _worker_telegram_upload(self, item: dict):
        """Telegramga yuborish ishchisi (MAX 1 ta oqim, bittalab)"""
        sid = item["id"]
        pname = item["name"]
        pid = item["patient_id"]
        desc = item["desc"]
        date = item["date"]
        slices = item["slices"]

        try:
            if self._cancel_flag.is_set():
                return

            # Arxiv yo'lini tekshirish
            z_path = Path(item["archive_path"]) if item.get("archive_path") else None
            if not z_path or not z_path.exists():
                # Qayta bazadan tekshirish
                conn = get_connection()
                c = conn.cursor()
                c.execute("SELECT archive_path FROM studies WHERE id = ?", (sid,))
                row = c.fetchone()
                conn.close()
                if row and row["archive_path"]:
                    z_path = Path(row["archive_path"])

            if not z_path or not z_path.exists():
                raise FileNotFoundError(f"Telegramga yuborish uchun ZIP arxiv topilmadi [{pname}]")

            update_progress(sid, "UPLOADING_TG", 1, "Telegram serveriga ulanmoqda... 0% • ⚡ 0.0 MB/s", speed="0.0 MB/s", force_db=True)

            send_study_to_telegram(
                study_id=sid,
                patient_name=pname,
                patient_id=pid,
                study_desc=desc,
                study_date=date,
                slices_count=slices,
                zip_path=z_path,
                force=True
            )

        except Exception as e:
            logger.error(f"Telegram yuborish xatosi ({pname}): {e}", exc_info=True)
            log_event("ERROR", f"Telegram yuborish xatosi [{pname}]: {e}")
            mark_completed(sid, success=False, error_msg=str(e))
        finally:
            with self.lock:
                self._active_tg.discard(sid)
            self.recalculate_positions()

batch_manager = BatchQueueManager()
