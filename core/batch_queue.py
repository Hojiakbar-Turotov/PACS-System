import time
import logging
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import threading

from core.database import get_connection, log_event
from core.config import load_settings
from telegram.dispatcher import send_study_to_telegram
from core.ct_poller import retrieve_study_from_ct

logger = logging.getLogger("BATCH_QUEUE")

class BatchQueueManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.active_batches = []
        self._executor = None
        self._concurrency = 2
        self._init_executor()

    def _init_executor(self):
        cfg = load_settings()
        self._concurrency = int(cfg.get("batch_concurrency", 2))
        self._executor = ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix="BatchWorker")

    def enqueue_studies(self, study_ids: list[int]):
        """Bir nechta (masalan 50 ta) bemorni parallel xavfsiz navbatga qo'yish"""
        conn = get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in study_ids)
        cursor.execute(f"SELECT * FROM studies WHERE id IN ({placeholders})", study_ids)
        studies = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not studies:
            return 0

        # Agar sozlamalarda oqimlar soni o'zgargan bo'lsa yangilash
        cfg = load_settings()
        new_conc = int(cfg.get("batch_concurrency", 2))
        if new_conc != self._concurrency:
            self._concurrency = new_conc
            self._executor = ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix="BatchWorker")

        log_event("INFO", f"⚡ Parallel navbat: {len(studies)} ta tekshiruv {self._concurrency} ta parallel oqimda yuklashga qo'yildi.")

        for study in studies:
            self._executor.submit(self._process_single_study, study)

        return len(studies)

    def enqueue_studies_archive(self, study_ids: list[int]):
        """Tanlangan bemorlarni KT dan tortib olib, faqat serverga ZIP arxivlash (Telegramga yubormaydi)"""
        conn = get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in study_ids)
        cursor.execute(f"SELECT * FROM studies WHERE id IN ({placeholders})", study_ids)
        studies = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not studies:
            return 0

        cfg = load_settings()
        new_conc = int(cfg.get("batch_concurrency", 2))
        if new_conc != self._concurrency:
            self._concurrency = new_conc
            self._executor = ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix="BatchWorker")

        log_event("INFO", f"🗜️ Mahalliylashtirish: {len(studies)} ta tekshiruv faqat serverga arxivlash navbatiga qo'yildi.")

        for study in studies:
            self._executor.submit(self._process_single_archive, study)

        return len(studies)

    def enqueue_archive_all_ct(self):
        """KT apparatidagi hali kompyuterda arxivlanmagan barcha bemorlarni navbatga qo'yish"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM studies WHERE (archive_path IS NULL OR archive_path = '' OR local_copy_status != 'STORED') ORDER BY id DESC")
        studies = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not studies:
            log_event("INFO", "ℹ️ Barcha tekshiruvlar allaqachon arxivlangan!")
            return 0

        cfg = load_settings()
        new_conc = int(cfg.get("batch_concurrency", 2))
        if new_conc != self._concurrency:
            self._concurrency = new_conc
            self._executor = ThreadPoolExecutor(max_workers=self._concurrency, thread_name_prefix="BatchWorker")

        log_event("INFO", f"🗜️ Ommaviy arxivlash: KT apparatidagi {len(studies)} ta arxivlanmagan bemor serverga yuklab olinmoqda ({self._concurrency} ta oqimda)...")

        for study in studies:
            self._executor.submit(self._process_single_archive, study)

        return len(studies)

    def _process_single_archive(self, study: dict):
        study_id = study["id"]
        patient_name = study.get("patient_name", "")
        uid = study.get("study_instance_uid", "")
        
        try:
            z_path = Path(study["archive_path"]) if study.get("archive_path") else None
            if z_path and z_path.exists():
                return
            
            retrieve_study_from_ct(uid, send_telegram=False)
            time.sleep(1)
        except Exception as e:
            logger.error(f"Archive study {study_id} ({patient_name}) xatosi: {e}", exc_info=True)
            log_event("ERROR", f"Arxivlash xatosi ({patient_name}): {e}")

    def _process_single_study(self, study: dict):
        study_id = study["id"]
        patient_name = study.get("patient_name", "")
        uid = study.get("study_instance_uid", "")
        
        try:
            # Fayllar mavjudligini tekshirish
            z_path = Path(study["archive_path"]) if study.get("archive_path") else None
            
            if z_path and z_path.exists():
                # Allaqachon serverda mavjud -> darhol Telegramga
                send_study_to_telegram(
                    study_id=study_id,
                    patient_name=patient_name,
                    patient_id=study.get("patient_id", ""),
                    study_desc=study.get("study_description", ""),
                    study_date=study.get("study_date", ""),
                    slices_count=study.get("instances_count", 0),
                    zip_path=z_path,
                    force=True
                )
            else:
                # KT apparatida -> C-MOVE orqali yuklab olib keyin yuborish
                retrieve_study_from_ct(uid, send_telegram=True)
                
            time.sleep(1)
        except Exception as e:
            logger.error(f"Batch study {study_id} ({patient_name}) xatosi: {e}", exc_info=True)
            log_event("ERROR", f"Batch xatolik ({patient_name}): {e}")

batch_manager = BatchQueueManager()
