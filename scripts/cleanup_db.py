"""
数据库清理 — 删重复预测 + 删旧性能记录 + VACUUM（保留综合预测）

只清理:
  - predictions 表: 每算法每阈值只保留最新 1 条
  - algorithm_performance 表: 每算法只保留最新 1 条
保留:
  - monitor_records（监控历史）
  - prediction_ensemble（综合预测）
  - algorithm_coherence（共识度）
  - weekly_scores / yearly_scores
  - 所有文件不删除

用法: python scripts/cleanup_db.py [--dry-run]
"""

import sqlite3, os, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CORE_DATA_DIR = PROJECT_ROOT / "core" / "data"


def get_size_mb(path: Path) -> float:
    return os.path.getsize(path) / (1024 * 1024)


def clean_one_db(db_path: Path, dry: bool):
    before = get_size_mb(db_path)
    if before < 1:
        return 0, 0, 0
    if dry:
        try:
            c = sqlite3.connect(str(db_path))
            np = c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
            na = c.execute("SELECT COUNT(*) FROM algorithm_performance").fetchone()[0]
            nm = c.execute("SELECT COUNT(*) FROM monitor_records").fetchone()[0]
            c.close()
            print(f"  [DRY] {db_path.name} ({before:.0f}MB, pred:{np} perf:{na} mon:{nm})")
        except Exception:
            print(f"  [DRY] {db_path.name} ({before:.0f}MB)")
        return 0, 0, 0

    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")

        # 1. predictions: 每 (algorithm, target_threshold) 只保留 MAX(id)
        del_pred = 0
        try:
            del_pred = conn.execute("""
                DELETE FROM predictions WHERE id NOT IN (
                    SELECT MAX(id) FROM predictions GROUP BY algorithm, target_threshold
                )
            """).rowcount
        except sqlite3.OperationalError:
            pass

        # 2. algorithm_performance: 每 algorithm 只保留 MAX(id)（表可能不存在）
        del_perf = 0
        try:
            del_perf = conn.execute("""
                DELETE FROM algorithm_performance WHERE id NOT IN (
                    SELECT MAX(id) FROM algorithm_performance GROUP BY algorithm
                )
            """).rowcount
        except sqlite3.OperationalError:
            pass

        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
        conn.close()

        after = get_size_mb(db_path)
        saved = before - after
        print(f"  {db_path.name}: {before:.0f}→{after:.0f}MB (pred:{del_pred} perf:{del_perf} 省{saved:.0f}MB)")
        return saved, del_pred, del_perf
    except Exception as e:
        print(f"  {db_path.name}: 失败 ({e})")
        return 0, 0, 0


def main():
    dry = "--dry-run" in sys.argv
    print("=" * 55)
    print("DB 清理 — 删重复预测+性能记录, VACUUM")
    print("  保留: monitor_records | prediction_ensemble | coherence")
    print("=" * 55)

    total_saved = total_pred = total_perf = 0
    dirs = [DATA_DIR]
    if CORE_DATA_DIR.exists():
        dirs.append(CORE_DATA_DIR)

    for d in dirs:
        print(f"\n[{d.name}]")
        for p in sorted(d.rglob("*.db"), key=lambda x: -os.path.getsize(x)):
            s, pr, pf = clean_one_db(p, dry)
            total_saved += s; total_pred += pr; total_perf += pf

    print(f"\n{'='*55}")
    print(f"总计: pred {total_pred}条 + perf {total_perf}条, 省 {total_saved:.0f}MB")
    rem = sum(os.path.getsize(str(f)) for d in dirs for f in d.rglob("*.db") if f.is_file()) / 1024 / 1024
    print(f"剩余 DB: {rem:.0f} MB")


if __name__ == "__main__":
    main()
