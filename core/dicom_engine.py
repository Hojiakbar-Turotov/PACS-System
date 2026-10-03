import os
import sys
import time
import socket
import queue
import threading
import logging
from datetime import datetime
from pathlib import Path

import pydicom
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pynetdicom import (
    AE, evt, AllStoragePresentationContexts, StoragePresentationContexts
)
from pynetdicom.sop_class import (
    Verification,
    ModalityWorklistInformationFind,
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelMove,
    StudyRootQueryRetrieveInformationModelMove,
    PatientRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelGet,
    StorageCommitmentPushModel
)

from core.config import (
    PACS_HOST, PACS_PORT, PACS_AET,
    CT_HOST, CT_PORT, CT_AET,
    STORAGE_DIR, STUDY_INACTIVITY_TIMEOUT
)
from core.database import get_connection, log_event

logger = logging.getLogger("DICOM_ENGINE")

class RadiantForwarder:
    """GE CT yoki tarmoqdan kelgan DICOM kadrlarni agar RadiAnt (127.0.0.1:11113) ochiq bo'lsa darhol uzatish"""
    def __init__(self):
        self.queue = queue.Queue(maxsize=10000)
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def forward(self, dataset):
        try:
            self.queue.put_nowait(dataset)
        except queue.Full:
            pass

    def _is_radiant_listening(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.04)
                return s.connect_ex(('127.0.0.1', 11113)) == 0
        except Exception:
            return False

    def _run(self):
        while True:
            try:
                ds = self.queue.get()
                if not self._is_radiant_listening():
                    # RadiAnt ochiq emas, navbatni tozalash
                    while not self.queue.empty():
                        try:
                            self.queue.get_nowait()
                        except Exception:
                            break
                    continue

                # RadiAnt 11113 portda kutmoqda! Bitta assotsiatsiya orqali yuborish
                ae = AE(ae_title=b'SABADARMON')
                ae.add_requested_context(ds.SOPClassUID)
                assoc = ae.associate('127.0.0.1', 11113, ae_title=b'RADIANT', contexts=StoragePresentationContexts)
                if assoc.is_established:
                    assoc.send_c_store(ds)
                    # Navbatda turgan qolgan kadrlarni ham shu bitta assotsiatsiya orqali uzatish
                    while True:
                        try:
                            next_ds = self.queue.get(timeout=0.3)
                            assoc.send_c_store(next_ds)
                        except queue.Empty:
                            break
                        except Exception:
                            break
                    assoc.release()
            except Exception:
                time.sleep(0.05)

class DicomEngine:
    def __init__(self, on_study_completed_callback=None):
        self.ae = AE(ae_title=PACS_AET.encode())
        self.server = None
        self.on_study_completed = on_study_completed_callback
        self.forwarder = RadiantForwarder()
        
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
        
        # 4. Query / Retrieve for RadiAnt / Workstations (Find, Move, Get)
        self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelFind)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
        self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelMove)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelMove)
        self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelGet)
        self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelGet)
        
        # 5. Storage Commitment (GE CT Archive Node uchun)
        self.ae.add_supported_context(StorageCommitmentPushModel, scu_role=True, scp_role=True)

    def _setup_handlers(self):
        self.handlers = [
            (evt.EVT_REQUESTED, self.handle_conn_requested),
            (evt.EVT_ACCEPTED, self.handle_conn_accepted),
            (evt.EVT_C_ECHO, self.handle_echo),
            (evt.EVT_C_FIND, self.handle_find),
            (evt.EVT_C_MOVE, self.handle_move),
            (evt.EVT_C_GET, self.handle_get),
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
                
            # 2. RadiAnt uchun Query/Retrieve (Q/R) C-FIND
            else:
                log_event("INFO", f"RadiAnt Q/R C-FIND so'rovi keldi ({calling_aet})")
                identifier = event.identifier
                query_level = getattr(identifier, 'QueryRetrieveLevel', 'STUDY')
                p_name = getattr(identifier, 'PatientName', '')
                p_id = getattr(identifier, 'PatientID', '')
                s_date = getattr(identifier, 'StudyDate', '')
                s_uid = getattr(identifier, 'StudyInstanceUID', '')
                
                sql = "SELECT * FROM studies WHERE 1=1"
                params = []
                
                if p_name and str(p_name).strip() and str(p_name).strip() != "*":
                    clean = str(p_name).replace("*", "%").replace("^", "%").strip()
                    sql += " AND patient_name LIKE ?"
                    params.append(f"%{clean}%")
                    
                if p_id and str(p_id).strip() and str(p_id).strip() != "*":
                    clean = str(p_id).replace("*", "%").strip()
                    sql += " AND patient_id LIKE ?"
                    params.append(f"%{clean}%")
                    
                if s_date and str(s_date).strip() and str(s_date).strip() != "*":
                    dt_str = str(s_date).strip()
                    if "-" in dt_str:
                        s1, s2 = dt_str.split("-", 1)
                        if s1:
                            sql += " AND study_date >= ?"
                            params.append(s1.strip().replace("-", "").replace(".", ""))
                        if s2:
                            sql += " AND study_date <= ?"
                            params.append(s2.strip().replace("-", "").replace(".", ""))
                    else:
                        c_d = dt_str.replace("-", "").replace(".", "")
                        sql += " AND (study_date = ? OR study_date LIKE ?)"
                        params.append(c_d)
                        params.append(f"%{c_d}%")
                        
                if s_uid and str(s_uid).strip():
                    sql += " AND study_instance_uid = ?"
                    params.append(str(s_uid).strip())
                    
                sql += " ORDER BY id DESC LIMIT 200"
                
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(sql, params)
                studies = cursor.fetchall()
                conn.close()
                
                for s_row in studies:
                    s = dict(s_row)
                    ds = Dataset()
                    ds.QueryRetrieveLevel = query_level
                    ds.PatientID = str(s.get('patient_id') or "")
                    ds.PatientName = str(s.get('patient_name') or "").replace(" ", "^")
                    ds.PatientBirthDate = str(s.get('birth_date') or "")
                    ds.PatientSex = str(s.get('gender') or "O")
                    ds.StudyInstanceUID = str(s.get('study_instance_uid') or "")
                    ds.StudyDate = str(s.get('study_date') or "")
                    ds.StudyTime = str(s.get('study_time') or "000000")
                    ds.StudyDescription = str(s.get('study_description') or "CT Study")
                    ds.Modality = str(s.get('modality') or "CT")
                    ds.ModalitiesInStudy = [str(s.get('modality') or "CT")]
                    ds.NumberOfStudyRelatedInstances = int(s.get('instances_count') or 0)
                    ds.NumberOfStudyRelatedSeries = 1
                    ds.AccessionNumber = ""
                    if query_level == 'SERIES':
                        ds.SeriesInstanceUID = f"{s.get('study_instance_uid')}.1"
                        ds.SeriesNumber = 1
                        ds.SeriesDescription = str(s.get('study_description') or "Series 1")
                        ds.NumberOfSeriesRelatedInstances = int(s.get('instances_count') or 0)
                    yield (0xFF00, ds)
                return
        except Exception as e:
            logger.error(f"C-FIND qayta ishlashda xatolik: {e}", exc_info=True)
            log_event("ERROR", f"C-FIND xatoligi: {e}")
            return

    def handle_move(self, event):
        """RadiAnt yoki boshqa ishchi stansiyalardan C-MOVE so'rovini qabul qilish va tasvirlarni jo'natish"""
        try:
            identifier = event.identifier
            study_uid = str(identifier.get('StudyInstanceUID', '')).strip()
            destination = str(getattr(event, 'move_destination', 'RADIANT')).strip()
            requestor_ip = getattr(event.assoc.requestor, 'address', '127.0.0.1')
            
            # Destination mapping
            if destination == 'RADIANT':
                dest_ip = '127.0.0.1' if requestor_ip in ('127.0.0.1', 'localhost', '::1') else requestor_ip
                dest_port = 11113
            elif destination == CT_AET:
                dest_ip = CT_HOST
                dest_port = CT_PORT
            elif destination == 'AW01':
                dest_ip = '192.168.10.251'
                dest_port = 4006
            else:
                dest_ip = requestor_ip
                dest_port = 11113
            
            log_event("INFO", f"📥 RadiAnt C-MOVE so'rovi keldi: StudyUID={study_uid[:16]}..., Destination={destination} ({dest_ip}:{dest_port})")
            
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM studies WHERE study_instance_uid = ?", (study_uid,))
            study_row = cursor.fetchone()
            conn.close()
            study = dict(study_row) if study_row else None
            
            datasets = []
            
            # 1. ZIP arxiv ichidan o'qish
            if study and study.get("archive_path") and Path(study["archive_path"]).exists():
                try:
                    import zipfile, io
                    with zipfile.ZipFile(study["archive_path"], 'r') as zf:
                        for name in zf.namelist():
                            if name.lower().endswith('.dcm'):
                                dcm_bytes = zf.read(name)
                                ds = pydicom.dcmread(io.BytesIO(dcm_bytes))
                                datasets.append(ds)
                except Exception as e_zip:
                    logger.error(f"ZIP dan dcm o'qishda xatolik: {e_zip}")
                    
            # 2. Storage papkasidan o'qish
            if not datasets and study and study.get("storage_folder") and Path(study["storage_folder"]).exists():
                s_folder = Path(study["storage_folder"])
                for f in sorted(s_folder.glob("*.dcm")):
                    try:
                        datasets.append(pydicom.dcmread(str(f)))
                    except Exception:
                        pass
            
            # 3. Active studies (hozir yuklanayotgan) papkasidan o'qish
            if not datasets and study_uid in self.active_studies:
                act_f = self.active_studies[study_uid].get("folder")
                if act_f and act_f.exists():
                    for f in sorted(act_f.glob("*.dcm")):
                        try:
                            datasets.append(pydicom.dcmread(str(f)))
                        except Exception:
                            pass
            
            # 4. Agar lokal serverda topilmasa, GE KT apparatidan darhol tortib olish
            if not datasets and study_uid:
                log_event("INFO", f"⚡ Tekshiruv serverda yo'q, GE KT apparatidan RadiAnt uchun yuklab olinmoqda ({study_uid[:16]})...")
                from core.ct_poller import retrieve_study_from_ct
                retrieve_study_from_ct(study_uid, send_telegram=False)
                
                for _ in range(25):
                    time.sleep(1)
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT storage_folder, archive_path FROM studies WHERE study_instance_uid = ?", (study_uid,))
                    s_new = cursor.fetchone()
                    conn.close()
                    if s_new:
                        if s_new["archive_path"] and Path(s_new["archive_path"]).exists():
                            import zipfile, io
                            with zipfile.ZipFile(s_new["archive_path"], 'r') as zf:
                                for name in zf.namelist():
                                    if name.lower().endswith('.dcm'):
                                        datasets.append(pydicom.dcmread(io.BytesIO(zf.read(name))))
                            if datasets:
                                break
                        elif s_new["storage_folder"] and Path(s_new["storage_folder"]).exists():
                            for f in sorted(Path(s_new["storage_folder"]).glob("*.dcm")):
                                datasets.append(pydicom.dcmread(str(f)))
                            if datasets:
                                break

            if not datasets:
                log_event("WARNING", f"RadiAnt C-MOVE uchun tasvirlar topilmadi: {study_uid}")
                yield (dest_ip, dest_port, {"contexts": StoragePresentationContexts})
                yield 0
                return

            log_event("INFO", f"📤 RadiAnt ga {len(datasets)} ta tasvir uzatilmoqda ({dest_ip}:{dest_port})...")
            
            # 1-yield: Maqsad IP, port va StoragePresentationContexts
            yield (dest_ip, dest_port, {"contexts": StoragePresentationContexts})
            # 2-yield: Jami yuboriladigan kadrlar soni
            yield len(datasets)
            
            # Qolgan yieldlar: Har bir kadr
            for ds in datasets:
                yield (0xFF00, ds)

            log_event("INFO", f"✅ RadiAnt ga barcha {len(datasets)} ta tasvir muvaffaqiyatli yetkazildi!")

        except Exception as e:
            logger.error(f"C-MOVE qayta ishlash xatosi: {e}", exc_info=True)
            log_event("ERROR", f"C-MOVE xatosi: {e}")
            yield (None, None)
            return

    def handle_get(self, event):
        """RadiAnt C-GET so'rovi (agar C-MOVE o'rniga C-GET ishlatilsa)"""
        try:
            identifier = event.identifier
            study_uid = str(identifier.get('StudyInstanceUID', '')).strip()
            
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM studies WHERE study_instance_uid = ?", (study_uid,))
            study_row = cursor.fetchone()
            conn.close()
            study = dict(study_row) if study_row else None
            
            datasets = []
            if study and study.get("archive_path") and Path(study["archive_path"]).exists():
                import zipfile, io
                with zipfile.ZipFile(study["archive_path"], 'r') as zf:
                    for name in zf.namelist():
                        if name.lower().endswith('.dcm'):
                            datasets.append(pydicom.dcmread(io.BytesIO(zf.read(name))))
            elif study and study.get("storage_folder") and Path(study["storage_folder"]).exists():
                for f in sorted(Path(study["storage_folder"]).glob("*.dcm")):
                    datasets.append(pydicom.dcmread(str(f)))
                    
            yield len(datasets)
            for ds in datasets:
                yield (0xFF00, ds)
        except Exception as e:
            logger.error(f"C-GET xatosi: {e}")
            yield 0
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

        # RadiAnt ochiq bo'lsa darhol uzatish (jonli ko'rsatish uchun)
        try:
            self.forwarder.forward(ds)
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
