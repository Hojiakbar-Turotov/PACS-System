from datetime import datetime
from pydicom.dataset import Dataset
from pynetdicom import AE
from pynetdicom.sop_class import StudyRootQueryRetrieveInformationModelFind

ae = AE(ae_title=b'RADIANT')
ae.add_requested_context(StudyRootQueryRetrieveInformationModelFind)

print("[*] GE CT apparatiga so'rov yuborilmoqda (192.168.10.250:4006)...")
assoc = ae.associate('192.168.10.250', 4006, ae_title=b'CT01')
if assoc.is_established:
    q = Dataset()
    q.QueryRetrieveLevel = 'STUDY'
    q.PatientName = ''
    q.PatientID = ''
    q.StudyDate = datetime.now().strftime('%Y%m%d')
    q.StudyTime = ''
    q.StudyDescription = ''
    q.ModalitiesInStudy = ''
    q.StudyInstanceUID = ''
    
    responses = assoc.send_c_find(q, StudyRootQueryRetrieveInformationModelFind)
    count = 0
    for status, identifier in responses:
        if status and status.Status in (0xFF00, 0xFF01) and identifier:
            count += 1
            p_name = str(identifier.get('PatientName', 'Noma\'lum'))
            p_id = str(identifier.get('PatientID', '-'))
            p_desc = str(identifier.get('StudyDescription', '-'))
            p_time = str(identifier.get('StudyTime', '-'))
            print(f"[{count}] Bemor: {p_name} | ID: {p_id} | Tekshiruv: {p_desc} | Vaqt: {p_time}")
            
    print(f"[*] Bugungi jami tekshiruvlar GE CT da: {count}")
    assoc.release()
else:
    print("[!] Ulanish amalga oshmadi!")
