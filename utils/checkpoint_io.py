"""
Checkpoint 批量导出/导入
打包/解包 algorithms/checkpoints/ 目录，跨机器迁移训练模型
"""

import os
import shutil
import logging
import tempfile
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_CKPT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "algorithms", "checkpoints"))


def get_checkpoints_dir() -> str:
    return os.path.abspath(_CKPT_ROOT)


def export_checkpoints(output_path: Optional[str] = None) -> str:
    """打包 checkpoints/ 为 zip 文件。返回输出路径。"""
    src = get_checkpoints_dir()
    if not os.path.isdir(src):
        raise FileNotFoundError(f"checkpoints 目录不存在: {src}")
    if not os.listdir(src):
        raise FileNotFoundError("checkpoints 目录为空，无可导出的模型")

    exports_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "exports"))
    os.makedirs(exports_dir, exist_ok=True)

    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(exports_dir, f"checkpoints_{ts}.zip")

    base_name = output_path.rstrip(".zip")
    logger.info("导出 checkpoint 到 %s ...", output_path)
    shutil.make_archive(base_name, "zip", src)
    logger.info("导出完成: %s (%d bytes)", output_path, os.path.getsize(output_path))
    return output_path


def import_checkpoints(zip_path: str, merge: bool = True) -> int:
    """从 zip 文件导入 checkpoint。
    
    Args:
        zip_path: zip 文件路径
        merge: True 时合并（同名跳过），False 时覆盖
        
    Returns:
        导入的算法数量
    """
    if not os.path.isfile(zip_path):
        raise FileNotFoundError(f"文件不存在: {zip_path}")

    dst = get_checkpoints_dir()
    os.makedirs(dst, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        shutil.unpack_archive(zip_path, tmp, "zip")
        imported = 0
        for algo_id in os.listdir(tmp):
            src_algo = os.path.join(tmp, algo_id)
            dst_algo = os.path.join(dst, algo_id)
            if not os.path.isdir(src_algo):
                continue
            if os.path.exists(dst_algo):
                if merge:
                    # 合并：只复制不存在的文件
                    _merge_dir(src_algo, dst_algo)
                else:
                    # 覆盖
                    shutil.rmtree(dst_algo)
                    shutil.copytree(src_algo, dst_algo)
            else:
                shutil.copytree(src_algo, dst_algo)
            imported += 1
        logger.info("导入完成: %d 个算法", imported)
        return imported


def _merge_dir(src: str, dst: str):
    """递归合并目录，同名文件跳过。"""
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s):
            _merge_dir(s, d)
        elif not os.path.exists(d):
            shutil.copy2(s, d)
