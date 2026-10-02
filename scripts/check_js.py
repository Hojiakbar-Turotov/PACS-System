import re
from pathlib import Path

html = Path("d:/PACS/web/index.html").read_text(encoding="utf-8")
js = Path("d:/PACS/web/app.js").read_text(encoding="utf-8")

calls = set(re.findall(r'onclick="([a-zA-Z0-9_]+)\(', html))
calls.update(re.findall(r"onclick='([a-zA-Z0-9_]+)\(", html))

missing = []
for c in calls:
    if f"function {c}" in js or f"{c} = " in js:
        pass
    else:
        missing.append(c)

print(f"Total onclick functions checked: {len(calls)}")
if missing:
    print(f"MISSING: {missing}")
else:
    print("ALL HTML onclick handlers are defined in app.js!")
