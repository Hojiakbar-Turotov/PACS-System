import time
import threading
import logging
from datetime import datetime
from pydicom.dataset import Dataset
from pynetdicom import AE
from pynetdicom.sop_class import (
    StudyRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelMove
)

from core.config import CT_HOST, CT_PORT, CT_AET
from core.database import get_connection, log_event

logger = logging.getLogger("CT_POLLER")

def retrieve_study_from_ct(study_instance_uid: str, send_telegram: bool = False) -> bool:
    """GE CT apparatidan belgilangan tekshiruvni C-MOVE orqali PACS serverga tortib olish"""
    try:
        from core.processor import set_retrieval_intent
        set_retrieval_intent(study_instance_uid, send_telegram)
        
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, instances_count, patient_name FROM studies WHERE study_instance_uid = ?", (study_instance_uid,))
            s_row = cursor.fetchone()
            conn.close()
            if s_row:
                from core.progress_tracker import start_ct_download
                start_ct_download(s_row["id"], study_instance_uid, s_row["instances_count"] or 0)
        except Exception as e_p:
            logger.warning(f"Progress start xatosi: {e_p}")

        log_event("INFO", f"📥 KT apparatidan tekshiruv tortib olinmoqda (C-MOVE): {study_instance_uid[:15]}...")
        ae = AE(ae_title=b'RADIANT')
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelMove)
        assoc = ae.associate(CT_HOST, CT_PORT, ae_title=CT_AET.encode())
        if not assoc.is_established:
            log_event("ERROR", f"C-MOVE uchun KT apparatiga ulanib bo'lmadi ({CT_HOST}:{CT_PORT})")
            return False

        q = Dataset()
        q.QueryRetrieveLevel = 'STUDY'
        q.StudyInstanceUID = study_instance_uid
        responses = assoc.send_c_move(q, b'RADIANT', StudyRootQueryRetrieveInformationModelMove)
        success = True
        for status, identifier in responses:
            if status and status.Status not in (0xFF00, 0xFF01, 0x0000):
                success = False
        assoc.release()
        return success
    except Exception as e:
        logger.error(f"C-MOVE xatosi: {e}")
        log_event("ERROR", f"C-MOVE xatosi: {e}")
        return False

def sync_all_studies_from_ct() -> int:
    """GE CT apparatidagi barcha mavjud (727 ta) bemorlarni so'rab bazaga kiritish"""
    try:
        log_event("INFO", "📡 KT apparatidagi barcha bemorlar ro'yxati so'ralmoqda...")
        ae = AE(ae_title=b'RADIANT')
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        assoc = ae.associate(CT_HOST, CT_PORT, ae_title=CT_AET.encode())
        if not assoc.is_established:
            log_event("ERROR", "KT apparatiga ulanib bo'lmadi")
            return 0

        q = Dataset()
        q.QueryRetrieveLevel = 'STUDY'
        q.PatientName = ''
        q.PatientID = ''
        q.StudyDate = ''
        q.StudyTime = ''
        q.StudyDescription = ''
        q.StudyInstanceUID = ''
        q.NumberOfStudyRelatedInstances = ''

        responses = assoc.send_c_find(q, StudyRootQueryRetrieveInformationModelFind)
        items = []
        for s, identifier in responses:
            if s and s.Status in (0xFF00, 0xFF01) and identifier:
                uid = str(identifier.get('StudyInstanceUID', '')).strip()
                p_name = str(identifier.get('PatientName', '')).replace('^', ' ').strip()
                p_id = str(identifier.get('PatientID', '')).strip()
                s_date = str(identifier.get('StudyDate', '')).strip()
                s_time = str(identifier.get('StudyTime', '')).strip()
                s_desc = str(identifier.get('StudyDescription', '')).strip()
                inst_cnt = int(identifier.get('NumberOfStudyRelatedInstances', 0) or 0)
                if uid:
                    items.append({
                        'uid': uid,
                        'name': p_name or "Noma'lum",
                        'id': p_id or "-",
                        'date': s_date or datetime.now().strftime("%Y%m%d"),
                        'time': s_time or "00:00:00",
                        'desc': s_desc or "-",
                        'instances': inst_cnt
                    })
        assoc.release()

        if not items:
            return 0

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT study_instance_uid FROM studies")
        existing_uids = {r["study_instance_uid"] for r in cursor.fetchall()}

        new_count = 0
        for item in items:
            if item['uid'] not in existing_uids:
                cursor.execute("""
                    INSERT INTO studies (
                        study_instance_uid, patient_id, patient_name,
                        study_date, study_time, study_description,
                        modality, instances_count, storage_folder,
                        archive_path, archive_size_bytes, preview_image_path,
                        telegram_status, last_sent_instances, created_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'CT', ?, '', '', 0, '', 'ON_CT_DEVICE', 0, ?, ?)
                """, (
                    item['uid'], item['id'], item['name'],
                    item['date'], item['time'], item['desc'],
                    item['instances'], datetime.now().isoformat(), datetime.now().isoformat()
                ))
                new_count += 1
            else:
                cursor.execute("""
                    UPDATE studies SET
                        instances_count = CASE WHEN instances_count = 0 THEN ? ELSE instances_count END,
                        study_description = CASE WHEN study_description = '' OR study_description IS NULL OR study_description = '-' THEN ? ELSE study_description END
                    WHERE study_instance_uid = ?
                """, (item['instances'], item['desc'], item['uid']))

        conn.commit()
        conn.close()

        log_event("INFO", f"✅ KT apparatidagi barcha {len(items)} ta bemor to'liq sinxronlashtirildi ({new_count} ta yangi qo'shildi)")
        return len(items)
    except Exception as e:
        logger.error(f"Sinxronlash xatosi: {e}", exc_info=True)
        log_event("ERROR", f"KT bemorlarini sinxronlashda xatolik: {e}")
        return 0

class CTPoller:
    def __init__(self, interval_seconds=25):
        self.interval = interval_seconds
        self.running = False
        self.thread = None
        self.ae = AE(ae_title=b'RADIANT')
        self.ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        print(f"[*] GE CT monitoring skaneri faollashtirildi (har {self.interval} soniyada).")

    def stop(self):
        self.running = False

    def check_once(self):
        """GE CT apparatidan bugungi bemorlarni so'rash va solishtirish"""
        try:
            today_str = datetime.now().strftime('%Y%m%d')
            self.ae.network_timeout = 4
            assoc = self.ae.associate(CT_HOST, CT_PORT, ae_title=CT_AET.encode())
            if not assoc.is_established:
                return []

            q = Dataset()
            q.QueryRetrieveLevel = 'STUDY'
            q.PatientName = ''
            q.PatientID = ''
            q.StudyDate = today_str
            q.StudyTime = ''
            q.StudyDescription = ''
            q.StudyInstanceUID = ''

            responses = assoc.send_c_find(q, StudyRootQueryRetrieveInformationModelFind)
            ct_studies = []
            for status, identifier in responses:
                if status and status.Status in (0xFF00, 0xFF01) and identifier:
                    p_name = str(identifier.get('PatientName', '')).replace('^', ' ').strip()
                    p_id = str(identifier.get('PatientID', '')).strip()
                    p_desc = str(identifier.get('StudyDescription', '')).strip()
                    p_time = str(identifier.get('StudyTime', '')).strip()
                    study_uid = str(identifier.get('StudyInstanceUID', '')).strip()
                    
                    if p_name or p_id:
                        ct_studies.append({
                            "patient_name": p_name or "Noma'lum",
                            "patient_id": p_id or "-",
                            "study_desc": p_desc or "CT Tekshiruv",
                            "study_time": p_time,
                            "study_uid": study_uid
                        })
            assoc.release()

            # Bazadagi bemorlar bilan solishtirish
            if ct_studies:
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT patient_id, patient_name FROM worklist")
                existing_worklist = {r["patient_id"]: r["patient_name"] for r in cursor.fetchall()}
                
                cursor.execute("SELECT patient_id FROM studies")
                existing_studies = {r["patient_id"] for r in cursor.fetchall()}
                
                for s in ct_studies:
                    p_id = s["patient_id"]
                    p_name = s["patient_name"]
                    
                    if p_id not in existing_worklist and p_id not in existing_studies:
                        accession_num = f"CT{today_str[-4:]}{s['study_time'][:4] if s['study_time'] else '0000'}"
                        cursor.execute("""
                            INSERT INTO worklist (
                                accession_number, patient_id, patient_name,
                                exam_description, scheduled_date, scheduled_time,
                                status, origin, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, 'CT_DIRECT', 'CT_DEVICE', ?)
                        """, (
                            accession_num, p_id, p_name,
                            s["study_desc"], datetime.now().strftime("%Y-%m-%d"),
                            s["study_time"], datetime.now().isoformat()
                        ))
                        conn.commit()
                        log_event("WARNING", f"⚠️ Yangi bemor aniqlandi: KT apparatida to'g'ridan-to'g'ri ro'yxatdan o'tgan! [{p_name} - ID: {p_id}]")
                conn.close()

            return ct_studies
        except Exception as e:
            logger.error(f"CT Poller xatoligi: {e}")
            return []

    def _poll_loop(self):
        while self.running:
            try:
                self.check_once()
            except Exception as e:
                logger.error(f"CT Poller loop error: {e}")
            time.sleep(self.interval)
