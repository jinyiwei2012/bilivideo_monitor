"""
通知模块 - 支持Windows原生通知和QQ Bot推送
"""
import json
import logging
import requests
import websocket
from typing import Optional, Dict, Any
from datetime import datetime


logger = logging.getLogger(__name__)


class NotificationManager:
    """通知管理器"""
    
    def __init__(self):
        self.onebot_http = "http://127.0.0.1:5700"
        self.onebot_ws = "ws://127.0.0.1:6700"
        self.token = ""
        self.enabled = True
        self.qq_private = ""
        self.qq_group = ""
    
    def configure(self, config: Dict[str, Any]):
        """配置通知参数"""
        self.onebot_http = config.get('onebot_http', self.onebot_http)
        self.onebot_ws = config.get('onebot_ws', self.onebot_ws)
        self.token = config.get('token', '')
        self.enabled = config.get('enabled', True)
        self.qq_private = config.get('qq_private', '')
        self.qq_group = config.get('qq_group', '')
    
    def send_windows_notification(self, title: str, message: str) -> bool:
        """发送Windows原生通知"""
        try:
            from plyer import notification
            notification.notify(
                title=title,
                message=message,
                timeout=10
            )
            return True
        except Exception as e:
            logger.error(f"Windows通知发送失败: {type(e).__name__}")
            return False
    
    def send_qq_private(self, message: str) -> bool:
        """发送QQ私聊消息"""
        if not self.qq_private or not self.enabled:
            return False
        
        # 安全警告：Token通过明文HTTP传输
        if self.token and self.onebot_http.startswith('http://'):
            logger.warning(
                "OneBot token通过明文HTTP传输，存在中间人攻击风险，"
                "建议将onebot_http配置为HTTPS/WSS地址"
            )
        
        try:
            url = f"{self.onebot_http}/send_private_msg"
            headers = {}
            if self.token:
                headers['Authorization'] = f"Bearer {self.token}"
            
            data = {
                'user_id': self.qq_private,
                'message': message
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"QQ私聊发送失败: {type(e).__name__}")
            return False
    
    def send_qq_group(self, message: str) -> bool:
        """发送QQ群消息"""
        if not self.qq_group or not self.enabled:
            return False
        
        try:
            url = f"{self.onebot_http}/send_group_msg"
            headers = {}
            if self.token:
                headers['Authorization'] = f"Bearer {self.token}"
            
            data = {
                'group_id': self.qq_group,
                'message': message
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"QQ群消息发送失败: {type(e).__name__}")
            return False
    
    def send_threshold_notification(self, bvid: str, title: str, threshold: int, current_views: int):
        """发送阈值突破通知"""
        message = f"视频《{title}》播放量突破{threshold/10000:.0f}万！\n当前播放量: {current_views}\nBV号: {bvid}"
        
        # Windows通知
        self.send_windows_notification("播放量突破提醒", message)
        
        # QQ通知
        qq_msg = f"🎉 播放量突破提醒\n{message}"
        self.send_qq_private(qq_msg)
        self.send_qq_group(qq_msg)


# 全局通知管理器实例
notification_manager = NotificationManager()
