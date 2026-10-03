import os
import zipfile
import logging
from pathlib import Path
from datetime import datetime
import numpy as np
from PIL import Image
import pydicom

from core.config import ARCHIVES_DIR, load_settings
from core.database import get_connection, log_event
from telegram.dispatcher import send_study_to_telegram

logger = logging.getLogger("STUDY_PROCESSOR")

def get_clean_name(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip()

def generate_preview_image(dcm_files: list, output_jpg: Path) -> bool:
    """DICOM fayllar orasidan o'rtadagi kesimni olib, diagnostik JPG prevyu yaratish"""
    try:
        if not dcm_files:
            return False
            
        # O'rtadagi kesimni tanlash (eng informativ qismi bo'ladi)
        mid_idx = len(dcm_files) // 2
        mid_file = dcm_files[mid_idx]
        
        ds = pydicom.dcmread(str(mid_file))
        if 'PixelData' not in ds:
            return False
            
        pixel_array = ds.pixel_array.astype(float)
        
        # Rescale Slope va Intercept qo'llash (agar mavjud bo'lsa)
        slope = getattr(ds, 'RescaleSlope', 1)
        intercept = getattr(ds, 'RescaleIntercept', 0)
        pixel_array = pixel_array * slope + intercept
        
        # Window Center va Window Width (KT kontrasti)
        center = getattr(ds, 'WindowCenter', None)
        width = getattr(ds, 'WindowWidth', None)
        
        if center is not None and width is not None:
            if isinstance(center, (list, pydicom.multival.MultiValue)):
                center = center[0]
            if isinstance(width, (list, pydicom.multival.MultiValue)):
                width = width[0]
            
            img_min = center - width // 2
            img_max = center + width // 2
            pixel_array = np.clip(pixel_array, img_min, img_max)
            pixel_array = ((pixel_array - img_min) / (img_max - img_min) * 255).astype(np.uint8)
        else:
            # Agar Windowing bo'lmasa, min-max orqali normallashtirish
            p_min = np.min(pixel_array)
            p_max = np.max(pixel_array)
            if p_max > p_min:
                pixel_array = ((pixel_array - p_min) / (p_max - p_min) * 255).astype(np.uint8)
            else:
                pixel_array = np.zeros_like(pixel_array, dtype=np.uint8)
                
        img = Image.fromarray(pixel_array)
        img.save(str(output_jpg), format="JPEG", quality=88)
        return True
    except Exception as e:
        logger.error(f"Prevyu yaratishda xatolik: {e}")
        return False

def create_study_zip(dcm_files: list, output_zip: Path):
    """Barcha DICOM fayllarni tartibli ZIP arxivga jamlash (tezkor compresslevel=1)"""
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(output_zip), 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for idx, f in enumerate(dcm_files, start=1):
            zf.write(str(f), arcname=f"DICOM/{f.name}")

_retrieval_intents = {}

def set_retrieval_intent(study_uid: str, send_telegram: bool):
    _retrieval_intents[study_uid] = send_telegram

def get_retrieval_intent(study_uid: str):
    """Qaytaradi: True (Telegramga), False (faqat serverga), None (avtomatik)"""
    return _retrieval_intents.pop(study_uid, None)

def process_completed_study(study_uid, study_dir: Path, patient_id, patient_name, study_desc, study_date, modality):
    """Tekshiruv qabul qilib bo'lingach chaqiriladigan asosiy funksiya"""
    try:
        log_event("INFO", f"Tekshiruvni qayta ishlash boshlandi: {patient_name} ({study_uid[:8]})")
        dcm_files = sorted(list(study_dir.glob("*.dcm")))
        if not dcm_files:
            log_event("WARNING", f"Papka ichida DCM fayllar topilmadi: {study_dir}")
            return
            
        clean_patient = get_clean_name(patient_name)
        clean_id = get_clean_name(patient_id)
        date_folder = datetime.now().strftime("%Y-%m-%d")
        
        # 1. Prevyu rasm yaratish
        preview_path = study_dir / "preview.jpg"
        has_preview = generate_preview_image(dcm_files, preview_path)
        
        # 2. ZIP Arxiv yaratish
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM studies WHERE study_instance_uid = ?", (study_uid,))
        pre_row = cursor.fetchone()
        conn.close()
        if pre_row:
            try:
                from core.progress_tracker import update_progress
                update_progress(pre_row["id"], "ARCHIVING", 96, "🗜️ ZIP arxiv yaratilmoqda...", current=len(dcm_files), total=len(dcm_files))
            except Exception:
                pass

        zip_filename = f"{clean_patient}_{clean_id}_{study_date}.zip"
        zip_path = ARCHIVES_DIR / date_folder / zip_filename
        create_study_zip(dcm_files, zip_path)
        zip_size = zip_path.stat().st_size
        
        # 2.1. ZIP tayyor bo'lgach, disk joyini tejash uchun D:\PACS\storage dagi ochilgan papkani tozalash
        import shutil
        try:
            if study_dir.exists() and zip_path.exists() and zip_size > 0:
                shutil.rmtree(study_dir, ignore_errors=True)
                log_event("INFO", f"🧹 Storage papkasi tozalandi, faqat 30 kunlik ZIP saqlanmoqda: {zip_filename}")
        except Exception as e_clean:
            logger.warning(f"Storage tozalashda ogohlantirish: {e_clean}")

        # 3. Bazaga yozish yoki yangilash
        from core.database import DB_LOCK
        with DB_LOCK:
            conn = get_connection()
            cursor = conn.cursor()
            
            # Worklist holatini yangilash (agar bo'lsa)
            cursor.execute("UPDATE worklist SET status = 'COMPLETED' WHERE patient_id = ?", (patient_id,))
            
            # Mavjudligini tekshirish
            cursor.execute("SELECT id, instances_count, last_sent_instances, telegram_status, local_stored_at FROM studies WHERE study_instance_uid = ?", (study_uid,))
            existing = cursor.fetchone()
            
            is_update = False
            slices_count = len(dcm_files)
            now_iso = datetime.now().isoformat()
            
            if existing:
                study_db_id = existing["id"]
                last_sent = existing["last_sent_instances"] or 0
                old_status = existing["telegram_status"]
                
                if old_status == 'SENT' and last_sent > 0 and last_sent != slices_count:
                    is_update = True
                    
                cursor.execute("""
                    UPDATE studies SET
                        instances_count = ?,
                        storage_folder = '',
                        archive_path = ?,
                        archive_size_bytes = ?,
                        local_copy_status = 'STORED',
                        local_stored_at = COALESCE(local_stored_at, ?),
                        completed_at = ?
                    WHERE id = ?
                """, (slices_count, str(zip_path), zip_size, now_iso, now_iso, study_db_id))
            else:
                cursor.execute("""
                    INSERT INTO studies (
                        study_instance_uid, patient_id, patient_name, study_date, study_time,
                        study_description, modality, instances_count, storage_folder,
                        archive_path, archive_size_bytes, preview_image_path, telegram_status,
                        local_copy_status, local_stored_at,
                        last_sent_instances, created_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, 'PENDING', 'STORED', ?, 0, ?, ?)
                """, (
                    study_uid, patient_id, patient_name, study_date, datetime.now().strftime("%H:%M:%S"),
                    study_desc, modality, slices_count,
                    str(zip_path), zip_size, str(preview_path) if has_preview else "",
                    now_iso, now_iso, now_iso
                ))
                study_db_id = cursor.lastrowid
                
            conn.commit()
            conn.close()
        
        log_event("INFO", f"Arxiv tayyor: {zip_filename} ({round(zip_size / 1024 / 1024, 1)} MB, {slices_count} ta kadr)")
        
        # 4. Telegramga yuborish yoki faqat serverda qoldirish
        intent = get_retrieval_intent(study_uid)
        cfg = load_settings()
        auto_archive = cfg.get("auto_archive_enabled", True)
        
        # Agar qasddan serverga arxivlash bo'lsa (intent is False), Telegramga yubormaymiz.
        # Boshqa barcha hollarda (intent is True yoki avtomatik yangi kelgan tekshiruvlar) Telegram navbatiga qo'yiladi.
        should_send_tg = (intent is True) or (intent is None and auto_archive)
        
        if should_send_tg:
            from core.batch_queue import batch_manager
            if not batch_manager._is_already_queued(study_db_id):
                log_event("INFO", f"📤 Avtomatik Telegram navbatiga qo'shildi: {patient_name} [{slices_count} kadr]")
                batch_manager.enqueue_single_telegram(study_db_id)
            else:
                log_event("INFO", f"📦 Tekshiruv tayyor va faol navbatda kutmoqda: {patient_name} [{slices_count} kadr]")
        else:
            log_event("INFO", f"💾 Faqat serverga arxivlandi: {patient_name} [{slices_count} kadr]")
            with DB_LOCK:
                conn = get_connection()
                conn.execute("""
                    UPDATE studies SET
                        telegram_status = CASE WHEN telegram_status = 'SENT' THEN 'SENT' ELSE 'PENDING' END,
                        local_copy_status = 'STORED',
                        progress_stage = 'IDLE',
                        progress_percent = 100,
                        progress_text = ''
                    WHERE id = ?
                """, (study_db_id,))
                conn.commit()
                conn.close()
            try:
                from core.progress_tracker import mark_completed
                mark_completed(study_db_id, success=True)
            except Exception:
                pass
        
    except Exception as e:
        logger.error(f"Tekshiruvni qayta ishlashda xatolik: {e}", exc_info=True)
        log_event("ERROR", f"Tekshiruv qayta ishlash xatosi: {e}")
