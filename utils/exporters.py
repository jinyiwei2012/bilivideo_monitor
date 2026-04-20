"""
导出工具模块
包含数据导出功能
"""

import csv
import json
import os
import re
from typing import List, Dict, Any
from datetime import datetime


_BVID_RE = re.compile(r'^BV[A-Za-z0-9]{10}$')


def _validate_bvid(bvid: str) -> bool:
    """验证BV号格式（BV + 10位字母数字）"""
    return bool(_BVID_RE.match(bvid))


def export_to_csv(data: List[Dict[str, Any]], filepath: str, headers: List[str] = None) -> bool:
    """
    导出数据到CSV文件
    
    Args:
        data: 数据列表
        filepath: 文件路径
        headers: 表头（可选）
        
    Returns:
        是否成功
    """
    try:
        if not data:
            return False
        
        # 如果没有提供headers，使用第一个数据项的keys
        if headers is None:
            headers = list(data[0].keys())
        
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(data)
        
        return True
    except Exception as e:
        print(f"导出CSV失败: {e}")
        return False


def export_to_json(data: Any, filepath: str, indent: int = 2) -> bool:
    """
    导出数据到JSON文件
    
    Args:
        data: 数据
        filepath: 文件路径
        indent: 缩进
        
    Returns:
        是否成功
    """
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        return True
    except Exception as e:
        print(f"导出JSON失败: {e}")
        return False


def export_video_data(video_data: Dict[str, Any], directory: str, formats: List[str] = None) -> Dict[str, str]:
    """
    导出视频数据到多种格式
    
    Args:
        video_data: 视频数据
        directory: 导出目录
        formats: 格式列表 ['csv', 'json']
        
    Returns:
        导出的文件路径字典
    """
    if formats is None:
        formats = ['csv', 'json']
    
    bvid = video_data.get('bvid', 'unknown')
    exported_files = {}
    
    os.makedirs(directory, exist_ok=True)
    
    if 'csv' in formats:
        csv_path = os.path.join(directory, f"{bvid}.csv")
        if export_to_csv([video_data], csv_path):
            exported_files['csv'] = csv_path
    
    if 'json' in formats:
        json_path = os.path.join(directory, f"{bvid}.json")
        if export_to_json(video_data, json_path):
            exported_files['json'] = json_path
    
    return exported_files


def generate_export_filename(bvid: str, keyword: str = None, extension: str = 'csv') -> str:
    """
    生成导出文件名

    Args:
        bvid: BV号
        keyword: 关键词
        extension: 扩展名

    Returns:
        文件名

    Raises:
        ValueError: BV号格式非法
    """
    if not _validate_bvid(bvid):
        raise ValueError(f"无效的BV号: {bvid}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if keyword:
        # 清理关键词中的非法字符
        safe_keyword = re.sub(r'[\\/*?:"<>|,]', '_', keyword)
        return f"{safe_keyword}_{bvid}_{timestamp}.{extension}"
    else:
        return f"{bvid}_{timestamp}.{extension}"


__all__ = [
    'export_to_csv',
    'export_to_json',
    'export_video_data',
    'generate_export_filename'
]
