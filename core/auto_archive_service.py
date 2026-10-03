import time
import threading
import logging
from datetime import datetime
from pydicom.dataset import Dataset
from pynetdicom import AE
from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind

from core.config import (
    CT_HOST, CT_PORT, CT_AET,
    load_settings
)
from core.database import get_connection, log_event
from core.ct_poller import retrieve_study_from_ct

logger = logging.getLogger("AUTO_ARCHIVE_SERVICE")

class AutoArchiveDaemon:
    def __init__(self):
        self.running = False
        self.thread = None
        # study_uid -> { "last_count": int, "stable_rounds": int, "patient_name": str }
        self.stability_tracker = {}
        self.last_deep_scan_time = 0
        self.lock = threading.Lock()

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        print("[*] Avtomatik kuzatuv, rekon barqarorligi va 3-soatlik chuqur arxivlash xizmati ishga tushirildi.")
        log_event("SYSTEM", "Avtomatik kuzatuv va barqarorlik (recon) tekshiruvi faol")

    def stop(self):
        self.running = False

    def _loop(self):
        while self.running:
            try:
                cfg = load_settings()
                enabled = cfg.get("auto_archive_enabled", True)
                poll_interval = int(cfg.get("new_study_poll_interval", 60))
                deep_interval = int(cfg.get("deep_scan_interval", 10800))
                req_stability = int(cfg.get("recon_stability_checks", 3))

                if enabled:
                    # 1. Tezkor tekshirish (har 60s) va rekon barqarorligini hisoblash
                    self._check_recent_studies(req_stability)

                    # 2. Chuqur 3 soatlik to'liq tekshirish (deep scan)
                    now_t = time.time()
                    if now_t - self.last_deep_scan_time >= deep_interval:
                        self.last_deep_scan_time = now_t
                        self._run_deep_reconciliation()
            except Exception as e:
                logger.error(f"AutoArchiveDaemon siklida xatolik: {e}", exc_info=True)

            # Keyingi tekshiruvgacha uxlash
            poll_interval = int(load_settings().get("new_study_poll_interval", 60))
            time.sleep(max(10, poll_interval))

    def _check_recent_studies(self, required_stability_rounds: int):
        """Bugungi va yangi qo'shilgan tekshiruvlarni so'rash va rekon barqarorligini tekshirish"""
        today_str = datetime.now().strftime("%Y%m%d")
        ae = AE(ae_title=b'RADIANT')
        ae.network_timeout = 5
        ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
        assoc = ae.associate(CT_HOST, CT_PORT, ae_title=CT_AET.encode())
        if not assoc.is_established:
            return

        q = Dataset()
        q.QueryRetrieveLevel = 'STUDY'
        q.PatientName = ''
        q.PatientID = ''
        q.StudyDate = today_str  # Bugungi sana bo'yicha tezkor
        q.StudyTime = ''
        q.StudyDescription = ''
        q.StudyInstanceUID = ''
        q.NumberOfStudyRelatedInstances = ''

        responses = assoc.send_c_find(q, StudyRootQueryRetrieveInformationModelFind)
        found_studies = []
        for s, identifier in responses:
            if s and s.Status in (0xFF00, 0xFF01) and identifier:
                uid = str(identifier.get('StudyInstanceUID', '')).strip()
                p_name = str(identifier.get('PatientName', '')).replace('^', ' ').strip()
                p_id = str(identifier.get('PatientID', '')).strip()
                s_desc = str(identifier.get('StudyDescription', '')).strip()
                inst_cnt = int(identifier.get('NumberOfStudyRelatedInstances', 0) or 0)
                if uid:
                    found_studies.append({
                        'uid': uid, 'name': p_name, 'id': p_id, 'desc': s_desc, 'instances': inst_cnt
                    })
        assoc.release()

        if not found_studies:
            return

        # Bazadagi holatni tekshirish
        conn = get_connection()
        cursor = conn.cursor()
        
        for item in found_studies:
            uid = item['uid']
            inst_cnt = item['instances']
            name = item['name']
            
            cursor.execute("SELECT id, instances_count, local_copy_status, telegram_status FROM studies WHERE study_instance_uid = ?", (uid,))
            db_row = cursor.fetchone()

            needs_archive = False
            if not db_row:
                # Yangi bemor, bazada umuman yo'q
                needs_archive = True
                cursor.execute("""
                    INSERT INTO studies (
                        study_instance_uid, patient_id, patient_name, study_date, study_time,
                        study_description, modality, instances_count, storage_folder, archive_path,
                        archive_size_bytes, preview_image_path, telegram_status, local_copy_status,
                        last_sent_instances, created_at, completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'CT', ?, '', '', 0, '', 'ON_CT_DEVICE', 'NOT_DOWNLOADED', 0, ?, ?)
                """, (
                    uid, item['id'], name, today_str, datetime.now().strftime("%H:%M:%S"),
                    item['desc'], inst_cnt, datetime.now().isoformat(), datetime.now().isoformat()
                ))
                conn.commit()
            else:
                db_inst = db_row['instances_count'] or 0
                db_stored = db_row['local_copy_status'] == 'STORED'
                # Agar hali yuklab olinmagan bo'lsa yoki kadrlar soni oshgan bo'lsa
                if not db_stored or (inst_cnt > db_inst and inst_cnt > 0):
                    needs_archive = True

            if needs_archive and inst_cnt > 0:
                with self.lock:
                    if uid not in self.stability_tracker:
                        self.stability_tracker[uid] = {
                            "last_count": inst_cnt,
                            "stable_rounds": 1,
                            "patient_name": name
                        }
                        log_event("MONITOR", f"🆕 Yangi tekshiruv aniqlandi: {name} ({inst_cnt} kadr). Rekon barqarorligi kuzatilmoqda (1/{required_stability_rounds})...")
                    else:
                        prev = self.stability_tracker[uid]
                        if inst_cnt != prev["last_count"]:
                            # Kadrlar soni oshmoqda (rekon ketmoqda)
                            diff = inst_cnt - prev["last_count"]
                            prev["last_count"] = inst_cnt
                            prev["stable_rounds"] = 1
                            log_event("MONITOR", f"🔄 Rekonstruksiya davom etmoqda: {name} (+{diff} kadr -> jami {inst_cnt}). Barqarorlik kutish qayta boshlandi (1/{required_stability_rounds}).")
                        else:
                            # Kadrlar soni o'zgarmay turibdi
                            prev["stable_rounds"] += 1
                            log_event("MONITOR", f"⏳ Barqarorlik tekshiruvi: {name} ({inst_cnt} kadr o'zgarmadi) - {prev['stable_rounds']}/{required_stability_rounds}")

                            if prev["stable_rounds"] >= required_stability_rounds:
                                # 3 marta o'zgarmadi -> Rekon to'liq tugagan!
                                log_event("INFO", f"✅ Rekonstruksiya to'liq yakunlandi: {name} ({inst_cnt} kadr). Avtomatik navbatga qo'yildi va Telegramga arxivlanmoqda!")
                                del self.stability_tracker[uid]
                                cursor.execute("SELECT id FROM studies WHERE study_instance_uid = ?", (uid,))
                                s_row = cursor.fetchone()
                                if s_row:
                                    from core.batch_queue import batch_manager
                                    batch_manager.enqueue_studies([s_row["id"]])
                                else:
                                    threading.Thread(target=retrieve_study_from_ct, args=(uid, True), daemon=True).start()

        conn.close()

    def _run_deep_reconciliation(self):
        """Har 3 soatda KT apparatidagi barcha bemorlarni birma-bir to'liq solishtirish"""
        try:
            log_event("INFO", "🔍 [3-SOATLIK TEKSHIRUV] KT apparatidagi barcha bemorlar kadrlar soni to'liq solishtirilmoqda...")
            ae = AE(ae_title=b'RADIANT')
            ae.network_timeout = 10
            ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)
            assoc = ae.associate(CT_HOST, CT_PORT, ae_title=CT_AET.encode())
            if not assoc.is_established:
                log_event("WARNING", "[3-SOATLIK TEKSHIRUV] KT apparatiga ulanib bo'lmadi")
                return

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
            ct_items = []
            for s, identifier in responses:
                if s and s.Status in (0xFF00, 0xFF01) and identifier:
                    uid = str(identifier.get('StudyInstanceUID', '')).strip()
                    p_name = str(identifier.get('PatientName', '')).replace('^', ' ').strip()
                    inst_cnt = int(identifier.get('NumberOfStudyRelatedInstances', 0) or 0)
                    if uid:
                        ct_items.append((uid, p_name, inst_cnt))
            assoc.release()

            conn = get_connection()
            cursor = conn.cursor()
            updated_count = 0

            for uid, name, ct_inst in ct_items:
                cursor.execute("SELECT id, instances_count, last_sent_instances, local_copy_status FROM studies WHERE study_instance_uid = ?", (uid,))
                row = cursor.fetchone()
                if row:
                    local_inst = row['instances_count'] or 0
                    if ct_inst > local_inst and ct_inst > 0:
                        updated_count += 1
                        log_event("INFO", f"🔄 [QAYTA ARXIVLASH] Bemor {name} kadrlar soni oshgan ({local_inst} -> {ct_inst} kadr). Qayta yuklanmoqda...")
                        cursor.execute("UPDATE studies SET instances_count = ? WHERE study_instance_uid = ?", (ct_inst, uid))
                        conn.commit()
                        # Yangilangan kadrlar bilan qayta yuklab arxivlash va Telegramga uzatish
                        from core.batch_queue import batch_manager
                        batch_manager.enqueue_studies([row["id"]])
                        time.sleep(1)

            conn.close()
            log_event("INFO", f"✅ [3-SOATLIK TEKSHIRUV] Tugallandi. {len(ct_items)} ta tekshiruv ko'rildi, {updated_count} ta yangilangan tekshiruv qayta arxivlandi.")
        except Exception as e:
            logger.error(f"Chuqur tekshiruv xatosi: {e}", exc_info=True)
            log_event("ERROR", f"3-soatlik tekshiruv xatosi: {e}")
