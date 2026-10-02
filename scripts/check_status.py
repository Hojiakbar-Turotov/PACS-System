import sqlite3
import sys

sys.stdout.reconfigure(encoding='utf-8')

conn = sqlite3.connect(r'd:\PACS\data\pacs.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=== RECENT 15 LOGS ===")
for r in cur.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 15").fetchall():
    print(f"[{r['created_at']}] [{r['level']}] {r['message']} {r['details'] or ''}")

print("\n=== RECENT STATUS DISTRIBUTION ===")
for r in cur.execute("SELECT telegram_status, count(*) as cnt FROM studies GROUP BY telegram_status").fetchall():
    print(f"{r['telegram_status']}: {r['cnt']}")

print("\n=== LOCAL COPY STATUS DISTRIBUTION ===")
for r in cur.execute("SELECT local_copy_status, count(*) as cnt FROM studies GROUP BY local_copy_status").fetchall():
    print(f"{r['local_copy_status']}: {r['cnt']}")

archived_cnt = cur.execute("SELECT COUNT(*) FROM studies WHERE archive_path IS NOT NULL AND archive_path != ''").fetchone()[0]
total_cnt = cur.execute("SELECT COUNT(*) FROM studies").fetchone()[0]
print(f"\nTotal: {total_cnt}, Archived (ZIP ready): {archived_cnt}, Not archived: {total_cnt - archived_cnt}")
