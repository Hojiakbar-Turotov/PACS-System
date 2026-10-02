import pydicom
from pydicom.dataset import Dataset
from pynetdicom import AE
from pynetdicom.sop_class import ModalityWorklistInformationFind

ae = AE(ae_title=b'CT01')
ae.add_requested_context(ModalityWorklistInformationFind)

assoc = ae.associate('127.0.0.1', 11112, ae_title=b'RADIANT')
if assoc.is_established:
    print('Accepted contexts:', [c.abstract_syntax for c in assoc.accepted_contexts])
    
    query_ds = Dataset()
    query_ds.PatientName = ''
    query_ds.PatientID = ''
    
    responses = assoc.send_c_find(query_ds, ModalityWorklistInformationFind)
    count = 0
    for status, identifier in responses:
        print("Response status:", status)
        if status and status.Status in (0xFF00, 0xFF01) and identifier:
            count += 1
            print("Found:", identifier.PatientName, identifier.PatientID)
    print("Total found:", count)
    assoc.release()
else:
    print('Failed to associate!')
