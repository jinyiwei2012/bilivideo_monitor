"""
训练面板 — Checkpoint 版本管理 Mixin

从 training_panel.py 提取的版本管理相关方法（查看/激活/删除 checkpoint 版本）。
"""
import os
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDialog, QFrame, QMessageBox,
)
from PyQt6.QtCore import Qt

from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO, project_path
from ui.scrollable_frame import ScrollableFrame
from utils.update_checker import _hard

logger = logging.getLogger(__name__)


class VersionManagerMixin:
    """Checkpoint 版本管理：查看、激活、删除模型版本。"""

    def _on_manage_versions(self, algo_id: str = None):
        """打开 checkpoint 版本管理对话框 — 查看/删除/激活版本。

        Args:
            algo_id: 指定算法时只显示该算法; None 显示全部可训练算法
        """
        from algorithms.training.checkpoint_manager import CheckpointManager
        from algorithms.registry import AlgorithmRegistry

        AlgorithmRegistry.initialize()
        algos = []
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            if algo_id and aid != algo_id:
                continue
            ckpt = CheckpointManager(aid)
            if ckpt.has_checkpoint() or os.path.exists(project_path("algorithms", "checkpoints", aid)):
                algos.append(
                    {
                        "algorithm_id": aid,
                        "name": getattr(algo, "name", aid),
                        "category": getattr(algo, "category", ""),
                    }
                )

        if not algos:
            QMessageBox.information(self, "知道啦 ♪", "还没有训练好的模型呢…♪")
            return

        self._show_manage_versions(algos, initial_aid=algo_id)

    def _show_manage_versions(self, algos, initial_aid: str = None):
        """打开版本管理对话框

        Args:
            algos: 算法列表 [{algorithm_id, name, category}, ...]
            initial_aid: 初始选中的算法 (None 时不自动选中)
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("Checkpoint 版本管理 ♪")
        dialog.resize(700, 500)
        dialog.setModal(True)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(8, 8, 8, 8)

        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        dlg_layout.addWidget(main, 1)

        left_panel = QFrame(main)
        left_panel.setStyleSheet(f"background-color: {C['bg_elevated']};")
        left_panel.setFixedWidth(220)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(left_panel)

        left_title = QLabel("算法")
        left_title.setStyleSheet(f"color: {C['text_2']}; background: transparent; padding: 4px;")
        left_title.setFont(FONT_SM)
        left_layout.addWidget(left_title)

        algo_sf = ScrollableFrame(left_panel, bg=C["bg_elevated"])
        left_layout.addWidget(algo_sf, 1)
        algo_inner = algo_sf.inner

        right_panel = QFrame(main)
        right_panel.setStyleSheet(f"background-color: {C['bg_surface']};")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(right_panel, 1)

        info_lbl = QLabel("← 先选一个算法哦 ♪")
        info_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        info_lbl.setFont(FONT)
        right_layout.addWidget(info_lbl)
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        detail_frame = QFrame(right_panel)
        detail_frame.setStyleSheet(f"background-color: {C['bg_surface']};")
        right_layout.addWidget(detail_frame, 1)

        def _refresh_detail(aid, name):
            self._draw_version_detail_pyqt(detail_frame, info_lbl, aid, name, _refresh_detail)

        self._draw_version_list_pyqt(algo_inner, algos, _refresh_detail)
        if initial_aid:
            # 自动选中指定算法, 跳过无 checkpoints 的过滤 (已保证 algos 含它)
            for a in algos:
                if a["algorithm_id"] == initial_aid:
                    _refresh_detail(initial_aid, a["name"])
                    break
        dialog.exec()

    def _draw_version_list_pyqt(self, algo_inner, algos, refresh_cb):
        """填充左侧算法列表按钮"""
        layout = algo_inner.layout() if algo_inner.layout() else QVBoxLayout(algo_inner)
        for a in sorted(algos, key=lambda x: x["name"]):
            btn = QPushButton(f"{a['name']}")
            btn.setStyleSheet(
                f"background-color: {C['bg_elevated']}; color: {C['text_1']}; font: {FONT_SM}; "
                f"text-align: left; padding: 3px 6px; border: none;"
            )
            aid_val = a["algorithm_id"]
            name_val = a["name"]
            btn.clicked.connect(lambda checked=False, aid=aid_val, n=name_val: refresh_cb(aid, n))
            layout.addWidget(btn)

    def _draw_version_detail_pyqt(self, detail_frame, info_lbl, aid, name, refresh_cb):
        """刷新指定算法的版本详情面板"""
        from algorithms.training.checkpoint_manager import CheckpointManager, list_video_finetune_bvids

        # Clear existing
        old_layout = detail_frame.layout()
        if old_layout is not None:
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        info_lbl.hide()

        layout = QVBoxLayout(detail_frame)
        layout.setContentsMargins(4, 4, 4, 4)

        title_lbl = QLabel(f"{name}  ({aid})")
        title_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        layout.addWidget(title_lbl)

        ckpt = CheckpointManager(aid)

        section_lbl = QLabel("全局版本 ♪")
        section_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        section_lbl.setFont(FONT_SM)
        layout.addWidget(section_lbl)

        versions = ckpt.list_versions()
        if not versions:
            no_ver = QLabel("  （还没有全局 checkpoint 呢…）♪")
            no_ver.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            no_ver.setFont(FONT_SM)
            layout.addWidget(no_ver)
        else:
            for v in versions:
                row = QFrame(detail_frame)
                row.setStyleSheet(f"background-color: {C['bg_elevated']};")
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(4, 1, 4, 1)
                layout.addWidget(row)

                active_tag = "★ " if v.get("active") else "  "
                ver_lbl = QLabel(f"{active_tag}{v['version']}")
                ver_lbl.setStyleSheet(
                    f"color: {C['success'] if v.get('active') else C['text_1']}; "
                    f"background: transparent; font: {FONT_MONO};"
                )
                ver_lbl.setFixedWidth(200)
                row_layout.addWidget(ver_lbl)

                if not v.get("active") and len(versions) > 1:
                    activate_btn = QPushButton("激活 ♪")
                    activate_btn.setFixedWidth(50)
                    ver_val = v["version"]
                    activate_btn.clicked.connect(
                        lambda checked=False, c=ckpt, ver=ver_val, a=aid, n=name, cb=refresh_cb: (
                            self._activate_version(c, ver, a, n, cb)
                        )
                    )
                    row_layout.addWidget(activate_btn)

                export_btn = QPushButton("导出 .pt ♪")
                export_btn.setFixedWidth(70)
                ver_val = v["version"]
                export_btn.clicked.connect(
                    lambda checked=False, c=ckpt, ver=ver_val, a=aid: (
                        self._export_version(c, ver, a)
                    )
                )
                row_layout.addWidget(export_btn)

                if len(versions) > 1:
                    del_btn = QPushButton("✕")
                    del_btn.setFixedWidth(30)
                    ver_val = v["version"]
                    del_btn.clicked.connect(
                        lambda checked=False, ver=ver_val, c=ckpt, a=aid, n=name, cb=refresh_cb: (
                            c.delete(ver),
                            cb(a, n),
                        )
                    )
                    row_layout.addWidget(del_btn)

                vl = v.get("val_loss", -1)
                meta_parts = []
                if vl >= 0:
                    meta_parts.append(f"val_loss={vl:.4f}")
                dc = v.get("data_count", 0)
                if dc:
                    meta_parts.append(f"{dc} 样本")
                ca = v.get("created_at", "")
                if ca:
                    meta_parts.append(str(ca)[:16])
                if meta_parts:
                    meta_lbl = QLabel("  ·  ".join(meta_parts))
                    meta_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
                    meta_lbl.setFont(FONT_SM)
                    row_layout.addWidget(meta_lbl)

                row_layout.addStretch()

        bvids = list_video_finetune_bvids(aid)
        if bvids:
            ft_lbl = QLabel("\n视频微调版本 ♪")
            ft_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
            ft_lbl.setFont(FONT_SM)
            layout.addWidget(ft_lbl)
            for bvid in bvids:
                v_ckpt = CheckpointManager(aid, bvid=bvid)
                v_vers = v_ckpt.list_versions()
                for v in v_vers:
                    row = QFrame(detail_frame)
                    row.setStyleSheet(f"background-color: {C['bg_elevated']};")
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(4, 1, 4, 1)
                    layout.addWidget(row)

                    bvid_lbl = QLabel(f"  📺 {bvid}  {v['version']}")
                    bvid_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
                    bvid_lbl.setFont(FONT_MONO)
                    row_layout.addWidget(bvid_lbl)
                    row_layout.addStretch()

                    del_btn = QPushButton("✕")
                    del_btn.setFixedWidth(30)
                    bvid_val = bvid
                    ver_val = v["version"]
                    del_btn.clicked.connect(
                        lambda checked=False, b=bvid_val, ver=ver_val, a=aid, n=name, cb=refresh_cb: (
                            CheckpointManager(a, bvid=b).delete(ver),
                            cb(a, n),
                        )
                    )
                    row_layout.addWidget(del_btn)

        if versions or bvids:
            layout.addSpacing(4)
            sep = QFrame(detail_frame)
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {C['border']};")
            layout.addWidget(sep)

            btn_row = QWidget()
            btn_row_layout = QHBoxLayout(btn_row)
            btn_row_layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(btn_row)

            if _hard() == "normal":
                del_global_btn = QPushButton("删除所有全局版本 ♪")
                del_global_btn.clicked.connect(
                    lambda checked=False, a=aid, n=name: self._delete_all_global(a, n, refresh_cb)
                )
                btn_row_layout.addWidget(del_global_btn)
                if bvids:
                    del_video_btn = QPushButton("删除所有微调版本 ♪")
                    del_video_btn.clicked.connect(
                        lambda checked=False, a=aid, n=name: self._delete_all_video(a, n, refresh_cb)
                    )
                    btn_row_layout.addWidget(del_video_btn)
            else:
                ckpt_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "algorithms", "checkpoints", aid,
                )
                dir_lbl = QLabel(f"📁 {os.path.relpath(ckpt_dir)}")
                dir_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
                dir_lbl.setFont(FONT_SM)
                btn_row_layout.addWidget(dir_lbl)
            btn_row_layout.addStretch()

        layout.addStretch()

    def _activate_version(self, ckpt, ver, aid, name, refresh_cb):
        """激活指定版本并刷新详情"""
        ckpt.activate(ver)
        refresh_cb(aid, name)

    def _export_version(self, ckpt, ver, aid):
        """导出指定版本的 checkpoint 到用户指定路径"""
        from PyQt6.QtWidgets import QFileDialog

        path = QFileDialog.getSaveFileName(
            self, "导出 checkpoint", f"{aid}_{ver}.pt",
            "PyTorch checkpoint (*.pt);;所有文件 (*.*)",
        )[0]
        if not path:
            return
        try:
            import shutil
            src = os.path.join(project_path("algorithms", "checkpoints", aid), f"{ver}.pt")
            shutil.copyfile(src, path)
            QMessageBox.information(self, "完成啦 ♪", f"已导出到:\n{path}")
        except Exception as e:
            logger.error("导出checkpoint版本失败", exc_info=True)
            QMessageBox.critical(self, "呜…出错了", "呜…导出失败啦，请稍后再试哦 ♪")

    def _delete_all_global(self, aid, name, refresh_cb):
        """删除算法的所有全局 checkpoint。"""
        reply = QMessageBox.question(
            self, "要注意哦…",
            f"真的要删除 {name} ({aid}) 的所有全局版本吗？\n删掉就找不回来啦…♪",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from algorithms.training.checkpoint_manager import CheckpointManager

        ckpt = CheckpointManager(aid)
        for v in ckpt.list_versions():
            ckpt.delete(v["version"])
        refresh_cb(aid, name)
        self._refresh_algo_list()

    def _delete_all_video(self, aid, name, refresh_cb):
        """删除算法的所有视频微调 checkpoint。"""
        reply = QMessageBox.question(
            self, "要注意哦…",
            f"真的要删除 {name} ({aid}) 的所有视频微调版本吗？\n删掉就找不回来啦…♪",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from algorithms.training.checkpoint_manager import CheckpointManager, list_video_finetune_bvids

        for bvid in list_video_finetune_bvids(aid):
            ckpt = CheckpointManager(aid, bvid=bvid)
            for v in ckpt.list_versions():
                ckpt.delete(v["version"])
        refresh_cb(aid, name)
