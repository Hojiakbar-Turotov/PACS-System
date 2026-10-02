import os
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

# Server loglarini data/logs/server.log ga yo'naltirish
log_dir = CURRENT_DIR / "data" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
try:
    log_file = open(log_dir / "server.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
except Exception:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

import uvicorn
from core.config import WEB_HOST, WEB_PORT

if __name__ == "__main__":
    uvicorn.run("core.main:app", host=WEB_HOST, port=WEB_PORT, reload=False, log_level="info")
