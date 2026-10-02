import time
from datetime import datetime
import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pynetdicom import AE
from pynetdicom.sop_class import CTImageStorage

print("[*] Test CT tasvirlarini yaratish...")
study_uid = pydicom.uid.generate_uid()
series_uid = pydicom.uid.generate_uid()
patient_id = "P-1518"
patient_name = "Toshmatov^Ali"

datasets = []
for i in range(1, 4):
    sop_uid = pydicom.uid.generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = file_meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = sop_uid
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.PatientID = patient_id
    ds.PatientName = patient_name
    ds.StudyDate = datetime.now().strftime("%Y%m%d")
    ds.StudyTime = datetime.now().strftime("%H%M%S")
    ds.StudyDescription = "Bosh miya MSKT (Sinov)"
    ds.Modality = "CT"
    ds.InstanceNumber = i
    
    # Sintetik 512x512 KT kesimi
    img_data = (np.random.rand(512, 512) * 1000).astype(np.int16)
    ds.Rows = 512
    ds.Columns = 512
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.RescaleIntercept = -1024
    ds.RescaleSlope = 1
    ds.WindowCenter = 40
    ds.WindowWidth = 400
    ds.PixelData = img_data.tobytes()
    
    datasets.append(ds)

print(f"[*] 3 ta test kesimi tayyor. PACS serverga (127.0.0.1:11112) yuborilmoqda...")
ae = AE(ae_title=b'CT01')
ae.add_requested_context(CTImageStorage)

assoc = ae.associate('127.0.0.1', 11112, ae_title=b'RADIANT')
if assoc.is_established:
    for idx, ds in enumerate(datasets, start=1):
        status = assoc.send_c_store(ds)
        print(f"  Kesim {idx}/3 yuborildi. Status:", status.Status)
    assoc.release()
    print("[*] Barcha kesimlar yuborildi. Endi PACS server 15 soniya kutadi va avtomatik Telegramga jo'natadi...")
else:
    print("[!] Ulanish amalga oshmadi!")
