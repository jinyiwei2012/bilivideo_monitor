"""
配置模块
包含系统配置和常量定义
"""

import os
import json
import logging
from copy import deepcopy
from typing import Dict, Any

from utils import PROJECT_ROOT  # 单点定义见 utils/__init__.py (兼容 PyInstaller frozen)

logger = logging.getLogger(__name__)

# 数据目录
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
COVER_DIR = os.path.join(DATA_DIR, "cover")
EXPORT_DIR = os.path.join(PROJECT_ROOT, "exports")

# 确保目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(COVER_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

# 数据库路径
DB_PATH = os.path.join(DATA_DIR, "bilibili_monitor.db")

# 配置文件路径
CONFIG_FILE = os.path.join(DATA_DIR, "settings.json")

# 默认配置
DEFAULT_CONFIG = {
    "onebot": {
        "enabled": False,
        "http_url": "http://127.0.0.1:5700",
        "ws_url": "ws://127.0.0.1:6700",
        "access_token": "",
        "private_qq": "",
        "group_qq": "",
    },
    "monitor": {
        "auto_start_monitor": True,
        "max_monitor_count": 100,
        "save_history": True,
        "history_days": 30,
    },
    "prediction": {
        "default_algorithm": "集成预测",
        "prediction_hours": 168,
        "min_confidence": 0.5,
        "auto_predict": True,
        "thresholds": [[100000, "10万"], [1000000, "100万"], [10000000, "1000万"]],
    },
    "notification": {
        "windows_notify": True,
        "sound_alert": True,
        "notify_on_threshold": True,
        "notify_on_error": False,
        "notify_on_start": False,
    },
    "ui": {"theme": "darkly", "auto_refresh": True, "refresh_interval": 30, "show_cover": True, "show_chart": True},
    "export": {"default_path": "", "auto_export": False, "export_format": "csv"},
    "ai": {"enabled": False, "api_key": "", "endpoint": "", "model": "gpt-4o-mini"},
}


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个字典，使深层嵌套的默认配置项也能自动生效"""
    result = {}
    for k in set(base) | set(override):
        if k in override and k in base:
            if isinstance(base[k], dict) and isinstance(override[k], dict):
                result[k] = _deep_merge(base[k], override[k])
            else:
                result[k] = override[k]
        elif k in override:
            result[k] = override[k]
        else:
            result[k] = base[k]
    return result


def load_config() -> Dict[str, Any]:
    """加载配置文件并合并默认值，自动解密敏感字段"""
    config = deepcopy(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config = _deep_merge(config, saved)
        except Exception as e:
            logger.warning("加载配置失败: %s", e)
    # 解密敏感字段（加密存储的 API Key / Token，解密失败保留原值做向后兼容）
    _decrypt_sensitive(config)
    return config


def _decrypt_sensitive(config: dict) -> None:
    """解密配置中的敏感字段（OneBot access_token、AI profiles api_key）"""
    try:
        from utils.crypto import decrypt_dict

        ob = config.get("onebot", {})
        if ob.get("access_token"):
            decrypt_dict(ob, "access_token")
        for p in config.get("ai", {}).get("profiles", []):
            if p.get("api_key"):
                decrypt_dict(p, "api_key")
    except ImportError:
        pass
    except Exception as e:
        logger.warning("解密敏感配置失败: %s", e)


def get_active_ai_profile() -> dict:
    """获取当前选中的 LLM 配置（支持多 profile）"""
    cfg = load_config().get("ai", {})
    profiles = cfg.get("profiles", [])
    selected = cfg.get("selected_profile", "")
    if profiles:
        for p in profiles:
            if p.get("name") == selected:
                return p
        return profiles[0]
    # 旧版单配置兼容
    return {
        "name": "默认配置",
        "api_key": cfg.get("api_key", ""),
        "endpoint": cfg.get("endpoint", "") or "https://api.openai.com/v1/chat/completions",
        "model": cfg.get("model", "gpt-4o-mini"),
    }


def save_config(config: Dict[str, Any]) -> bool:
    """保存配置到 JSON 文件"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.warning("保存配置失败: %s", e)
        return False


__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "COVER_DIR",
    "EXPORT_DIR",
    "DB_PATH",
    "CONFIG_FILE",
    "DEFAULT_CONFIG",
    "load_config",
    "save_config",
    "get_active_ai_profile",
]
