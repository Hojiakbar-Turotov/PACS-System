import time
import threading
from typing import Dict, Any, Optional
from core.database import get_connection

_lock = threading.Lock()

# study_id -> { "stage": str, "percent": int, "text": str, "current": int, "total": int, "speed": str, "updated_at": float }
_active_progress: Dict[int, Dict[str, Any]] = {}
# study_instance_uid -> study_id
_uid_to_id: Dict[str, int] = {}
# study_instance_uid -> { "received": int, "total": int, "last_t": float, "last_rec": int, "speed_mb_s": float }
_ct_download_metrics: Dict[str, Dict[str, Any]] = {}
# study_id -> last_db_save_timestamp
_last_db_save: Dict[int, float] = {}

def get_study_id_by_uid(uid: str) -> Optional[int]:
    with _lock:
        if uid in _uid_to_id:
            return _uid_to_id[uid]
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, instances_count FROM studies WHERE study_instance_uid = ?", (uid,))
        row = cursor.fetchone()
        conn.close()
        if row:
            with _lock:
                _uid_to_id[uid] = row["id"]
                if uid not in _ct_download_metrics:
                    now = time.time()
                    _ct_download_metrics[uid] = {
                        "received": 0,
                        "total": row["instances_count"] or 0,
                        "last_t": now,
                        "last_rec": 0,
                        "speed_mb_s": 0.0
                    }
            return row["id"]
    except Exception:
        pass
    return None

def start_ct_download(study_id: int, uid: str, total_instances: int):
    now = time.time()
    with _lock:
        _uid_to_id[uid] = study_id
        _ct_download_metrics[uid] = {
            "received": 0,
            "total": total_instances,
            "last_t": now,
            "last_rec": 0,
            "speed_mb_s": 0.0
        }
    update_progress(
        study_id=study_id,
        stage="DOWNLOADING_CT",
        percent=0,
        text=f"KT apparatiga so'rov yuborildi (0/{total_instances} kadr)...",
        current=0,
        total=total_instances,
        force_db=True
    )

def record_slice_received(uid: str) -> Optional[int]:
    """C-STORE orqali bitta kadr qabul qilinganda chaqiriladi"""
    study_id = get_study_id_by_uid(uid)
    if not study_id:
        return None
        
    now = time.time()
    speed_mb_s = 0.0
    with _lock:
        if uid not in _ct_download_metrics:
            _ct_download_metrics[uid] = {
                "received": 0,
                "total": 0,
                "last_t": now,
                "last_rec": 0,
                "speed_mb_s": 0.0
            }
        metric = _ct_download_metrics[uid]
        metric["received"] += 1
        rec = metric["received"]
        tot = metric["total"] or 1
        
        dt = now - metric["last_t"]
        if dt >= 0.8:
            d_slices = rec - metric["last_rec"]
            # Har bir KT DICOM kadri o'rtacha ~0.52 MB
            speed_mb_s = round((d_slices * 0.52) / dt, 1)
            metric["speed_mb_s"] = speed_mb_s
            metric["last_t"] = now
            metric["last_rec"] = rec
        else:
            speed_mb_s = metric.get("speed_mb_s", 0.0)

    percent = min(95, int((rec / tot) * 95)) if tot > 0 else 50
    speed_str = f" • {speed_mb_s} MB/s" if speed_mb_s > 0 else ""
    text = f"KT dan yuklanmoqda: {percent}% ({rec}/{tot} kadr){speed_str}"

    update_progress(
        study_id=study_id,
        stage="DOWNLOADING_CT",
        percent=percent,
        text=text,
        current=rec,
        total=tot,
        speed=f"{speed_mb_s} MB/s"
    )
    return study_id

def update_progress(study_id: int, stage: str, percent: int, text: str, current: int = 0, total: int = 0, speed: str = "", force_db: bool = False):
    now = time.time()
    with _lock:
        _active_progress[study_id] = {
            "stage": stage,
            "percent": percent,
            "text": text,
            "current": current,
            "total": total,
            "speed": speed,
            "updated_at": now
        }
        last_save = _last_db_save.get(study_id, 0)
        should_save = force_db or (now - last_save >= 1.5) or (stage in ('DONE', 'ERROR', 'IDLE')) or (percent == 100)
        if should_save:
            _last_db_save[study_id] = now

    # DB ga faqat davriy (throttled) yozish - SQLite qulflanishini oldini oladi
    if should_save:
        from core.database import DB_LOCK
        with DB_LOCK:
            try:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE studies SET
                        progress_stage = ?,
                        progress_percent = ?,
                        progress_text = ?
                    WHERE id = ?
                """, (stage, percent, text, study_id))
                conn.commit()
                conn.close()
            except Exception:
                pass

def mark_completed(study_id: int, success: bool = True, error_msg: str = ""):
    stage = "DONE" if success else "ERROR"
    percent = 100 if success else 0
    text = "Muvaffaqiyatli yakunlandi" if success else f"Xatolik: {error_msg}"
    update_progress(study_id, stage, percent, text, force_db=True)

def get_study_progress(study_id: int) -> Optional[Dict[str, Any]]:
    with _lock:
        return _active_progress.get(study_id)

def get_all_active_progress() -> Dict[int, Dict[str, Any]]:
    with _lock:
        return dict(_active_progress)

def clear_all_progress():
    """Barcha faol jarayonlarni xotiradan va bazadan tozalash"""
    with _lock:
        _active_progress.clear()
        _ct_download_metrics.clear()
        _uid_to_id.clear()
        _last_db_save.clear()

    from core.database import DB_LOCK
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
        except Exception:
            pass
