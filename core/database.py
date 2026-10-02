import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from core.config import DATA_DIR

DB_PATH = DATA_DIR / "pacs.db"
DB_LOCK = threading.RLock()

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=60000;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn

@contextmanager
def db_write_transaction(max_retries: int = 5, retry_delay: float = 0.2):
    """Barcha yozish operatsiyalari uchun xavfsiz qulflash va takrorlash konteksti"""
    with DB_LOCK:
        conn = None
        for attempt in range(max_retries):
            try:
                conn = get_connection()
                yield conn
                conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    if conn:
                        try: conn.close()
                        except: pass
                    continue
                raise
            finally:
                if conn:
                    try: conn.close()
                    except: pass

def init_db():
    with DB_LOCK:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 1. Bemorlar / Worklist jadvali
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS worklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            accession_number TEXT UNIQUE,
            patient_id TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            birth_date TEXT,
            gender TEXT,
            exam_description TEXT,
            referring_physician TEXT,
            operator TEXT,
            scheduled_date TEXT,
            scheduled_time TEXT,
            status TEXT DEFAULT 'SCHEDULED', -- SCHEDULED, IN_PROGRESS, COMPLETED, CANCELLED, CT_DIRECT
            origin TEXT DEFAULT 'WEB',       -- WEB, CT_DEVICE
            created_at TEXT
        )
        """)
        
        # Eskidan bor bo'lsa origin ustunini qo'shish
        try:
            cursor.execute("ALTER TABLE worklist ADD COLUMN origin TEXT DEFAULT 'WEB'")
        except Exception:
            pass
        
        # 2. Qabul qilingan tekshiruvlar (Studies) jadvali
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS studies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            study_instance_uid TEXT UNIQUE,
            patient_id TEXT,
            patient_name TEXT,
            birth_date TEXT,
            gender TEXT,
            study_date TEXT,
            study_time TEXT,
            study_description TEXT,
            modality TEXT,
            series_count INTEGER DEFAULT 0,
            instances_count INTEGER DEFAULT 0,
            storage_folder TEXT,
            archive_path TEXT,
            archive_size_bytes INTEGER DEFAULT 0,
            preview_image_path TEXT,
            telegram_status TEXT DEFAULT 'PENDING', -- PENDING, SENDING, SENT, FAILED
            telegram_message_id INTEGER,
            telegram_error TEXT,
            last_sent_instances INTEGER DEFAULT 0,
            created_at TEXT,
            completed_at TEXT
        )
        """)
        
        try:
            cursor.execute("ALTER TABLE studies ADD COLUMN last_sent_instances INTEGER DEFAULT 0")
        except Exception:
            pass
            
        try:
            cursor.execute("ALTER TABLE studies ADD COLUMN local_copy_status TEXT DEFAULT 'NOT_DOWNLOADED'")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE studies ADD COLUMN local_stored_at TEXT")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE studies ADD COLUMN progress_stage TEXT DEFAULT 'IDLE'")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE studies ADD COLUMN progress_percent INTEGER DEFAULT 0")
        except Exception:
            pass

        try:
            cursor.execute("ALTER TABLE studies ADD COLUMN progress_text TEXT DEFAULT ''")
        except Exception:
            pass
        
        # 3. Harakatlar va loglar jadvali
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT,
            message TEXT,
            details TEXT,
            created_at TEXT
        )
        """)
        
        conn.commit()
        conn.close()

def log_event(level: str, message: str, details: str = ""):
    with DB_LOCK:
        try:
            conn = get_connection()
            conn.execute("INSERT INTO logs (level, message, details, created_at) VALUES (?, ?, ?, ?)",
                         (level, message, details, datetime.now().isoformat()))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Log xatoligi: {e}")

# Ishga tushganda bazani initsializatsiya qilish
init_db()
