import os
import shutil
import zipfile
import logging
import tempfile
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Tuple

import pydicom
from pynetdicom import AE, StoragePresentationContexts

from core.config import (
    ARCHIVES_DIR, STORAGE_DIR,
    CT_HOST, CT_PORT, CT_AET
)
from core.database import get_connection, log_event, DB_LOCK
from core.processor import generate_preview_image, get_clean_name, create_study_zip

logger = logging.getLogger("DICOM_IMPORTER")

def is_valid_dicom(file_path: Path) -> bool:
    """Fayl DICOM formatida ekanligini tezkor tekshirish"""
    try:
        if file_path.stat().st_size < 132:
            return False
        with open(file_path, 'rb') as f:
            f.seek(128)
            magic = f.read(4)
            if magic == b'DICM':
                return True
        # Ba'zi GE yoki eski DICOM fayllarda 128-bayt preambula bo'lmasligi mumkin
        ds = pydicom.dcmread(str(file_path), stop_before_pixels=True, force=True)
        return hasattr(ds, 'SOPClassUID') or hasattr(ds, 'StudyInstanceUID')
    except Exception:
        return False

def collect_dicom_files(root_dir: Path) -> List[Path]:
    """Papka ichidagi barcha DICOM fayllarni rekursiv topish"""
    dicom_files = []
    for p in root_dir.rglob('*'):
        if p.is_file() and is_valid_dicom(p):
            dicom_files.append(p)
    return dicom_files

def send_files_to_ct_device(dcm_files: List[Path], patient_name: str = "") -> Tuple[int, int]:
    """DICOM fayllarni GE CT apparatiga C-STORE protokoli orqali uzatish"""
    if not dcm_files:
        return 0, 0

    log_event("INFO", f"📡 KT apparatiga ({CT_HOST}:{CT_PORT}) {len(dcm_files)} ta kadr uzatilmoqda [{patient_name}]...")
    ae = AE(ae_title=b'RADIANT')
    ae.requested_contexts = StoragePresentationContexts
    
    assoc = ae.associate(CT_HOST, CT_PORT, ae_title=CT_AET.encode())
    if not assoc.is_established:
        log_event("ERROR", f"KT apparatiga ulanib bo'lmadi ({CT_HOST}:{CT_PORT})")
        raise ConnectionError(f"KT apparatiga ulanib bo'lmadi ({CT_HOST}:{CT_PORT})")

    sent_count = 0
    failed_count = 0
    total = len(dcm_files)

    try:
        for idx, f in enumerate(dcm_files, start=1):
            try:
                ds = pydicom.dcmread(str(f), force=True)
                status = assoc.send_c_store(ds)
                if status and status.Status == 0x0000:
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception as e_s:
                failed_count += 1
                logger.warning(f"Kadr uzatish xatosi ({f.name}): {e_s}")

            if idx % 100 == 0 or idx == total:
                log_event("MONITOR", f"📤 KT apparatiga uzatildi: {sent_count}/{total} kadr [{patient_name}]")
    finally:
        assoc.release()

    log_event("INFO", f"✅ KT apparatiga import yakunlandi: {sent_count}/{total} kadr muvaffaqiyatli uzatildi [{patient_name}]")
    return sent_count, failed_count

def process_imported_dicom_dir(source_dir: Path, send_to_ct: bool = True) -> List[Dict[str, Any]]:
    """DICOM fayllar joylashgan papkani qayta ishlash, mahalliy arxivlash va KT ga uzatish"""
    all_dcms = collect_dicom_files(source_dir)
    if not all_dcms:
        raise ValueError("Papka ichida yaroqli DICOM fayllar topilmadi")

    # StudyInstanceUID bo'yicha guruhlash
    studies_map: Dict[str, List[Path]] = {}
    for f in all_dcms:
        try:
            ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
            uid = getattr(ds, 'StudyInstanceUID', None)
            if not uid:
                uid = "1.2.840.manual_import." + datetime.now().strftime("%Y%m%d%H%M%S")
            uid = str(uid).strip()
            studies_map.setdefault(uid, []).append(f)
        except Exception:
            continue

    if not studies_map:
        raise ValueError("DICOM fayllarning StudyUID metama'lumotlarini o'qib bo'lmadi")

    results = []

    for uid, dcm_files in studies_map.items():
        # Birinchi kadr orqali metama'lumotlarni olish
        sample_ds = pydicom.dcmread(str(dcm_files[0]), force=True)
        raw_name = str(getattr(sample_ds, 'PatientName', 'NOMA_LUM')).replace('^', ' ').strip()
        p_name = raw_name if raw_name else "NOMA_LUM"
        p_id = str(getattr(sample_ds, 'PatientID', 'ID_' + datetime.now().strftime("%H%M%S"))).strip()
        s_date = str(getattr(sample_ds, 'StudyDate', datetime.now().strftime("%Y%m%d"))).strip()
        s_time = str(getattr(sample_ds, 'StudyTime', datetime.now().strftime("%H%M%S"))).strip()
        s_desc = str(getattr(sample_ds, 'StudyDescription', 'Imported Study')).strip()
        modality = str(getattr(sample_ds, 'Modality', 'CT')).strip()

        clean_p = get_clean_name(p_name)
        clean_i = get_clean_name(p_id)
        slices_cnt = len(dcm_files)

        date_folder = datetime.now().strftime("%Y-%m-%d")
        target_dir = ARCHIVES_DIR / date_folder
        target_dir.mkdir(parents=True, exist_ok=True)

        zip_filename = f"{clean_p}_{clean_i}_{s_date}.zip"
        zip_path = target_dir / zip_filename

        # 1. Prevyu yaratish
        preview_path = target_dir / f"{clean_p}_{clean_i}_preview.jpg"
        has_preview = generate_preview_image(dcm_files, preview_path)

        # 2. ZIP Arxiv yaratish
        create_study_zip(dcm_files, zip_path)
        zip_size = zip_path.stat().st_size

        # 3. Bazaga saqlash
        now_iso = datetime.now().isoformat()
        study_db_id = None
        with DB_LOCK:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM studies WHERE study_instance_uid = ?", (uid,))
            existing = cursor.fetchone()

            if existing:
                study_db_id = existing["id"]
                cursor.execute("""
                    UPDATE studies SET
                        patient_id = ?,
                        patient_name = ?,
                        study_date = ?,
                        study_time = ?,
                        study_description = ?,
                        modality = ?,
                        instances_count = ?,
                        storage_folder = '',
                        archive_path = ?,
                        archive_size_bytes = ?,
                        preview_image_path = ?,
                        local_copy_status = 'STORED',
                        local_stored_at = ?,
                        completed_at = ?,
                        progress_stage = 'IDLE',
                        progress_percent = 100,
                        progress_text = ''
                    WHERE id = ?
                """, (
                    p_id, p_name, s_date, s_time, s_desc, modality,
                    slices_cnt, str(zip_path), zip_size,
                    str(preview_path) if has_preview else "",
                    now_iso, now_iso, study_db_id
                ))
            else:
                cursor.execute("""
                    INSERT INTO studies (
                        study_instance_uid, patient_id, patient_name, study_date, study_time,
                        study_description, modality, instances_count, storage_folder,
                        archive_path, archive_size_bytes, preview_image_path, telegram_status,
                        local_copy_status, local_stored_at,
                        last_sent_instances, created_at, completed_at,
                        progress_stage, progress_percent, progress_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, 'PENDING', 'STORED', ?, 0, ?, ?, 'IDLE', 100, '')
                """, (
                    uid, p_id, p_name, s_date, s_time, s_desc, modality,
                    slices_cnt, str(zip_path), zip_size,
                    str(preview_path) if has_preview else "",
                    now_iso, now_iso, now_iso
                ))
                study_db_id = cursor.lastrowid

            conn.commit()
            conn.close()

        log_event("INFO", f"📥 DICOM Import muvaffaqiyatli: {p_name} ({slices_cnt} kadr, {round(zip_size/1024/1024, 1)} MB)")

        # 4. KT apparatiga C-STORE orqali uzatish (agar belgilangan bo'lsa)
        ct_sent = 0
        ct_failed = 0
        if send_to_ct:
            try:
                ct_sent, ct_failed = send_files_to_ct_device(dcm_files, patient_name=p_name)
            except Exception as e_ct:
                logger.error(f"KT apparatiga uzatishda xatolik: {e_ct}")
                log_event("WARNING", f"KT apparatiga uzatishda xatolik [{p_name}]: {e_ct}")

        results.append({
            "study_id": study_db_id,
            "patient_name": p_name,
            "patient_id": p_id,
            "study_date": s_date,
            "instances_count": slices_cnt,
            "archive_size_mb": round(zip_size / 1024 / 1024, 1),
            "sent_to_ct": send_to_ct,
            "ct_sent": ct_sent,
            "ct_failed": ct_failed
        })

    return results

def import_from_zip(zip_path: Path, send_to_ct: bool = True) -> List[Dict[str, Any]]:
    """ZIP faylni ochib import qilish"""
    temp_dir = Path(tempfile.mkdtemp(prefix="dicom_import_zip_"))
    try:
        with zipfile.ZipFile(str(zip_path), 'r') as zf:
            zf.extractall(str(temp_dir))
        return process_imported_dicom_dir(temp_dir, send_to_ct=send_to_ct)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
