import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager

import time
import tempfile
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, UploadFile, File, Form
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
def resend_study_telegram(study_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM studies WHERE id = ?", (study_id,))
    study = cursor.fetchone()
    conn.close()
    
    if not study:
        raise HTTPException(status_code=404, detail="Tekshiruv topilmadi")
        
    count = batch_manager.enqueue_single_telegram(study_id)
    return {"status": "enqueued", "detail": "Telegram navbatiga muvaffaqiyatli qo'shildi"}

@app.post("/api/studies/batch_resend")
def batch_resend_studies(req: BatchResendRequest):
    if not req.study_ids:
        raise HTTPException(status_code=400, detail="Kamida bitta tekshiruv tanlanishi kerak")
    count = batch_manager.enqueue_studies(req.study_ids)
    return {"status": "started", "count": count}

@app.post("/api/studies/batch_archive")
def batch_archive_studies(req: BatchResendRequest):
    if not req.study_ids:
        raise HTTPException(status_code=400, detail="Kamida bitta tekshiruv tanlanishi kerak")
    count = batch_manager.enqueue_studies_archive(req.study_ids)
    return {"status": "started", "count": count}

@app.post("/api/studies/archive_all_ct")
def archive_all_ct_studies():
    count = batch_manager.enqueue_archive_all_ct()
    return {"status": "started", "count": count}

@app.post("/api/queue/cancel_all")
def cancel_all_queue():
    batch_manager.cancel_all()
    return {"status": "ok", "message": "Barcha faol jarayonlar to'xtatildi va navbat tozalandi"}

@app.post("/api/studies/{study_id}/delete_local")
@app.delete("/api/studies/{study_id}/local_storage")
def delete_study_local_storage(study_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM studies WHERE id = ?", (study_id,))
    study = cursor.fetchone()
    conn.close()

    if not study:
        raise HTTPException(status_code=404, detail="Tekshiruv topilmadi")

    freed_bytes = 0
    if study["archive_path"]:
        zp = Path(study["archive_path"])
        if zp.exists():
            freed_bytes += zp.stat().st_size
            try: zp.unlink()
            except Exception as e: print(f"Arxiv o'chirish xatosi: {e}")

    if study["storage_folder"]:
        sp = Path(study["storage_folder"])
        if sp.exists():
            shutil.rmtree(sp, ignore_errors=True)

    from core.database import DB_LOCK
    with DB_LOCK:
        conn = get_connection()
        conn.execute("""
            UPDATE studies SET
                local_copy_status = 'NOT_DOWNLOADED',
                archive_path = '',
                archive_size_bytes = 0,
                storage_folder = '',
                local_stored_at = NULL
            WHERE id = ?
        """, (study_id,))
        conn.commit()
        conn.close()

    freed_mb = round(freed_bytes / (1024 * 1024), 1)
    log_event("INFO", f"🗑️ Serverdan mahalliy fayllar tozalandi: {study['patient_name']} ({freed_mb} MB bo'shatildi)")
    return {"status": "ok", "freed_mb": freed_mb, "message": f"{freed_mb} MB disk joyi bo'shatildi"}

@app.post("/api/studies/batch_delete_local")
def batch_delete_local_storage(req: BatchResendRequest):
    if not req.study_ids:
        raise HTTPException(status_code=400, detail="Kamida bitta tekshiruv tanlanishi kerak")
    
    total_freed = 0
    deleted_cnt = 0
    conn = get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in req.study_ids)
    cursor.execute(f"SELECT * FROM studies WHERE id IN ({placeholders})", req.study_ids)
    studies = cursor.fetchall()
    conn.close()

    from core.database import DB_LOCK
    with DB_LOCK:
        conn = get_connection()
        for s in studies:
            sid = s["id"]
            if s["archive_path"]:
                zp = Path(s["archive_path"])
                if zp.exists():
                    total_freed += zp.stat().st_size
                    try: zp.unlink()
                    except: pass
            if s["storage_folder"]:
                sp = Path(s["storage_folder"])
                if sp.exists():
                    shutil.rmtree(sp, ignore_errors=True)
            
            conn.execute("""
                UPDATE studies SET
                    local_copy_status = 'NOT_DOWNLOADED',
                    archive_path = '',
                    archive_size_bytes = 0,
                    storage_folder = '',
                    local_stored_at = NULL
                WHERE id = ?
            """, (sid,))
            deleted_cnt += 1
        conn.commit()
        conn.close()

    freed_mb = round(total_freed / (1024 * 1024), 1)
    log_event("INFO", f"🗑️ Ommaviy tozalash: {deleted_cnt} ta tekshiruv server diskidan o'chirildi ({freed_mb} MB bo'shatildi)")
    return {"status": "ok", "deleted_count": deleted_cnt, "freed_mb": freed_mb}

@app.post("/api/studies/{study_id}/download_from_telegram")
def download_from_telegram_endpoint(study_id: int, background_tasks: BackgroundTasks):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM studies WHERE id = ?", (study_id,))
    study = cursor.fetchone()
    conn.close()

    if not study:
        raise HTTPException(status_code=404, detail="Tekshiruv topilmadi")

    if not study["telegram_message_id"]:
        raise HTTPException(status_code=400, detail="Ushbu tekshiruv Telegramga yuborilmagan yoki xabar ID si topilmadi")

    from telegram.dispatcher import download_study_from_telegram
    from core.progress_tracker import update_progress
    update_progress(study_id, "DOWNLOADING_TG", 5, "Telegramdan yuklab olish boshlandi...", force_db=True)
    
    background_tasks.add_task(download_study_from_telegram, study_id)
    return {"status": "started", "message": "Telegramdan yuklab olish boshlandi"}

@app.post("/api/import/zip")
async def import_zip_endpoint(
    file: UploadFile = File(...),
    send_to_ct: bool = Form(True)
):
    from core.importer import import_from_zip
    temp_zip = Path(tempfile.mkdtemp(prefix="dicom_zip_upload_")) / file.filename
    try:
        with open(temp_zip, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        results = import_from_zip(temp_zip, send_to_ct=send_to_ct)
        return {"status": "ok", "results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"ZIP import xatosi: {e}")
    finally:
        shutil.rmtree(temp_zip.parent, ignore_errors=True)

@app.post("/api/import/files")
async def import_files_endpoint(
    files: list[UploadFile] = File(...),
    send_to_ct: bool = Form(True)
):
    from core.importer import process_imported_dicom_dir
    temp_dir = Path(tempfile.mkdtemp(prefix="dicom_files_upload_"))
    try:
        for f in files:
            # Nisbiy yo'l yoki nomni xavfsiz shakllantirish
            norm_name = f.filename.replace('/', os.sep).replace('\\', os.sep)
            dest_file = temp_dir / norm_name
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_file, "wb") as buffer:
                shutil.copyfileobj(f.file, buffer)
        results = process_imported_dicom_dir(temp_dir, send_to_ct=send_to_ct)
        return {"status": "ok", "results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"DICOM fayllar import xatosi: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@app.post("/api/studies/{study_id}/download_to_server")
def download_study_to_server(study_id: int):
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
        
    count = batch_manager.enqueue_single_archive(study_id)
    return {"status": "enqueued", "detail": "KT dan serverga yuklash navbatiga qo'shildi"}

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
    if row["archive_path"] and Path(row["archive_path"]).exists():
        target_path = Path(row["archive_path"])
    elif row["storage_folder"] and Path(row["storage_folder"]).exists():
        target_path = Path(row["storage_folder"])
        
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
