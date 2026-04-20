"""
配置模块
包含系统配置和常量定义
"""

import os
import json
from typing import Dict, Any

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

# 播放量阈值
VIEW_THRESHOLDS = [100000, 1000000, 10000000]  # 10万, 100万, 1000万
THRESHOLD_NAMES = {
    100000: "10万",
    1000000: "100万",
    10000000: "1000万"
}

# 默认配置
DEFAULT_CONFIG = {
    "onebot": {
        "enabled": False,
        "http_url": "http://127.0.0.1:5700",
        "ws_url": "ws://127.0.0.1:6700",
        "access_token": "",
        "private_qq": "",
        "group_qq": ""
    },
    "monitor": {
        "check_interval": 300,
        "auto_start_monitor": True,
        "max_monitor_count": 100,
        "save_history": True,
        "history_days": 30
    },
    "prediction": {
        "default_algorithm": "集成预测",
        "prediction_hours": 168,
        "min_confidence": 0.5,
        "auto_predict": True,
        "thresholds": [100000, 1000000, 10000000]
    },
    "notification": {
        "windows_notify": True,
        "sound_alert": True,
        "notify_on_threshold": True,
        "notify_on_error": False,
        "notify_on_start": False
    },
    "ui": {
        "theme": "darkly",
        "auto_refresh": True,
        "refresh_interval": 30,
        "show_cover": True,
        "show_chart": True
    },
    "export": {
        "default_path": "",
        "auto_export": False,
        "export_format": "csv"
    }
}


def load_config() -> Dict[str, Any]:
    """加载配置文件"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载配置失败: {e}")
    return DEFAULT_CONFIG.copy()


def save_config(config: Dict[str, Any]) -> bool:
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False


__all__ = [
    'PROJECT_ROOT',
    'DATA_DIR',
    'COVER_DIR',
    'EXPORT_DIR',
    'DB_PATH',
    'CONFIG_FILE',
    'VIEW_THRESHOLDS',
    'THRESHOLD_NAMES',
    'DEFAULT_CONFIG',
    'load_config',
    'save_config'
]
