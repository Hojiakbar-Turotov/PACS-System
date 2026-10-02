import os
import sys
from pathlib import Path

# D:\PACS papkasini Python path'ga qo'shish
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import uvicorn
from core.config import WEB_HOST, WEB_PORT

if __name__ == "__main__":
    print("=" * 60)
    print("   SABADARMON MSKT PACS & WORKLIST TIZIMI ISHGA TUSHMOQDA")
    print(f"   Veb-panel manzili : http://localhost:{WEB_PORT}")
    print(f"   Klinika tarmog'i  : http://192.168.10.100:{WEB_PORT}")
    print(f"   DICOM PACS porti  : 11112 [AE: RADIANT]")
    print("=" * 60)
    
    uvicorn.run("core.main:app", host=WEB_HOST, port=WEB_PORT, reload=False, log_level="info")
