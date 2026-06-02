"""
用户管理模块 —— 注册、登录、API Key 管理

提供完整的多用户账户体系：
- PBKDF2-SHA256 密码哈希（20 万次迭代 + 随机 salt）
- 基于 API Key 的无状态认证
- 视频所有权（ownership）多对多关联
- 管理员账户自动初始化

安全特性：
- 密码从不以明文存储
- API Key 使用 secrets.token_hex() 生成（加密安全的随机数）
- salt 字段支持向后兼容迁移
"""

import hashlib
import secrets
import logging
import time
from typing import Optional, Dict, List

from core import db as central_db

logger = logging.getLogger(__name__)

# 密码哈希迭代次数：20 万次 PBKDF2 迭代
HASH_ITERATIONS = 200000


def _hash_password(password: str, salt: str) -> str:
    """
    使用 PBKDF2-SHA256 对密码进行安全哈希。
    
    Args:
        password: 明文密码
        salt: 密码盐值（16 字节十六进制字符串）
        
    Returns:
        str: 十六进制编码的哈希值
    """
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), HASH_ITERATIONS).hex()


def _generate_apikey() -> str:
    """
    生成加密安全的随机 API Key（64 字符十六进制）。
    
    Returns:
        str: 32 字节的十六进制 API Key
    """
    return secrets.token_hex(32)


def _ensure_tables():
    """
    确保用户相关的数据库表存在。
    
    创建/验证的表：
    - users: 用户账户表（用户名、密码哈希、salt、API Key、管理员标记）
    - video_ownership: 视频所有权关联表（多对多关系）
    """
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
    """
    向后兼容：为旧版 users 表（缺少 salt 列）自动添加 salt 列。
    
    旧版本使用固定 salt，新版本每个用户使用独立随机 salt。
    """
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
    """
    向后兼容：为 videos 表添加 user_id 列（关联到 users 表）。
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
    
    从配置文件读取默认管理员 API Key 和密码。
    如果管理员账户不存在则创建，如果缺少 salt 则迁移。
    """
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
    """
    用户登录，支持两种方式：
    1. API Key 直接认证（优先级最高，无需密码）
    2. 用户名 + 密码认证
    
    Args:
        username: 用户名（可选）
        password: 密码（可选）
        apikey: API Key（可选，优先使用）
        
    Returns:
        dict: 用户信息 {"id", "username", "apikey", "is_admin"}，失败返回 None
    """
    _ensure_tables()

    with central_db._get_connection() as conn:
        if apikey:
            # API Key 认证：直接查询匹配
            row = conn.execute(
                "SELECT id, username, apikey, is_admin FROM users WHERE apikey = ?",
                (apikey,),
            ).fetchone()
            if row:
                return {"id": row[0], "username": row[1], "apikey": row[2], "is_admin": bool(row[3])}

        if username and password:
            # 用户名+密码认证：验证哈希后的密码值
            username = username.strip().lower()
            row = conn.execute(
                "SELECT id, username, apikey, is_admin, salt, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if row and _hash_password(password, row["salt"]) == row["password_hash"]:
                return {"id": row[0], "username": row[1], "apikey": row[2], "is_admin": bool(row[3])}

    return None


def get_user_by_apikey(apikey: str) -> Optional[Dict]:
    """
    通过 API Key 查找用户（用于请求认证中间件）。
    
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
    重新生成 API Key（旧 Key 立即失效），用于密钥轮换。
    
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
    
    逻辑：
    - 如果某视频仅该用户拥有，则一并删除视频数据
    - 如果某视频还有其他用户拥有，则仅移除该用户的所有权
    - 最后删除用户记录
    
    Args:
        user_id: 要删除的用户 ID
    """
    with central_db._get_connection() as conn:
        owned = conn.execute("SELECT bvid FROM video_ownership WHERE user_id = ?", (user_id,)).fetchall()
        for row in owned:
            bvid = row[0]
            others = conn.execute(
                "SELECT COUNT(*) FROM video_ownership WHERE bvid = ? AND user_id != ?", (bvid, user_id)
            ).fetchone()[0]
            if others == 0:
                # 该视频没有其他用户拥有，删除视频
                conn.execute("DELETE FROM videos WHERE bvid = ?", (bvid,))

        conn.execute("DELETE FROM video_ownership WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


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
        conn.commit()


def remove_video_ownership(bvid: str, user_id: int):
    """
    撤销用户对视频的所有权。
    
    如果该视频不再有任何用户拥有，则从数据库中删除。
    
    Args:
        bvid: 视频 BV 号
        user_id: 用户 ID
    """
    with central_db._get_connection() as conn:
        conn.execute("DELETE FROM video_ownership WHERE bvid = ? AND user_id = ?", (bvid, user_id))
        others = conn.execute("SELECT COUNT(*) FROM video_ownership WHERE bvid = ?", (bvid,)).fetchone()[0]
        if others == 0:
            # 没有其他人拥有此视频，删除视频记录
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


# 模块导入时自动初始化管理员账户
_init_admin_user()
