"""
一次性的数据同步脚本
将 core/data/ 的旧数据同步到 data/
"""
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_DIR

old_base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "data")
new_base = DATA_DIR

print("=== Sync per-video DBs ===")
for item in sorted(os.listdir(old_base)):
    old_db = os.path.join(old_base, item, f"{item}.db")
    if not os.path.exists(old_db):
        continue
    try:
        old_conn = sqlite3.connect(old_db)
        old_cnt = old_conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
    except Exception:
        continue

    new_dir = os.path.join(new_base, item)
    new_db = os.path.join(new_dir, f"{item}.db")

    if os.path.exists(new_db):
        new_conn = sqlite3.connect(new_db)
        try:
            new_cnt = new_conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
        except Exception:
            new_cnt = 0

        if old_cnt > new_cnt:
            old_conn.row_factory = sqlite3.Row
            rows = old_conn.execute("SELECT * FROM monitor_records ORDER BY timestamp ASC").fetchall()
            for r in rows:
                d = dict(r)
                try:
                    new_conn.execute(
                        """INSERT OR IGNORE INTO monitor_records
                        (timestamp, view_count, like_count, coin_count, share_count,
                         favorite_count, danmaku_count, reply_count, viewers_app,
                         viewers_web, viewers_total, like_view_ratio)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            d["timestamp"],
                            d.get("view_count", 0),
                            d.get("like_count", 0),
                            d.get("coin_count", 0),
                            d.get("share_count", 0),
                            d.get("favorite_count", 0),
                            d.get("danmaku_count", 0),
                            d.get("reply_count", 0),
                            d.get("viewers_app", 0),
                            d.get("viewers_web", 0),
                            d.get("viewers_total", 0),
                            d.get("like_view_ratio", 0),
                        ),
                    )
                except Exception:
                    pass
            new_conn.commit()
            new_cnt2 = new_conn.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
            print(f"  {item}: {new_cnt} -> {new_cnt2} records")
            new_conn.close()
        else:
            print(f"  {item}: {new_cnt} records (up-to-date)")
            new_conn.close()
    else:
        os.makedirs(new_dir, exist_ok=True)
        shutil.copy2(old_db, new_db)
        print(f"  {item}: 0 -> {old_cnt} records (copied)")

    old_conn.close()

print()
print("=== Sync central DB ===")
src = os.path.join(old_base, "bilibili_monitor.db")
dst = os.path.join(new_base, "bilibili_monitor.db")
try:
    shutil.copy2(src, dst)
    print(f"  central DB copied: {dst}")
except Exception as e:
    print(f"  central DB copy failed: {e}")

print()
print("Done! Restart the app to use the synced data.")
