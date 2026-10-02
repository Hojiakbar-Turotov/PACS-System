import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager

import time
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from core.config import (
    BASE_DIR, WEB_DIR, RADIANT_EXE,
    CT_HOST, CT_PORT, CT_AET,
    load_settings, save_settings
)
from core.database import get_connection, log_event
from core.dicom_engine import DicomEngine
from core.ct_poller import CTPoller, sync_all_studies_from_ct, retrieve_study_from_ct
from core.processor import process_completed_study
from core.retention_manager import RetentionDaemon
from core.auto_archive_service import AutoArchiveDaemon
from core.batch_queue import batch_manager
from telegram.dispatcher import send_study_to_telegram

dicom_engine = None
ct_poller = None
retention_daemon = None
auto_archive_daemon = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global dicom_engine, ct_poller, retention_daemon, auto_archive_daemon
    print("[*] Sabadarmon MSKT PACS Tizimi yuklanmoqda...")
    
    # 1. DICOM Serverni ishga tushirish
    dicom_engine = DicomEngine(on_study_completed_callback=process_completed_study)
    dicom_engine.start()
    
    # 2. GE CT fon skanerini ishga tushirish (har 20 soniyada tekshiradi)
    ct_poller = CTPoller(interval_seconds=20)
    ct_poller.start()

    # 3. 30 kunlik saqlash va avtomatik tozalash xizmati
    retention_daemon = RetentionDaemon(check_interval_hours=6)
    retention_daemon.start()

    # 4. Yangi bemorlarni avtomatik aniqlash, rekon barqarorligi va 3-soatlik qayta tekshirish xizmati
    auto_archive_daemon = AutoArchiveDaemon()
    auto_archive_daemon.start()
    
    log_event("SYSTEM", "PACS Server, Worklist, GE CT monitoring va Avto-arxiv xizmati faol")
    yield
    # To'xtatish
    if ct_poller:
        ct_poller.stop()
    if dicom_engine:
        dicom_engine.stop()
    if retention_daemon:
        retention_daemon.stop()
    if auto_archive_daemon:
        auto_archive_daemon.stop()
    print("[*] Tizim to'xtatildi.")

app = FastAPI(title="Sabadarmon MSKT PACS", lifespan=lifespan)

# Pydantic modellari
class PatientCreate(BaseModel):
    patient_id: str
    patient_name: str
    birth_date: str = ""
    gender: str = "M"
    exam_description: str
    referring_physician: str = ""
    operator: str = ""

# API Endpoints

@app.post("/api/worklist")
def add_patient_to_worklist(item: PatientCreate):
    conn = get_connection()
    cursor = conn.cursor()
    
    today_str = datetime.now().strftime("%y%m%d")
    now_time = datetime.now().strftime("%H%M%S")
    accession_num = f"ACC{today_str}{now_time[-4:]}"
    
    try:
        cursor.execute("""
            INSERT INTO worklist (
                accession_number, patient_id, patient_name, birth_date,
                gender, exam_description, referring_physician, operator,
                scheduled_date, scheduled_time, status, origin, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SCHEDULED', 'WEB', ?)
        """, (
            accession_num, item.patient_id.strip(), item.patient_name.strip(),
            item.birth_date.strip(), item.gender, item.exam_description.strip(),
            item.referring_physician.strip(), item.operator.strip(),
            datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%H:%M:%S"),
            datetime.now().isoformat()
        ))
        conn.commit()
        log_event("INFO", f"Yangi bemor qo'shildi (Web): {item.patient_name} ({item.patient_id}) - {item.exam_description}")
        return {"status": "ok", "accession_number": accession_num}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/worklist")
def get_worklist():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM worklist ORDER BY id DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@app.delete("/api/worklist/{worklist_id}")
def delete_worklist_item(worklist_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM worklist WHERE id = ?", (worklist_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted"}

@app.post("/api/poll_ct")
def poll_ct_now():
    """GE CT apparatidan darhol bemorlarni so'rash"""
    global ct_poller
    if ct_poller:
        studies = ct_poller.check_once()
        return {"status": "ok", "count": len(studies), "studies": studies}
    return {"status": "error", "detail": "CT poller faol emas"}

@app.get("/api/studies")
def get_studies():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM studies ORDER BY id DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    from core.progress_tracker import get_study_progress
    now = datetime.now()

    for s in rows:
        # Diskda fayllar mavjudligini aniqlash
        has_arch = bool(s.get("archive_path") and Path(s["archive_path"]).exists())
        has_store = bool(s.get("storage_folder") and Path(s["storage_folder"]).exists())
        s["has_local_copy"] = has_arch or has_store

        # 30 kunlik saqlash muddatidan qolgan kunlar
        stored_at_str = s.get("local_stored_at") or s.get("completed_at")
        if s["has_local_copy"] and stored_at_str:
            try:
                st_dt = datetime.fromisoformat(stored_at_str)
                days_passed = (now - st_dt).days
                s["days_remaining"] = max(0, 30 - days_passed)
            except Exception:
                s["days_remaining"] = 30
        else:
            s["days_remaining"] = 0

        # Jonli progress holati
        prog = get_study_progress(s["id"])
        if prog:
            s["active_stage"] = prog.get("stage", "")
            s["active_percent"] = prog.get("percent", 0)
            s["active_text"] = prog.get("text", "")
            s["active_speed"] = prog.get("speed", "")
        else:
            s["active_stage"] = s.get("progress_stage") or ""
            s["active_percent"] = s.get("progress_percent") or 0
            s["active_text"] = s.get("progress_text") or ""
            s["active_speed"] = ""

    return rows

@app.get("/api/studies/progress")
def get_studies_progress():
    from core.progress_tracker import get_all_active_progress
    return get_all_active_progress()

@app.post("/api/sync_ct")
def sync_ct_database():
    """GE CT apparatidagi barcha 727 ta bemorni sinxronlash"""
    count = sync_all_studies_from_ct()
    return {"status": "ok", "count": count}

class BatchResendRequest(BaseModel):
    study_ids: list[int]

@app.post("/api/studies/{study_id}/resend")
def resend_study_telegram(study_id: int, background_tasks: BackgroundTasks):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM studies WHERE id = ?", (study_id,))
    study = cursor.fetchone()
    conn.close()
    
    if not study:
        raise HTTPException(status_code=404, detail="Tekshiruv topilmadi")
        
    zip_path = Path(study["archive_path"]) if study["archive_path"] else None
    if zip_path and zip_path.exists():
        from core.database import DB_LOCK
        with DB_LOCK:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE studies SET telegram_status = 'SENDING' WHERE id = ?", (study_id,))
            conn.commit()
            conn.close()
        
        def _send_bg():
            send_study_to_telegram(
                study_id=study["id"],
                patient_name=study["patient_name"],
                patient_id=study["patient_id"],
                study_desc=study["study_description"],
                study_date=study["study_date"],
                slices_count=study["instances_count"],
                zip_path=zip_path,
                force=True
            )
        background_tasks.add_task(_send_bg)
        return {"status": "sending", "detail": "Telegramga yuklash boshlandi"}
    else:
        # Fayllar KT apparatida - C-MOVE orqali tortib olamiz
        log_event("INFO", f"Fayllar KT apparatida, C-MOVE orqali so'ralmoqda: {study['patient_name']} ({study['patient_id']})")
        from core.database import DB_LOCK
        with DB_LOCK:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE studies SET telegram_status = 'RETRIEVING' WHERE id = ?", (study_id,))
            conn.commit()
            conn.close()
        
        background_tasks.add_task(retrieve_study_from_ct, study["study_instance_uid"])
        return {"status": "retrieving", "detail": "KT apparatidan tasvirlar yuklab olinmoqda va Telegramga uzatiladi"}

@app.post("/api/studies/batch_resend")
def batch_resend_studies(req: BatchResendRequest):
    if not req.study_ids:
        raise HTTPException(status_code=400, detail="Kamida bitta tekshiruv tanlanishi kerak")
    count = batch_manager.enqueue_studies(req.study_ids)
    return {"status": "started", "count": count}

@app.post("/api/studies/{study_id}/download_to_server")
def download_study_to_server(study_id: int, background_tasks: BackgroundTasks):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM studies WHERE id = ?", (study_id,))
    study = cursor.fetchone()
    conn.close()
    
    if not study:
        raise HTTPException(status_code=404, detail="Tekshiruv topilmadi")
        
    has_local = False
    if study["archive_path"] and Path(study["archive_path"]).exists():
        has_local = True
    if study["storage_folder"] and Path(study["storage_folder"]).exists():
        has_local = True
        
    if has_local:
        return {"status": "already_stored", "detail": "Ushbu tekshiruv allaqachon server xotirasida mavjud"}
        
    log_event("INFO", f"📥 KT apparatidan faqat serverga yuklab olish: {study['patient_name']} ({study['patient_id']})")
    background_tasks.add_task(retrieve_study_from_ct, study["study_instance_uid"], False)
    return {"status": "downloading", "detail": "KT apparatidan serverga yuklab olish boshlandi"}

@app.post("/api/studies/{study_id}/open_radiant")
def open_in_radiant(study_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT storage_folder, archive_path, patient_name FROM studies WHERE id = ?", (study_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Tekshiruv topilmadi")
        
    radiant_exe = Path(RADIANT_EXE)
    if not radiant_exe.exists():
        raise HTTPException(status_code=500, detail=f"RadiAntViewer dasturi topilmadi: {RADIANT_EXE}")
        
    target_path = None
    if row["storage_folder"] and Path(row["storage_folder"]).exists():
        target_path = Path(row["storage_folder"])
    elif row["archive_path"] and Path(row["archive_path"]).exists():
        target_path = Path(row["archive_path"])
        
    if not target_path:
        raise HTTPException(
            status_code=400,
            detail="Ushbu tekshiruv hozircha faqat KT apparatida saqlanmoqda. Avval uni '📥 Serverga' tugmasi orqali kompyuterga yuklab oling."
        )
        
    try:
        subprocess.Popen([str(radiant_exe), str(target_path)])
        return {"status": "opened", "path": str(target_path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RadiAnt ochishda xatolik: {e}")

class SettingsUpdate(BaseModel):
    ct_host: str = "192.168.10.250"
    ct_port: int = 4006
    ct_aet: str = "CT01"
    pacs_port: int = 11112
    pacs_aet: str = "RADIANT"
    web_port: int = 8000
    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    retention_days: int = 30
    auto_archive_enabled: bool = True
    new_study_poll_interval: int = 60
    recon_stability_checks: int = 3
    deep_scan_interval: int = 10800
    batch_concurrency: int = 2

@app.get("/api/settings")
def get_system_settings():
    return load_settings()

@app.post("/api/settings")
def update_system_settings(settings: SettingsUpdate):
    save_settings(settings.dict())
    log_event("SETTINGS", f"Tizim sozlamalari yangilandi: CT={settings.ct_host}:{settings.ct_port}, PACS={settings.pacs_port}")
    return {"status": "ok", "settings": load_settings()}

@app.get("/api/status")
def get_system_status():
    total, used, free = shutil.disk_usage(str(BASE_DIR))
    
    from pynetdicom import AE
    from pynetdicom.sop_class import Verification
    ct_online = False
    try:
        test_ae = AE(ae_title=b"RADIANT")
        test_ae.network_timeout = 3
        test_ae.add_requested_context(Verification)
        assoc = test_ae.associate(CT_HOST, CT_PORT, ae_title=CT_AET.encode())
        if assoc.is_established:
            status = assoc.send_c_echo()
            ct_online = (status.Status == 0)
            assoc.release()
    except Exception:
        ct_online = False
        
    return {
        "pacs_running": True,
        "ct_host": f"{CT_HOST}:{CT_PORT} ({CT_AET})",
        "ct_online": ct_online,
        "disk_free_gb": round(free / (1024**3), 1),
        "disk_total_gb": round(total / (1024**3), 1),
        "disk_used_percent": round((used / total) * 100, 1)
    }

@app.get("/api/logs")
def get_system_logs(limit: int = 80):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@app.get("/list")
def get_queue_page():
    return FileResponse(str(WEB_DIR / "list.html"))

app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
