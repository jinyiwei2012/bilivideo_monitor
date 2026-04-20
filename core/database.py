"""
数据库模块 - 增强版
支持观看人数、封面保存、播赞比、预测记录
每个视频独立数据库 + 总数据库同步
"""
import sqlite3
import os
import json
import requests
import shutil
from datetime import datetime
from typing import List, Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class VideoInfo:
    """视频信息"""
    bvid: str
    title: str
    view_count: int = 0
    like_count: int = 0
    coin_count: int = 0
    share_count: int = 0
    favorite_count: int = 0
    danmaku_count: int = 0
    reply_count: int = 0
    viewers_app: int = 0
    viewers_web: int = 0
    viewers_total: int = 0
    cover_path: str = ""
    like_view_ratio: float = 0.0
    owner_name: str = ""
    owner_id: int = 0
    pubdate: str = ""
    duration: int = 0
    pic: str = ""


@dataclass
class MonitorRecord:
    """监控记录"""
    bvid: str
    timestamp: str
    view_count: int
    like_count: int
    coin_count: int
    share_count: int
    favorite_count: int
    danmaku_count: int
    reply_count: int
    viewers_app: int = 0
    viewers_web: int = 0
    viewers_total: int = 0
    like_view_ratio: float = 0.0


@dataclass
class PredictionRecord:
    """预测记录"""
    bvid: str
    algorithm: str
    algorithm_id: str
    target_threshold: int
    predicted_seconds: int
    predicted_time: str
    confidence: float
    current_views: int
    is_reached: bool = False
    actual_time: str = ""
    error_rate: float = 0.0


class VideoDatabase:
    """单个视频的独立数据库"""
    
    def __init__(self, bvid: str, base_dir: str = None):
        self.bvid = bvid
        if base_dir is None:
            base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        
        # 创建以BV号命名的文件夹
        self.video_dir = os.path.join(base_dir, bvid)
        os.makedirs(self.video_dir, exist_ok=True)
        
        # 数据库文件路径：/data/BV号/BV号.db
        self.db_path = os.path.join(self.video_dir, f"{bvid}.db")
        self._init_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        """初始化数据库"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 视频信息表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS video_info (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    view_count INTEGER DEFAULT 0,
                    like_count INTEGER DEFAULT 0,
                    coin_count INTEGER DEFAULT 0,
                    share_count INTEGER DEFAULT 0,
                    favorite_count INTEGER DEFAULT 0,
                    danmaku_count INTEGER DEFAULT 0,
                    reply_count INTEGER DEFAULT 0,
                    viewers_app INTEGER DEFAULT 0,
                    viewers_web INTEGER DEFAULT 0,
                    viewers_total INTEGER DEFAULT 0,
                    cover_path TEXT,
                    like_view_ratio REAL DEFAULT 0,
                    owner_name TEXT,
                    owner_id INTEGER,
                    pubdate TEXT,
                    duration INTEGER,
                    pic TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 监控记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS monitor_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    view_count INTEGER,
                    like_count INTEGER,
                    coin_count INTEGER,
                    share_count INTEGER,
                    favorite_count INTEGER,
                    danmaku_count INTEGER,
                    reply_count INTEGER,
                    viewers_app INTEGER DEFAULT 0,
                    viewers_web INTEGER DEFAULT 0,
                    viewers_total INTEGER DEFAULT 0,
                    like_view_ratio REAL DEFAULT 0
                )
            ''')
            
            # 预测记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    algorithm TEXT,
                    algorithm_id TEXT,
                    target_threshold INTEGER,
                    predicted_seconds INTEGER,
                    predicted_time TIMESTAMP,
                    confidence REAL,
                    current_views INTEGER,
                    is_reached BOOLEAN DEFAULT 0,
                    actual_time TIMESTAMP,
                    error_rate REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_monitor_timestamp ON monitor_records(timestamp)')
            
            # 周刊分数记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS weekly_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_score REAL,
                    view_score REAL,
                    interaction_score REAL,
                    favorite_score REAL,
                    coin_score REAL,
                    like_score REAL,
                    correction_a REAL,
                    correction_b REAL,
                    correction_c REAL,
                    correction_d REAL,
                    base_view_score REAL
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_weekly_timestamp ON weekly_scores(timestamp)')
            
            # 年刊分数记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS yearly_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_score REAL,
                    view_score REAL,
                    interaction_score REAL,
                    favorite_score REAL,
                    coin_score REAL,
                    like_score REAL,
                    correction_a REAL,
                    correction_b REAL,
                    correction_c REAL
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_yearly_timestamp ON yearly_scores(timestamp)')
            
            conn.commit()
    
    def save_video_info(self, video_info: Dict):
        """保存视频信息"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO video_info 
                    (id, title, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, cover_path, like_view_ratio,
                     owner_name, owner_id, pubdate, duration, pic, updated_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    video_info.get('title', ''),
                    video_info.get('view_count', 0),
                    video_info.get('like_count', 0),
                    video_info.get('coin_count', 0),
                    video_info.get('share_count', 0),
                    video_info.get('favorite_count', 0),
                    video_info.get('danmaku_count', 0),
                    video_info.get('reply_count', 0),
                    video_info.get('viewers_app', 0),
                    video_info.get('viewers_web', 0),
                    video_info.get('viewers_total', 0),
                    video_info.get('cover_path', ''),
                    video_info.get('like_view_ratio', 0),
                    video_info.get('owner_name', ''),
                    video_info.get('owner_id', 0),
                    video_info.get('pubdate', ''),
                    video_info.get('duration', 0),
                    video_info.get('pic', ''),
                    datetime.now()
                ))
                conn.commit()
        except Exception as e:
            print(f"保存视频信息失败: {e}")
    
    def add_monitor_record(self, record: MonitorRecord) -> bool:
        """添加监控记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO monitor_records 
                    (timestamp, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, like_view_ratio)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record.timestamp, record.view_count, record.like_count,
                    record.coin_count, record.share_count, record.favorite_count,
                    record.danmaku_count, record.reply_count, record.viewers_app,
                    record.viewers_web, record.viewers_total, record.like_view_ratio
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"添加监控记录失败: {e}")
            return False
    
    def get_all_records(self) -> List[Dict]:
        """获取所有监控记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM monitor_records ORDER BY timestamp ASC')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"获取记录失败: {e}")
            return []
    
    def get_video_info(self) -> Optional[Dict]:
        """获取视频信息"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM video_info WHERE id = 1')
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            return None
    
    def add_prediction(self, prediction: PredictionRecord) -> bool:
        """添加预测记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO predictions 
                    (algorithm, algorithm_id, target_threshold, predicted_seconds,
                     predicted_time, confidence, current_views)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    prediction.algorithm, prediction.algorithm_id,
                    prediction.target_threshold, prediction.predicted_seconds,
                    prediction.predicted_time, prediction.confidence,
                    prediction.current_views
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"添加预测记录失败: {e}")
            return False

    def add_weekly_score(self, timestamp: str, score_data: dict) -> bool:
        """添加周刊分数记录
        
        Args:
            timestamp: 时间戳字符串
            score_data: 包含分数数据的字典，键名与 weekly_scores 表字段对应
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO weekly_scores 
                    (timestamp, total_score, view_score, interaction_score,
                     favorite_score, coin_score, like_score,
                     correction_a, correction_b, correction_c, correction_d,
                     base_view_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    timestamp,
                    score_data.get('total_score', 0),
                    score_data.get('view_score', 0),
                    score_data.get('interaction_score', 0),
                    score_data.get('favorite_score', 0),
                    score_data.get('coin_score', 0),
                    score_data.get('like_score', 0),
                    score_data.get('correction_a', 0),
                    score_data.get('correction_b', 0),
                    score_data.get('correction_c', 0),
                    score_data.get('correction_d', 0),
                    score_data.get('base_view_score', 0),
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"添加周刊分数记录失败: {e}")
            return False

    def get_weekly_scores(self, limit: int = 0) -> list:
        """获取周刊分数历史记录
        
        Args:
            limit: 限制返回条数，0 表示不限制
            
        Returns:
            分数记录列表，按时间升序
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit and limit > 0:
                    cursor.execute(
                        'SELECT * FROM weekly_scores ORDER BY timestamp ASC LIMIT ?',
                        (limit,))
                else:
                    cursor.execute(
                        'SELECT * FROM weekly_scores ORDER BY timestamp ASC')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"获取周刊分数记录失败: {e}")
            return []

    def get_latest_weekly_score(self) -> Optional[Dict]:
        """获取最新一条周刊分数记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT * FROM weekly_scores ORDER BY timestamp DESC LIMIT 1')
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception:
            return None

    def add_yearly_score(self, timestamp: str, score_data: dict) -> bool:
        """添加年刊分数记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO yearly_scores
                    (timestamp, total_score, view_score, interaction_score,
                     favorite_score, coin_score, like_score,
                     correction_a, correction_b, correction_c)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    timestamp,
                    score_data.get('total_score', 0),
                    score_data.get('view_score', 0),
                    score_data.get('interaction_score', 0),
                    score_data.get('favorite_score', 0),
                    score_data.get('coin_score', 0),
                    score_data.get('like_score', 0),
                    score_data.get('correction_a', 0),
                    score_data.get('correction_b', 0),
                    score_data.get('correction_c', 0),
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"添加年刊分数记录失败: {e}")
            return False

    def get_yearly_scores(self, limit: int = 0) -> list:
        """获取年刊分数历史记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit and limit > 0:
                    cursor.execute(
                        'SELECT * FROM yearly_scores ORDER BY timestamp ASC LIMIT ?',
                        (limit,))
                else:
                    cursor.execute(
                        'SELECT * FROM yearly_scores ORDER BY timestamp ASC')
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"获取年刊分数记录失败: {e}")
            return []

    def get_latest_yearly_score(self) -> Optional[Dict]:
        """获取最新一条年刊分数记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT * FROM yearly_scores ORDER BY timestamp DESC LIMIT 1')
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception:
            return None


class Database:
    """总数据库管理类"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, 'bilibili_monitor.db')
        
        self.db_path = db_path
        self.data_dir = os.path.dirname(db_path)
        self.init_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_database(self):
        """初始化数据库表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 视频信息表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS videos (
                    bvid TEXT PRIMARY KEY,
                    title TEXT,
                    view_count INTEGER DEFAULT 0,
                    like_count INTEGER DEFAULT 0,
                    coin_count INTEGER DEFAULT 0,
                    share_count INTEGER DEFAULT 0,
                    favorite_count INTEGER DEFAULT 0,
                    danmaku_count INTEGER DEFAULT 0,
                    reply_count INTEGER DEFAULT 0,
                    viewers_app INTEGER DEFAULT 0,
                    viewers_web INTEGER DEFAULT 0,
                    viewers_total INTEGER DEFAULT 0,
                    cover_path TEXT,
                    like_view_ratio REAL DEFAULT 0,
                    owner_name TEXT,
                    owner_id INTEGER,
                    pubdate TEXT,
                    duration INTEGER,
                    pic TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 监控记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS monitor_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bvid TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    view_count INTEGER,
                    like_count INTEGER,
                    coin_count INTEGER,
                    share_count INTEGER,
                    favorite_count INTEGER,
                    danmaku_count INTEGER,
                    reply_count INTEGER,
                    viewers_app INTEGER DEFAULT 0,
                    viewers_web INTEGER DEFAULT 0,
                    viewers_total INTEGER DEFAULT 0,
                    like_view_ratio REAL DEFAULT 0,
                    FOREIGN KEY (bvid) REFERENCES videos(bvid)
                )
            ''')
            
            # 预测记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bvid TEXT,
                    algorithm TEXT,
                    algorithm_id TEXT,
                    target_threshold INTEGER,
                    predicted_seconds INTEGER,
                    predicted_time TIMESTAMP,
                    confidence REAL,
                    current_views INTEGER,
                    is_reached BOOLEAN DEFAULT 0,
                    actual_time TIMESTAMP,
                    error_rate REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (bvid) REFERENCES videos(bvid)
                )
            ''')
            
            conn.commit()
    
    def get_video_db(self, bvid: str) -> VideoDatabase:
        """获取单个视频的数据库实例"""
        return VideoDatabase(bvid, self.data_dir)
    
    def sync_from_video_db(self, bvid: str) -> bool:
        """从单个视频数据库同步到总数据库"""
        try:
            video_db = VideoDatabase(bvid, self.data_dir)
            
            # 获取视频信息
            video_info = video_db.get_video_info()
            if video_info:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT OR REPLACE INTO videos 
                        (bvid, title, view_count, like_count, coin_count, share_count,
                         favorite_count, danmaku_count, reply_count, viewers_app,
                         viewers_web, viewers_total, cover_path, like_view_ratio,
                         owner_name, owner_id, pubdate, duration, pic, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        bvid, video_info.get('title', ''), video_info.get('view_count', 0),
                        video_info.get('like_count', 0), video_info.get('coin_count', 0),
                        video_info.get('share_count', 0), video_info.get('favorite_count', 0),
                        video_info.get('danmaku_count', 0), video_info.get('reply_count', 0),
                        video_info.get('viewers_app', 0), video_info.get('viewers_web', 0),
                        video_info.get('viewers_total', 0), video_info.get('cover_path', ''),
                        video_info.get('like_view_ratio', 0), video_info.get('owner_name', ''),
                        video_info.get('owner_id', 0), video_info.get('pubdate', ''),
                        video_info.get('duration', 0), video_info.get('pic', ''), datetime.now()
                    ))
                    conn.commit()
            
            # 获取所有监控记录并同步
            records = video_db.get_all_records()
            if records:
                with self._get_connection() as conn:
                    cursor = conn.cursor()
                    for record in records:
                        # 检查是否已存在
                        cursor.execute('''
                            SELECT id FROM monitor_records 
                            WHERE bvid = ? AND timestamp = ?
                        ''', (bvid, record['timestamp']))
                        
                        if not cursor.fetchone():
                            cursor.execute('''
                                INSERT INTO monitor_records 
                                (bvid, timestamp, view_count, like_count, coin_count, share_count,
                                 favorite_count, danmaku_count, reply_count, viewers_app,
                                 viewers_web, viewers_total, like_view_ratio)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                bvid, record['timestamp'], record['view_count'],
                                record['like_count'], record['coin_count'], record['share_count'],
                                record['favorite_count'], record['danmaku_count'], record['reply_count'],
                                record['viewers_app'], record['viewers_web'],
                                record['viewers_total'], record['like_view_ratio']
                            ))
                    conn.commit()
            
            return True
        except Exception as e:
            print(f"同步数据失败: {e}")
            return False
    
    def sync_all_video_dbs(self) -> Dict[str, bool]:
        """同步所有视频数据库到总数据库"""
        results = {}
        video_dirs = []
        
        # 遍历data目录下的所有BV号文件夹
        for item in os.listdir(self.data_dir):
            item_path = os.path.join(self.data_dir, item)
            if os.path.isdir(item_path) and item.startswith('BV'):
                video_dirs.append(item)
        
        for bvid in video_dirs:
            results[bvid] = self.sync_from_video_db(bvid)
        
        return results
    
    def add_video(self, video: VideoInfo) -> bool:
        """添加视频信息"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO videos 
                    (bvid, title, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, cover_path, like_view_ratio,
                     owner_name, owner_id, pubdate, duration, pic, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    video.bvid, video.title, video.view_count, video.like_count,
                    video.coin_count, video.share_count, video.favorite_count,
                    video.danmaku_count, video.reply_count, video.viewers_app,
                    video.viewers_web, video.viewers_total, video.cover_path,
                    video.like_view_ratio, video.owner_name, video.owner_id,
                    video.pubdate, video.duration, video.pic, datetime.now()
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"添加视频失败: {e}")
            return False
    
    def get_video(self, bvid: str) -> Optional[VideoInfo]:
        """获取视频信息"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM videos WHERE bvid = ?', (bvid,))
                row = cursor.fetchone()
                if row:
                    return VideoInfo(**dict(row))
                return None
        except Exception as e:
            print(f"获取视频失败: {e}")
            return None
    
    def add_monitor_record(self, record: MonitorRecord) -> bool:
        """添加监控记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO monitor_records 
                    (bvid, timestamp, view_count, like_count, coin_count, share_count,
                     favorite_count, danmaku_count, reply_count, viewers_app,
                     viewers_web, viewers_total, like_view_ratio)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record.bvid, record.timestamp, record.view_count, record.like_count,
                    record.coin_count, record.share_count, record.favorite_count,
                    record.danmaku_count, record.reply_count, record.viewers_app,
                    record.viewers_web, record.viewers_total, record.like_view_ratio
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"添加监控记录失败: {e}")
            return False
    
    def get_monitor_history(self, bvid: str, limit: int = 0) -> List[Dict]:
        """获取监控历史"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if limit and limit > 0:
                    cursor.execute('''
                        SELECT * FROM monitor_records 
                        WHERE bvid = ? 
                        ORDER BY timestamp ASC 
                        LIMIT ?
                    ''', (bvid, limit))
                else:
                    cursor.execute('''
                        SELECT * FROM monitor_records 
                        WHERE bvid = ? 
                        ORDER BY timestamp ASC
                    ''', (bvid,))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"获取监控历史失败: {e}")
            return []
    
    def add_prediction(self, prediction: PredictionRecord) -> bool:
        """添加预测记录"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO predictions 
                    (bvid, algorithm, algorithm_id, target_threshold, predicted_seconds,
                     predicted_time, confidence, current_views)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    prediction.bvid, prediction.algorithm, prediction.algorithm_id,
                    prediction.target_threshold, prediction.predicted_seconds,
                    prediction.predicted_time, prediction.confidence,
                    prediction.current_views
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"添加预测记录失败: {e}")
            return False
    
    def download_cover(self, bvid: str, pic_url: str) -> str:
        """下载视频封面"""
        try:
            cover_dir = os.path.join(os.path.dirname(self.db_path), 'cover')
            os.makedirs(cover_dir, exist_ok=True)
            
            cover_path = os.path.join(cover_dir, f"{bvid}.jpg")
            
            if os.path.exists(cover_path):
                return cover_path
            
            response = requests.get(pic_url, timeout=10)
            if response.status_code == 200:
                with open(cover_path, 'wb') as f:
                    f.write(response.content)
                return cover_path
        except Exception as e:
            print(f"下载封面失败: {e}")
        return ""
    
    def export_video_to_csv(self, bvid: str, filepath: str = None) -> str:
        """导出视频数据到CSV"""
        import csv
        
        if filepath is None:
            exports_dir = os.path.join(os.path.dirname(self.db_path), 'exports')
            os.makedirs(exports_dir, exist_ok=True)
            filepath = os.path.join(exports_dir, f"{bvid}.csv")
        
        try:
            video = self.get_video(bvid)
            history = self.get_monitor_history(bvid)
            
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['BV号', '标题', 'UP主', '播放量', '点赞数', '投币数',
                                '分享数', '收藏数', '弹幕数', '评论数', 'APP观看人数',
                                '网页观看人数', '总观看人数', '播赞比'])
                
                if video:
                    writer.writerow([
                        video.bvid, video.title, video.owner_name, video.view_count,
                        video.like_count, video.coin_count, video.share_count,
                        video.favorite_count, video.danmaku_count, video.reply_count,
                        video.viewers_app, video.viewers_web, video.viewers_total,
                        video.like_view_ratio
                    ])
            
            return filepath
        except Exception as e:
            print(f"导出失败: {e}")
            return ""


# 全局数据库实例
db = Database()
