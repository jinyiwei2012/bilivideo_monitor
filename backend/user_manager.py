"""用户管理模块 —— 注册、登录、API Key 管理"""

import hashlib
import secrets
import logging
import time
from typing import Optional, Dict, List

from core import db as central_db

logger = logging.getLogger(__name__)

HASH_ITERATIONS = 200000


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), HASH_ITERATIONS).hex()


def _generate_apikey() -> str:
    return secrets.token_hex(32)


def _ensure_tables():
    with central_db._get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL DEFAULT '',
                apikey TEXT UNIQUE NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS video_ownership (
                bvid TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (bvid, user_id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.commit()

    _ensure_salt_column()
    _ensure_user_id_column()


def _ensure_salt_column():
    try:
        with central_db._get_connection() as conn:
            cur = conn.execute("PRAGMA table_info(users)")
            cols = {r["name"] for r in cur.fetchall()}
            if "salt" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN salt TEXT NOT NULL DEFAULT ''")
                conn.execute("UPDATE users SET salt = '' WHERE salt IS NULL")
                conn.commit()
                logger.info("已为 users 表添加 salt 列")
    except Exception as e:
        logger.warning("添加 salt 列失败: %s", e)


def _ensure_user_id_column():
    try:
        with central_db._get_connection() as conn:
            cur = conn.execute("PRAGMA table_info(videos)")
            cols = {r["name"] for r in cur.fetchall()}
            if "user_id" not in cols:
                conn.execute("ALTER TABLE videos ADD COLUMN user_id INTEGER DEFAULT NULL")
                conn.commit()
                logger.info("已为 videos 表添加 user_id 列")
    except Exception as e:
        logger.warning("添加 user_id 列失败: %s", e)


def _init_admin_user():
    _ensure_tables()
    from config import load_config
    cfg = load_config()
    api_cfg = cfg.get("api", {})
    admin_key = api_cfg.get("default_admin_apikey", "")
    admin_pass = api_cfg.get("default_admin_password", "")

    with central_db._get_connection() as conn:
        existing = conn.execute("SELECT id, salt FROM users WHERE username = 'admin'").fetchone()
        if not existing:
            salt = secrets.token_hex(16)
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, apikey, is_admin, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                ("admin", _hash_password(admin_pass, salt), salt, admin_key, time.time()),
            )
            conn.commit()
            logger.info("已创建管理员账号")
        elif not existing["salt"]:
            salt = secrets.token_hex(16)
            conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE username = 'admin'",
                         (_hash_password(admin_pass, salt), salt))
            conn.commit()
            logger.info("已为管理员账号迁移 salt")


def register_user(username: str, password: str) -> Dict:
    _ensure_tables()
    username = username.strip().lower()
    if not username or len(username) < 2:
        raise ValueError("用户名至少 2 个字符")
    if not password or len(password) < 4:
        raise ValueError("密码至少 4 个字符")

    apikey = _generate_apikey()
    salt = secrets.token_hex(16)
    with central_db._get_connection() as conn:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise ValueError(f"用户名 '{username}' 已被注册")
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, apikey, is_admin, created_at) VALUES (?, ?, ?, ?, 0, ?)",
            (username, _hash_password(password, salt), salt, apikey, time.time()),
        )
        conn.commit()

    logger.info("用户注册成功: %s", username)
    return {"username": username, "apikey": apikey, "is_admin": False}


def login_user(username: str = None, password: str = None, apikey: str = None) -> Optional[Dict]:
    _ensure_tables()

    with central_db._get_connection() as conn:
        if apikey:
            row = conn.execute(
                "SELECT id, username, apikey, is_admin FROM users WHERE apikey = ?",
                (apikey,),
            ).fetchone()
            if row:
                return {"id": row[0], "username": row[1], "apikey": row[2], "is_admin": bool(row[3])}

        if username and password:
            username = username.strip().lower()
            row = conn.execute(
                "SELECT id, username, apikey, is_admin, salt, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if row and _hash_password(password, row["salt"]) == row["password_hash"]:
                return {"id": row[0], "username": row[1], "apikey": row[2], "is_admin": bool(row[3])}

    return None


def get_user_by_apikey(apikey: str) -> Optional[Dict]:
    with central_db._get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, apikey, is_admin FROM users WHERE apikey = ?",
            (apikey,),
        ).fetchone()
        if row:
            return {"id": row[0], "username": row[1], "apikey": row[2], "is_admin": bool(row[3])}
    return None


def regenerate_apikey(user_id: int) -> str:
    apikey = _generate_apikey()
    with central_db._get_connection() as conn:
        conn.execute("UPDATE users SET apikey = ? WHERE id = ?", (apikey, user_id))
        conn.commit()
    return apikey


def delete_user(user_id: int):
    with central_db._get_connection() as conn:
        owned = conn.execute("SELECT bvid FROM video_ownership WHERE user_id = ?", (user_id,)).fetchall()
        for row in owned:
            bvid = row[0]
            others = conn.execute(
                "SELECT COUNT(*) FROM video_ownership WHERE bvid = ? AND user_id != ?", (bvid, user_id)
            ).fetchone()[0]
            if others == 0:
                conn.execute("DELETE FROM videos WHERE bvid = ?", (bvid,))

        conn.execute("DELETE FROM video_ownership WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


def add_video_ownership(bvid: str, user_id: int):
    with central_db._get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO video_ownership (bvid, user_id) VALUES (?, ?)",
            (bvid, user_id),
        )
        conn.commit()


def remove_video_ownership(bvid: str, user_id: int):
    with central_db._get_connection() as conn:
        conn.execute("DELETE FROM video_ownership WHERE bvid = ? AND user_id = ?", (bvid, user_id))
        others = conn.execute("SELECT COUNT(*) FROM video_ownership WHERE bvid = ?", (bvid,)).fetchone()[0]
        if others == 0:
            conn.execute("DELETE FROM videos WHERE bvid = ?", (bvid,))
        conn.commit()


def get_user_video_ids(user_id: int) -> List[str]:
    with central_db._get_connection() as conn:
        rows = conn.execute("SELECT bvid FROM video_ownership WHERE user_id = ?", (user_id,)).fetchall()
        return [r[0] for r in rows]


_init_admin_user()
