"""
一次性数据同步脚本
将 core/data/ 的旧数据结构数据同步到 data/ 新目录

功能：
1. 遍历旧目录中的视频专属数据库（每个 BV 号一个 .db 文件）
2. 检查新目录中对应数据库的记录数
3. 如果旧库有更多记录，增量合并到新库
4. 如果新库不存在，直接复制整个数据库文件
5. 同步中央数据库（bilibili_monitor.db）

用于项目目录结构调整后的数据迁移，确保不丢失历史监控数据。
"""
import os
import shutil
import sqlite3
import sys

# 将项目根目录加入 sys.path，以便导入 config 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATA_DIR

# 旧数据目录（core/data/）
old_base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "data")
# 新数据目录（data/）
new_base = DATA_DIR

print("=== 同步每个视频的数据库 ===")
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

        # 如果旧库有更多记录，则增量合并
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
            print(f"  {item}: {new_cnt} -> {new_cnt2} 条记录")
            new_conn.close()
        else:
            print(f"  {item}: {new_cnt} 条记录 (已是最新)")
            new_conn.close()
    else:
        # 新库不存在：复制整个文件
        os.makedirs(new_dir, exist_ok=True)
        shutil.copy2(old_db, new_db)
        print(f"  {item}: 0 -> {old_cnt} 条记录 (已复制)")

    old_conn.close()

print()
print("=== 同步中央数据库 ===")
src = os.path.join(old_base, "bilibili_monitor.db")
dst = os.path.join(new_base, "bilibili_monitor.db")
try:
    shutil.copy2(src, dst)
    print(f"  中央数据库已复制: {dst}")
except Exception as e:
    print(f"  中央数据库复制失败: {e}")

print()
print("完成！请重启应用以使用同步后的数据。")
