"""
Checkpoint（算法模型检查点）批量导出/导入模块

功能说明：
- 导出 (export): 将 algorithms/checkpoints/ 目录下的所有训练模型
  打包为 ZIP 文件，方便跨机器迁移和备份
- 导入 (import): 从 ZIP 文件恢复模型到 checkpoints/ 目录，
  支持合并（同名跳过）和覆盖两种模式

安全特性：
- ZIP 路径穿越防护：使用 realpath 比较防止恶意 ZIP 中的 ../ 逃逸攻击
- 合并模式避免误覆盖已有模型
- 导出目录自动创建，不覆盖已有文件

使用场景：
- 在一台机器上训练模型后，导出到另一台机器使用
- 定期备份模型，防止训练成果丢失
- 团队间共享训练好的模型
"""

import os
import shutil
import logging
import tempfile
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Checkpoint 根目录：algorithms/checkpoints/
_CKPT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "algorithms", "checkpoints")
)


def get_checkpoints_dir() -> str:
    """获取 checkpoint 根目录的绝对路径。

    Returns:
        str: algorithms/checkpoints/ 的绝对路径
    """
    return os.path.abspath(_CKPT_ROOT)


def export_checkpoints(output_path: Optional[str] = None) -> str:
    """打包 checkpoints/ 目录为 ZIP 文件。

    输出到 exports/ 目录，文件名格式：checkpoints_{timestamp}.zip

    Args:
        output_path: 输出 ZIP 文件路径，为 None 时自动生成

    Returns:
        str: 生成的 ZIP 文件路径

    Raises:
        FileNotFoundError: checkpoints 目录不存在或为空
    """
    src = get_checkpoints_dir()
    if not os.path.isdir(src):
        raise FileNotFoundError(f"checkpoints 目录不存在: {src}")
    if not os.listdir(src):
        raise FileNotFoundError("checkpoints 目录为空，无可导出的模型")

    # 确保 exports/ 目录存在
    exports_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "exports"))
    os.makedirs(exports_dir, exist_ok=True)

    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(exports_dir, f"checkpoints_{ts}.zip")

    # 去掉 .zip 后缀用于 shutil.make_archive（它会自动添加）
    base_name = output_path[:-4] if output_path.endswith(".zip") else output_path
    logger.info("导出 checkpoint 到 %s ...", output_path)
    shutil.make_archive(base_name, "zip", src)
    logger.info("导出完成: %s (%d bytes)", output_path, os.path.getsize(output_path))
    return output_path


def import_checkpoints(zip_path: str, merge: bool = True) -> int:
    """从 ZIP 文件导入 checkpoint 模型。

    安全特性：
    - 使用 realpath 比较每个解压条目的目标路径，拦截路径穿越攻击
    - 支持合并模式（同名不覆盖）和覆盖模式

    Args:
        zip_path: zip 文件的完整路径
        merge: 合并模式
               - True: 合并导入，只复制目标不存在的文件（安全）
               - False: 覆盖导入，完全覆盖已有模型

    Returns:
        int: 成功导入的算法模型数量

    Raises:
        FileNotFoundError: ZIP 文件不存在
    """
    if not os.path.isfile(zip_path):
        raise FileNotFoundError(f"文件不存在: {zip_path}")

    dst = get_checkpoints_dir()
    os.makedirs(dst, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        # 使用 zipfile 解压，逐条校验路径防止 ZIP 路径穿越攻击
        import zipfile

        # 获取临时目录的真实绝对路径用于路径穿越检测
        tmp_abs = os.path.realpath(tmp)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                # 计算解压后的实际路径并做 realpath 比较
                dest_path = os.path.realpath(os.path.join(tmp, info.filename))
                # 确保目标路径在临时目录内（拦截 ../ 等路径穿越）
                if not dest_path.startswith(tmp_abs + os.sep):
                    logger.warning("路径穿越已拦截: %s", info.filename)
                    continue
                zf.extract(info, tmp)

        imported = 0
        # 遍历解压后的每个算法子目录
        for algo_id in os.listdir(tmp):
            src_algo = os.path.join(tmp, algo_id)
            dst_algo = os.path.join(dst, algo_id)
            if not os.path.isdir(src_algo):
                continue  # 跳过非目录条目
            if os.path.exists(dst_algo):
                if merge:
                    # 合并模式：只复制目标不存在的文件（保护已有数据）
                    _merge_dir(src_algo, dst_algo)
                else:
                    # 覆盖模式：删除旧的，完全替换
                    shutil.rmtree(dst_algo)
                    shutil.copytree(src_algo, dst_algo)
            else:
                shutil.copytree(src_algo, dst_algo)  # 目标不存在，直接复制
            imported += 1
        logger.info("导入完成: %d 个算法", imported)
        return imported


def _merge_dir(src: str, dst: str):
    """递归合并目录：只复制目标不存在的文件，同名跳过。

    用于导入时的"合并模式"，保护已有模型不被覆盖。

    Args:
        src: 源目录路径
        dst: 目标目录路径
    """
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s):
            _merge_dir(s, d)  # 递归处理子目录
        elif not os.path.exists(d):
            shutil.copy2(s, d)  # 仅复制不存在的文件
