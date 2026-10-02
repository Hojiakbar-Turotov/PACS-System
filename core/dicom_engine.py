import os
import sys
import time
import threading
import logging
from datetime import datetime
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pynetdicom import (
    AE, evt, AllStoragePresentationContexts
)
from pynetdicom.sop_class import (
    Verification,
    ModalityWorklistInformationFind,
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
    StorageCommitmentPushModel
)

from core.config import (
    PACS_HOST, PACS_PORT, PACS_AET,
    STORAGE_DIR, STUDY_INACTIVITY_TIMEOUT
)
from core.database import get_connection, log_event

logger = logging.getLogger("DICOM_ENGINE")

class DicomEngine:
    def __init__(self, on_study_completed_callback=None):
        self.ae = AE(ae_title=PACS_AET.encode())
        self.server = None
        self.on_study_completed = on_study_completed_callback
        
        # Debounce timerlar: {study_uid: {"timer": Timer, "last_seen": timestamp, "folder": Path}}
        self.active_studies = {}
        self.studies_lock = threading.Lock()
        
        self._setup_contexts()
        self._setup_handlers()

    def _setup_contexts(self):
        # 1. Barcha DICOM Storage SOP classlar
        self.ae.supported_contexts = AllStoragePresentationContexts
        
        # 2. Verification (C-ECHO)
        self.ae.add_supported_context(Verification)
        
        # 3. Modality Worklist (C-FIND MWL)
        self.ae.add_supported_context(ModalityWorklistInformationFind)
        
        # 4. Query / Retrieve for RadiAnt / Workstations
        self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelFind)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
        
        # 5. Storage Commitment (GE CT Archive Node uchun)
        self.ae.add_supported_context(StorageCommitmentPushModel, scu_role=True, scp_role=True)

    def _setup_handlers(self):
        self.handlers = [
            (evt.EVT_REQUESTED, self.handle_conn_requested),
            (evt.EVT_ACCEPTED, self.handle_conn_accepted),
            (evt.EVT_C_ECHO, self.handle_echo),
            (evt.EVT_C_FIND, self.handle_find),
            (evt.EVT_C_STORE, self.handle_store),
            (evt.EVT_N_ACTION, self.handle_n_action),
        ]

    def handle_n_action(self, event):
        """Storage Commitment N-ACTION qabul qilish (GE Archive Node tasdiqlash)"""
        calling_aet = str(getattr(event.assoc.requestor, 'ae_title', 'UNKNOWN')).strip()
        log_event("MONITOR", f"💾 Storage Commitment N-ACTION qabul qilindi ({calling_aet})")
        return 0x0000

    def handle_conn_requested(self, event):
        """Yangi tarmoq ulanishi kelganda monitorga yozish"""
        requestor = event.assoc.requestor
        calling_ae = str(getattr(requestor, 'ae_title', 'UNKNOWN')).strip()
        address = getattr(requestor, 'address', 'UNKNOWN')
        port = getattr(requestor, 'port', 'UNKNOWN')
        log_event("MONITOR", f"📡 Tarmoq ulanishi: IP={address}:{port} | Calling AE='{calling_ae}'")
        print(f"[MONITOR] Yangi DICOM ulanish: {address}:{port} [{calling_ae}]")

    def handle_conn_accepted(self, event):
        requestor = event.assoc.requestor
        calling_ae = str(getattr(requestor, 'ae_title', 'UNKNOWN')).strip()
        log_event("MONITOR", f"✅ DICOM Assotsiatsiya o'rnatildi: AE='{calling_ae}'")

    def handle_echo(self, event):
        """C-ECHO Ping qabul qilish"""
        calling_aet = str(getattr(event.assoc.requestor, 'ae_title', 'UNKNOWN')).strip()
        log_event("INFO", f"🔔 C-ECHO Ping qabul qilindi ({calling_aet})")
        return 0x0000

    def handle_find(self, event):
        """GE CT yoki RadiAnt'dan C-FIND so'rovlarini qayta ishlash"""
        try:
            calling_aet = str(getattr(event.assoc.requestor, 'ae_title', 'UNKNOWN')).strip()
            model = str(event.context.abstract_syntax)
            mwl_uid = str(ModalityWorklistInformationFind)
            req_ds = event.identifier
            
            # 1. Modality Worklist so'rovi (GE CT dan)
            if model == mwl_uid:
                log_event("MONITOR", f"🔍 MODALITY WORKLIST so'rovi keldi ({calling_aet})! Qidiruv parametrlari: PatientName='{getattr(req_ds, 'PatientName', '*')}', PatientID='{getattr(req_ds, 'PatientID', '*')}'")
                
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM worklist 
                    WHERE status = 'SCHEDULED' 
                    ORDER BY id ASC
                """)
                patients = cursor.fetchall()
                conn.close()
                
                if not patients:
                    log_event("INFO", f"Worklist so'roviga javob: Navbatda faol kutilayotgan bemorlar yo'q.")
                    return
                
                log_event("INFO", f"Worklist so'roviga javob: {len(patients)} ta kutilayotgan bemor yuborilmoqda.")
                for p in patients:
                    ds = Dataset()
                    clean_name = p['patient_name'].replace(" ", "^")
                    ds.PatientName = clean_name
                    ds.PatientID = str(p['patient_id'])
                    
                    b_date = p['birth_date'].replace("-", "").replace(".", "") if p['birth_date'] else ""
                    ds.PatientBirthDate = b_date
                    ds.PatientSex = p['gender'] if p['gender'] else "O"
                    
                    ds.AccessionNumber = str(p['accession_number'])
                    ds.StudyInstanceUID = pydicom.uid.generate_uid()
                    ds.RequestedProcedureID = f"PROC_{p['id']}"
                    ds.RequestedProcedureDescription = p['exam_description'] or "CT Exam"
                    ds.ReferringPhysicianName = (p['referring_physician'] or "Physician").replace(" ", "^")
                    
                    sps = Dataset()
                    sps.ScheduledStationAETitle = "CT01"
                    sps.ScheduledProcedureStepStartDate = datetime.now().strftime("%Y%m%d")
                    sps.ScheduledProcedureStepStartTime = datetime.now().strftime("%H%M%S")
                    sps.Modality = "CT"
                    sps.ScheduledProcedureStepDescription = p['exam_description'] or "CT Exam"
                    sps.ScheduledProcedureStepID = f"SPS_{p['id']}"
                    sps.ScheduledPerformingPhysicianName = (p['operator'] or "Operator").replace(" ", "^")
                    
                    ds.ScheduledProcedureStepSequence = Sequence([sps])
                    
                    log_event("MONITOR", f"  ➡️ Bemor uzatildi: {clean_name} (ID: {p['patient_id']}, Acc: {p['accession_number']})")
                    yield (0xFF00, ds)
                return
                
            # 2. RadiAnt uchun Query/Retrieve (Q/R)
            else:
                log_event("INFO", f"RadiAnt Q/R C-FIND so'rovi keldi ({calling_aet})")
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM studies ORDER BY id DESC LIMIT 50")
                studies = cursor.fetchall()
                conn.close()
                
                for s in studies:
                    ds = Dataset()
                    ds.PatientID = s['patient_id'] or ""
                    ds.PatientName = (s['patient_name'] or "").replace(" ", "^")
                    ds.StudyInstanceUID = s['study_instance_uid']
                    ds.StudyDate = s['study_date'] or ""
                    ds.StudyTime = s['study_time'] or ""
                    ds.StudyDescription = s['study_description'] or ""
                    ds.Modality = s['modality'] or "CT"
                    ds.NumberOfStudyRelatedInstances = s['instances_count'] or 0
                    yield (0xFF00, ds)
                return
        except Exception as e:
            logger.error(f"C-FIND qayta ishlashda xatolik: {e}", exc_info=True)
            log_event("ERROR", f"C-FIND xatoligi: {e}")
            return

    def handle_store(self, event):
        """GE CT apparatidan kelayotgan DICOM tasvirlarni saqlash"""
        ds = event.dataset
        calling_aet = str(getattr(event.assoc.requestor, 'ae_title', 'UNKNOWN')).strip()
        
        # Metadata
        patient_id = getattr(ds, 'PatientID', 'UNKNOWN_ID').strip()
        patient_name = str(getattr(ds, 'PatientName', 'UNKNOWN_NAME')).replace('^', ' ').strip()
        study_uid = getattr(ds, 'StudyInstanceUID', pydicom.uid.generate_uid())
        sop_uid = getattr(ds, 'SOPInstanceUID', pydicom.uid.generate_uid())
        study_date = getattr(ds, 'StudyDate', datetime.now().strftime('%Y%m%d'))
        study_desc = getattr(ds, 'StudyDescription', 'CT Study')
        modality = getattr(ds, 'Modality', 'CT')
        
        # Papka tuzish: storage / YYYYMMDD_PatientName_PatientID
        safe_name = "".join(c for c in patient_name if c.isalnum() or c in (' ', '_', '-')).strip()
        safe_id = "".join(c for c in patient_id if c.isalnum() or c in ('_', '-')).strip()
        study_folder_name = f"{study_date}_{safe_name}_{safe_id}"
        study_dir = STORAGE_DIR / study_folder_name
        study_dir.mkdir(parents=True, exist_ok=True)
        
        # Faylni saqlash
        file_path = study_dir / f"{sop_uid}.dcm"
        ds.file_meta = event.file_meta
        ds.is_little_endian = event.context.transfer_syntax.is_little_endian
        ds.is_implicit_VR = event.context.transfer_syntax.is_implicit_VR
        ds.save_as(file_path, write_like_original=False)

        try:
            from core.progress_tracker import record_slice_received
            record_slice_received(study_uid)
        except Exception:
            pass
        
        # Debounce taymerini yangilash
        with self.studies_lock:
            if study_uid in self.active_studies:
                self.active_studies[study_uid]["timer"].cancel()
            
            count = self.active_studies.get(study_uid, {}).get("count", 0) + 1
            
            # Yangi taymer qo'yish
            timer = threading.Timer(
                STUDY_INACTIVITY_TIMEOUT,
                self._study_finished_trigger,
                args=[study_uid, study_dir, patient_id, patient_name, study_desc, study_date, modality]
            )
            self.active_studies[study_uid] = {
                "timer": timer,
                "folder": study_dir,
                "count": count
            }
            timer.start()
            
            if count == 1:
                log_event("MONITOR", f"📥 Tasvirlarni qabul qilish boshlandi: {patient_name} (ID: {patient_id}) - {study_desc}")
            elif count % 50 == 0:
                log_event("MONITOR", f"  📥 Qabul qilindi: {count} ta kadr [{patient_name}]")
            
        return 0x0000  # Success

    def _study_finished_trigger(self, study_uid, study_dir, patient_id, patient_name, study_desc, study_date, modality):
        """Oxirgi tasvirdan keyin 15s o'tgach, tekshiruv yakunlanganini e'lon qilish"""
        with self.studies_lock:
            if study_uid in self.active_studies:
                del self.active_studies[study_uid]
                
        log_event("INFO", f"Tekshiruv qabul qilindi: {patient_name} ({patient_id}), Papka: {study_dir.name}")
        
        if self.on_study_completed:
            self.on_study_completed(study_uid, study_dir, patient_id, patient_name, study_desc, study_date, modality)

    def start(self):
        log_event("INFO", f"PACS Server ishga tushmoqda: {PACS_HOST}:{PACS_PORT} (AE: {PACS_AET})")
        self.server = self.ae.start_server(
            (PACS_HOST, PACS_PORT),
            block=False,
            evt_handlers=self.handlers
        )
        print(f"[*] DICOM PACS Server faol: {PACS_HOST}:{PACS_PORT} [AE: {PACS_AET}]")

    def stop(self):
        if self.server:
            self.server.shutdown()
            log_event("INFO", "PACS Server to'xtatildi")
            print("[*] DICOM PACS Server to'xtatildi.")
