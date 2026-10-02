import os
import zipfile
from pathlib import Path

BASE_DIR = Path("D:/PACS")
OUTPUT_ZIP = BASE_DIR / "PACS_System_Portable.zip"

INCLUDE_EXTS = {".py", ".html", ".css", ".js", ".bat", ".vbs", ".cs", ".exe", ".ico", ".png", ".jpg", ".txt", ".me", ".json", ".sql", ".gitignore"}

EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    "archives",
    "storage",
    "logs",
    "Orthanc Server",
    "orthanc",
    ".pytest_cache",
    ".vscode",
    ".system_generated"
}

def should_include(rel_path: Path) -> bool:
    parts = rel_path.parts
    for exc in EXCLUDE_DIRS:
        if exc in parts:
            return False
            
    # pacs.db bazasini chetlab o'tish (boshqa kompyuterda o'zi yangi toza db ochadi)
    if "pacs.db" in rel_path.name:
        return False
    if rel_path.name == "PACS_System_Portable.zip":
        return False
        
    if rel_path.suffix.lower() in INCLUDE_EXTS or rel_path.name in {".gitignore", "requirements.txt"}:
        return True
    return False

def pack():
    print(f"[*] Packaging {OUTPUT_ZIP}...")
    count = 0
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(BASE_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(BASE_DIR)
                if should_include(rel_path):
                    zf.write(full_path, arcname=str(rel_path))
                    count += 1
    size_kb = round(OUTPUT_ZIP.stat().st_size / 1024, 1)
    print(f"[OK] Packed {count} files -> {OUTPUT_ZIP} ({size_kb} KB)")

if __name__ == "__main__":
    pack()
