"""
配置模块
包含系统配置和常量定义

功能：
- 项目根目录、数据目录、导出目录等路径常量
- 数据库路径和配置文件路径
- 完整的默认配置字典（涵盖监控、预测、通知、UI、导出、AI、Web 等）
- 配置加载/保存/svg-merge 等工具函数
- 多 AI profile 支持

兼容 PyInstaller 打包后的路径解析（sys.frozen）。
"""

import os
import json
import logging
import sys
from typing import Dict, Any

logger = logging.getLogger(__name__)

# ── 路径常量 ──────────────────────────────────

# 项目根目录（兼容 PyInstaller 打包后的路径）
# 打包后 sys.executable 指向 exe 所在目录，开发时使用源文件路径
if getattr(sys, "frozen", False):
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据目录（存放数据库、封面、配置文件等）
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

# ── 默认配置 ──────────────────────────────────
# 所有可配置项的默认值，首次启动时自动生成

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
        "check_interval": 300,
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
    "web": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 8800,
        "auto_start": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """
    递归合并两个字典，使深层嵌套的默认配置项也能自动生效。
    
    当用户保存了旧版本的配置（缺少新字段）时，通过深度合并
    自动补全缺失的默认值，避免因配置结构不完整导致的 KeyError。
    
    Args:
        base: 基础字典（默认配置）
        override: 覆盖字典（用户保存的配置）
        
    Returns:
        dict: 合并后的字典
    """
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
    """
    加载配置文件并合并默认值。
    
    如果配置文件不存在，返回完整的默认配置。
    如果配置文件存在但缺少某些字段，自动用默认值补全。
    对 JSON 解析异常做容错处理，异常时返回默认配置。
    
    Returns:
        dict: 完整的配置字典
    """
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                config = _deep_merge(config, saved)
        except Exception as e:
            logger.warning("加载配置失败: %s", e)
    return config


def get_active_ai_profile() -> dict:
    """
    获取当前选中的 LLM 配置（支持多 profile）。
    
    优先从 profiles 列表中查找与 selected_profile 匹配的项；
    如果没有 profiles 配置，则回退到旧版单配置兼容模式。
    
    Returns:
        dict: 包含 name, api_key, endpoint, model 的配置字典
    """
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
    """
    保存配置到 JSON 文件。
    
    Args:
        config: 要保存的配置字典
        
    Returns:
        bool: 是否保存成功
    """
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
