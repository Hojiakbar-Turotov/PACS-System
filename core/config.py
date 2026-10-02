import os
import json
from pathlib import Path

# Asosiy papkalar - barchasi D:\PACS ga nisbatan
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
STORAGE_DIR = BASE_DIR / "storage"
ARCHIVES_DIR = BASE_DIR / "archives"
WEB_DIR = BASE_DIR / "web"
LOGS_DIR = BASE_DIR / "logs"
SETTINGS_FILE = DATA_DIR / "settings.json"

for p in [DATA_DIR, STORAGE_DIR, ARCHIVES_DIR, LOGS_DIR]:
    p.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "pacs_host": "0.0.0.0",
    "pacs_port": 11112,
    "pacs_aet": "RADIANT",
    "ct_host": "192.168.10.250",
    "ct_port": 4006,
    "ct_aet": "CT01",
    "web_host": "0.0.0.0",
    "web_port": 8000,
    "telegram_bot_token": "8901578611:AAFwH648xgPAfnw5Oh_ScBVuzVr94-JYkJI",
    "telegram_channel_id": "-1004295879936",
    "telegram_api_id": 12756254,
    "telegram_api_hash": "c77f78c1ac09bb77b02c8b800321",
    "telegram_string_session": "1ApWapzMBu1U5C0IdOChgztLd4gSOThZ2y2c8v7XCOs2p16X1x0SNSUO4XfpvhILtq1vzIvNcylWhxbvzc_ZZ5995ieEplDii-_a5moLRqFMA4BTT8GhWKS-soN2N0s9jpIJ4xPMeLc5vE391Pap82ZHZEjjsER4JKBgzsS4Hk0TD04ZlKDFG8oj7KzzVOywXaO06j6vihvlOuGFJ0wB7he6agQ2O3R_asfZIyhtJ5bbdYjArx2xGmbpIs24bTWKtJE7--JizGdXiINCL0VI_hJOwkZMPJmjO4gVrUKFidlAkM3ZW2CXYAUClGLqUt1OiT6SjxT_Bbr7OE1HQ4NR7CyG2MdFfBj4=",
    "radiant_exe": r"C:\App\RadiAntViewer\RadiAntViewer.exe",
    "study_inactivity_timeout": 15,
    "retention_days": 30,
    # Yangi avtomatlashtirish va parallel yuklash sozlamalari
    "auto_archive_enabled": True,
    "new_study_poll_interval": 60,      # Yangi bemorlarni tekshirish oralig'i (soniyalarda, default: 60s)
    "recon_stability_checks": 3,        # Rekonstruksiya barqarorligi uchun ketma-ket bir xil kadr soni chiqishi (3 marta)
    "deep_scan_interval": 10800,        # Barcha bemorlarni qayta tekshirish (chuqur skaner) oralig'i (3 soat = 10800s)
    "batch_concurrency": 2              # Bir vaqtda parallel yuklanadigan bemorlar soni (kompyuter qotmasligi uchun 2)
}

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                conf = DEFAULT_SETTINGS.copy()
                conf.update(saved)
                return conf
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()

def save_settings(new_conf: dict):
    current = load_settings()
    current.update(new_conf)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=4, ensure_ascii=False)
    _apply_globals(current)

def _apply_globals(conf: dict):
    global PACS_HOST, PACS_PORT, PACS_AET
    global CT_HOST, CT_PORT, CT_AET
    global WEB_HOST, WEB_PORT
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_STRING_SESSION
    global RADIANT_EXE, STUDY_INACTIVITY_TIMEOUT, RETENTION_DAYS
    global AUTO_ARCHIVE_ENABLED, NEW_STUDY_POLL_INTERVAL, RECON_STABILITY_CHECKS, DEEP_SCAN_INTERVAL, BATCH_CONCURRENCY
    
    PACS_HOST = conf.get("pacs_host", DEFAULT_SETTINGS["pacs_host"])
    PACS_PORT = int(conf.get("pacs_port", DEFAULT_SETTINGS["pacs_port"]))
    PACS_AET = conf.get("pacs_aet", DEFAULT_SETTINGS["pacs_aet"])
    
    CT_HOST = conf.get("ct_host", DEFAULT_SETTINGS["ct_host"])
    CT_PORT = int(conf.get("ct_port", DEFAULT_SETTINGS["ct_port"]))
    CT_AET = conf.get("ct_aet", DEFAULT_SETTINGS["ct_aet"])
    
    WEB_HOST = conf.get("web_host", DEFAULT_SETTINGS["web_host"])
    WEB_PORT = int(conf.get("web_port", DEFAULT_SETTINGS["web_port"]))
    
    TELEGRAM_BOT_TOKEN = conf.get("telegram_bot_token", DEFAULT_SETTINGS["telegram_bot_token"])
    TELEGRAM_CHANNEL_ID = conf.get("telegram_channel_id", DEFAULT_SETTINGS["telegram_channel_id"])
    TELEGRAM_API_ID = int(conf.get("telegram_api_id", DEFAULT_SETTINGS["telegram_api_id"]))
    TELEGRAM_API_HASH = conf.get("telegram_api_hash", DEFAULT_SETTINGS["telegram_api_hash"])
    TELEGRAM_STRING_SESSION = conf.get("telegram_string_session", DEFAULT_SETTINGS["telegram_string_session"])
    
    RADIANT_EXE = conf.get("radiant_exe", DEFAULT_SETTINGS["radiant_exe"])
    STUDY_INACTIVITY_TIMEOUT = int(conf.get("study_inactivity_timeout", DEFAULT_SETTINGS["study_inactivity_timeout"]))
    RETENTION_DAYS = int(conf.get("retention_days", DEFAULT_SETTINGS["retention_days"]))

    AUTO_ARCHIVE_ENABLED = bool(conf.get("auto_archive_enabled", DEFAULT_SETTINGS["auto_archive_enabled"]))
    NEW_STUDY_POLL_INTERVAL = int(conf.get("new_study_poll_interval", DEFAULT_SETTINGS["new_study_poll_interval"]))
    RECON_STABILITY_CHECKS = int(conf.get("recon_stability_checks", DEFAULT_SETTINGS["recon_stability_checks"]))
    DEEP_SCAN_INTERVAL = int(conf.get("deep_scan_interval", DEFAULT_SETTINGS["deep_scan_interval"]))
    BATCH_CONCURRENCY = int(conf.get("batch_concurrency", DEFAULT_SETTINGS["batch_concurrency"]))

# Dastlabki yuklash
_cfg = load_settings()
_apply_globals(_cfg)
