"""
用户管理模块 —— 注册、登录、API Key 管理

Web 模块内置的用户管理系统，提供：
- SHA-256 + 固定盐值密码哈希
- API Key 生成与认证
- 视频所有权（ownership）多对多关联

注意：此模块与 backend/user_manager.py 功能类似，
但使用固定盐值而非 PBKDF2 + 随机盐（相对简化版本）。
backend/user_manager.py 是主模块，web/user_manager.py 为兼容保留。
"""

import hashlib
import secrets
import logging
import sqlite3
import time
from typing import Optional, Dict, List

from core import db as central_db

logger = logging.getLogger(__name__)


def _hash_password(password: str) -> str:
    """
    对密码进行 SHA-256 哈希（使用固定盐值）。
    
    注意：生产环境建议使用 backend/user_manager.py 中的 PBKDF2 方案。
    
    Args:
        password: 明文密码
        
    Returns:
        str: 十六进制哈希值
    """
    salt = "bili_monitor_salt_2026"
    return hashlib.sha256((password + salt).encode()).hexdigest()


def _generate_apikey() -> str:
    """
    生成加密安全的随机 API Key（64 字符十六进制）。
    
    Returns:
        str: 32 字节的十六进制 API Key
    """
    return secrets.token_hex(32)


def _ensure_tables():
    """
    确保 users 和 video_ownership 表存在。
    
    创建的表：
    - users: 用户账户（用户名、密码哈希、API Key、管理员标记、创建时间）
    - video_ownership: 视频所有权关联（bvid + user_id 联合主键）
    """
    with central_db._get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
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

    _ensure_user_id_column()


def _ensure_user_id_column():
    """
    向后兼容：为 videos 表添加 user_id 列（如不存在）。
    """
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
    """
    自动初始化管理员账户。
    
    从配置文件读取管理员 API Key 和密码，如果 admin 用户不存在则创建。
    """
    _ensure_tables()
    from config import load_config
    cfg = load_config()
    api_cfg = cfg.get("api", {})
    admin_key = api_cfg.get("default_admin_apikey", "")
    admin_pass = api_cfg.get("default_admin_password", "")

    with central_db._get_connection() as conn:
        existing = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO users (username, password_hash, apikey, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
                ("admin", _hash_password(admin_pass), admin_key, time.time()),
            )
            conn.commit()
            logger.info("已创建管理员账号")


# ── 用户操作 ──────────────────────────────────


def register_user(username: str, password: str) -> Dict:
    """
    注册新用户，生成随机 API Key。
    
    Args:
        username: 用户名（至少 2 个字符，不区分大小写）
        password: 密码（至少 4 个字符）
        
    Returns:
        dict: {"username": str, "apikey": str, "is_admin": False}
        
    Raises:
        ValueError: 用户名已存在或格式不符合要求
    """
    _ensure_tables()
    username = username.strip().lower()
    if not username or len(username) < 2:
        raise ValueError("用户名至少 2 个字符")
    if not password or len(password) < 4:
        raise ValueError("密码至少 4 个字符")

    apikey = _generate_apikey()
    with central_db._get_connection() as conn:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise ValueError(f"用户名 '{username}' 已被注册")
        conn.execute(
            "INSERT INTO users (username, password_hash, apikey, is_admin, created_at) VALUES (?, ?, ?, 0, ?)",
            (username, _hash_password(password), apikey, time.time()),
        )
        conn.commit()

    logger.info("用户注册成功: %s", username)
    return {"username": username, "apikey": apikey, "is_admin": False}


def login_user(username: str = None, password: str = None, apikey: str = None) -> Optional[Dict]:
    """
    用户登录，支持 API Key 或用户名+密码两种方式。
    
    优先级：API Key > 用户名+密码。
    
    Args:
        username: 用户名（可选）
        password: 密码（可选）
        apikey: API Key（可选，优先使用）
        
    Returns:
        dict: {"id", "username", "apikey", "is_admin"}，失败返回 None
    """
    _ensure_tables()

    with central_db._get_connection() as conn:
        if apikey:
            # 优先通过 API Key 直接认证
            row = conn.execute(
                "SELECT id, username, apikey, is_admin FROM users WHERE apikey = ?",
                (apikey,),
            ).fetchone()
            if row:
                return {"id": row[0], "username": row[1], "apikey": row[2], "is_admin": bool(row[3])}

        if username and password:
            # 用户名+密码认证
            username = username.strip().lower()
            row = conn.execute(
                "SELECT id, username, apikey, is_admin FROM users WHERE username = ? AND password_hash = ?",
                (username, _hash_password(password)),
            ).fetchone()
            if row:
                return {"id": row[0], "username": row[1], "apikey": row[2], "is_admin": bool(row[3])}

    return None


def get_user_by_apikey(apikey: str) -> Optional[Dict]:
    """
    通过 API Key 查找用户信息（无密码验证）。
    
    Args:
        apikey: API Key 字符串
        
    Returns:
        dict: 用户信息，不存在返回 None
    """
    with central_db._get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, apikey, is_admin FROM users WHERE apikey = ?",
            (apikey,),
        ).fetchone()
        if row:
            return {"id": row[0], "username": row[1], "apikey": row[2], "is_admin": bool(row[3])}
    return None


def regenerate_apikey(user_id: int) -> str:
    """
    重新生成用户的 API Key（旧 Key 立即失效）。
    
    Args:
        user_id: 用户 ID
        
    Returns:
        str: 新生成的 API Key
    """
    apikey = _generate_apikey()
    with central_db._get_connection() as conn:
        conn.execute("UPDATE users SET apikey = ? WHERE id = ?", (apikey, user_id))
        conn.commit()
    return apikey


def delete_user(user_id: int):
    """
    删除用户及其所有关联数据。
    
    删除逻辑：仅删除该用户独有视频的数据；
    如果某视频还有其他用户拥有，则仅移除该用户的所有权。
    
    Args:
        user_id: 要删除的用户 ID
    """
    with central_db._get_connection() as conn:
        owned = conn.execute("SELECT bvid FROM video_ownership WHERE user_id = ?", (user_id,)).fetchall()
        for row in owned:
            bvid = row[0]
            others = conn.execute("SELECT COUNT(*) FROM video_ownership WHERE bvid = ? AND user_id != ?", (bvid, user_id)).fetchone()[0]
            if others == 0:
                # 没有其他用户拥有此视频 → 删除视频数据
                conn.execute("DELETE FROM videos WHERE bvid = ? AND user_id = ?", (bvid, user_id))

        conn.execute("DELETE FROM video_ownership WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


# ── 视频所有权 ────────────────────────────────
# 管理用户与视频的多对多关联关系


def add_video_ownership(bvid: str, user_id: int):
    """
    建立用户与视频的所有权关系（INSERT OR IGNORE 防重复）。
    
    Args:
        bvid: 视频 BV 号
        user_id: 用户 ID
    """
    with central_db._get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO video_ownership (bvid, user_id) VALUES (?, ?)",
            (bvid, user_id),
        )
        conn.execute("UPDATE videos SET user_id = ? WHERE bvid = ?", (user_id, bvid))
        conn.commit()


def remove_video_ownership(bvid: str, user_id: int):
    """
    撤销用户对视频的所有权。
    
    如果撤销后该视频没有其他用户，则从数据库中彻底删除视频记录。
    
    Args:
        bvid: 视频 BV 号
        user_id: 用户 ID
    """
    with central_db._get_connection() as conn:
        conn.execute("DELETE FROM video_ownership WHERE bvid = ? AND user_id = ?", (bvid, user_id))
        others = conn.execute("SELECT COUNT(*) FROM video_ownership WHERE bvid = ?", (bvid,)).fetchone()[0]
        if others == 0:
            # 没有其他人拥有此视频 → 彻底删除
            conn.execute("DELETE FROM videos WHERE bvid = ?", (bvid,))
        conn.commit()


def get_user_video_ids(user_id: int) -> List[str]:
    """
    获取指定用户拥有的所有视频 BV 号列表。
    
    Args:
        user_id: 用户 ID
        
    Returns:
        list[str]: BV 号列表
    """
    with central_db._get_connection() as conn:
        rows = conn.execute("SELECT bvid FROM video_ownership WHERE user_id = ?", (user_id,)).fetchall()
        return [r[0] for r in rows]


# ── 初始化 ────────────────────────────────────
# 模块导入时自动初始化管理员账户

_init_admin_user()
