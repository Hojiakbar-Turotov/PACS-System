import shutil
import logging
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from core.database import get_connection, log_event

logger = logging.getLogger("RETENTION_MANAGER")

RETENTION_DAYS = 30

def init_retention_metadata():
    """Mavjud arxivlarni tekshirib, local_copy_status va local_stored_at ni to'g'rilash"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, storage_folder, archive_path, completed_at, created_at, local_stored_at FROM studies")
        rows = cursor.fetchall()
        for r in rows:
            has_archive = bool(r["archive_path"] and Path(r["archive_path"]).exists())
            has_storage = bool(r["storage_folder"] and Path(r["storage_folder"]).exists())
            
            if (has_archive or has_storage) and not r["local_stored_at"]:
                stored_time = r["completed_at"] or r["created_at"] or datetime.now().isoformat()
                cursor.execute("""
                    UPDATE studies SET
                        local_copy_status = 'STORED',
                        local_stored_at = ?
                    WHERE id = ?
                """, (stored_time, r["id"]))
            elif not has_archive and not has_storage:
                cursor.execute("""
                    UPDATE studies SET
                        local_copy_status = 'NOT_DOWNLOADED'
                    WHERE id = ? AND (local_copy_status IS NULL OR local_copy_status = '')
                """, (r["id"],))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Retention metadata initsializatsiyasida xatolik: {e}")

def run_retention_cleanup(retention_days=RETENTION_DAYS) -> int:
    """30 kundan oshgan mahalliy tekshiruv fayllarini diskdan tozalash (bazadagi qayd saqlanadi)"""
    try:
        cutoff_date = (datetime.now() - timedelta(days=retention_days)).isoformat()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, patient_name, patient_id, storage_folder, archive_path, local_stored_at
            FROM studies
            WHERE local_copy_status = 'STORED' AND local_stored_at <= ?
        """, (cutoff_date,))
        expired_studies = cursor.fetchall()
        
        cleaned_count = 0
        for s in expired_studies:
            p_name = s["patient_name"]
            p_id = s["patient_id"]
            
            # 1. Raw DICOM papkasini o'chirish
            if s["storage_folder"]:
                sf_path = Path(s["storage_folder"])
                if sf_path.exists():
                    try:
                        shutil.rmtree(sf_path)
                    except Exception as err:
                        logger.warning(f"Papka o'chirishda xatolik {sf_path}: {err}")
            
            # 2. ZIP arxivni o'chirish
            if s["archive_path"]:
                ap_path = Path(s["archive_path"])
                if ap_path.exists():
                    try:
                        ap_path.unlink()
                    except Exception as err:
                        logger.warning(f"ZIP o'chirishda xatolik {ap_path}: {err}")
                        
            # 3. Bazada statusni yangilash
            cursor.execute("""
                UPDATE studies SET
                    local_copy_status = 'CLEANED_30_DAYS',
                    storage_folder = '',
                    archive_path = '',
                    archive_size_bytes = 0
                WHERE id = ?
            """, (s["id"],))
            cleaned_count += 1
            log_event("INFO", f"🧹 30 kunlik muddat tugadi: Mahalliy diskdan fayllar tozalandi [{p_name} - ID: {p_id}]. Kerak bo'lsa KT apparatidan qayta yuklab olish mumkin.")
            
        conn.commit()
        conn.close()
        
        if cleaned_count > 0:
            log_event("INFO", f"✅ Avtomatik tozalash yakunlandi: {cleaned_count} ta 30 kundan eski tekshiruv diskdan tozalandi.")
        return cleaned_count
    except Exception as e:
        logger.error(f"Avtomatik tozalashda xatolik: {e}")
        return 0

class RetentionDaemon:
    def __init__(self, check_interval_hours=6):
        self.interval = check_interval_hours * 3600
        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print(f"[*] 30 kunlik saqlash va tozalash xizmati faollashtirildi (har {self.interval // 3600} soatda tekshiriladi).")

    def stop(self):
        self.running = False

    def _loop(self):
        # Boshlang'ich initsializatsiya
        init_retention_metadata()
        time.sleep(5)
        run_retention_cleanup()
        
        while self.running:
            for _ in range(int(self.interval)):
                if not self.running:
                    return
                time.sleep(1)
            try:
                run_retention_cleanup()
            except Exception as e:
                logger.error(f"Retention loop error: {e}")
