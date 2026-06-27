"""
模型训练标签页
"""

import os
import logging
import webbrowser
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTextEdit, QCheckBox, QSpinBox,
    QDoubleSpinBox, QGroupBox, QTabWidget, QFrame, QMessageBox,
    QScrollArea, QSizePolicy, QHeaderView, QTreeWidget, QTreeWidgetItem,
    QGridLayout, QProgressBar, QSplitter, QDialog, QFileDialog,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from ui.theme import C
from ui.helpers import FONT, FONT_BOLD, FONT_SM, FONT_MONO, project_path
from algorithms.registry import AlgorithmRegistry
from algorithms.weight_manager import get_weight_manager
from utils.update_checker import _s, _hard, _train, _confirm_risky
from ui.scrollable_frame import ScrollableFrame
from ui.settings_common import styled_label as _styled_label, field_wrapper as _field_wrapper

logger = logging.getLogger(__name__)


class SettingsTrainingMixin:
    """Model training settings tab."""

    def _build_training_tab(self, nb):
        page = QWidget()
        page.setStyleSheet(f"background-color: {C['bg_base']};")
        nb.addTab(page, "  模型训练  ")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        dev_sec = self._section(page, "训练设备", padding=(16, 12, 6))
        dev_layout = dev_sec.layout()

        dev_row = QWidget()
        dev_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        dr_layout = QHBoxLayout(dev_row)
        dr_layout.setContentsMargins(0, 4, 0, 4)
        dr_layout.addWidget(_styled_label("当前设备:", "text_2"))

        self._tr_force_cpu_var = False
        self._tr_device_lbl = _styled_label("检测中…", "text_1", bold=True)
        dr_layout.addWidget(self._tr_device_lbl)
        dr_layout.addSpacing(12)

        dr_layout.addWidget(_styled_label("推理设备:", "text_2"))
        self._tr_infer_device_cb = QComboBox()
        self._tr_infer_device_cb.addItems([
            "auto - 自动选择",
            "openvino_npu - OpenVINO NPU (Intel AI Boost)",
            "onnx_dml - ONNX DirectML (NPU)",
            "cuda - NVIDIA GPU",
            "cpu - CPU only",
        ])
        self._tr_infer_device_cb.currentIndexChanged.connect(lambda: self._on_infer_device_changed())
        dr_layout.addWidget(self._tr_infer_device_cb)

        # 恢复持久化的设备偏好
        from algorithms.training.device import get_preferred_device
        saved_pref = get_preferred_device()
        for i in range(self._tr_infer_device_cb.count()):
            if self._tr_infer_device_cb.itemText(i).startswith(saved_pref):
                self._tr_infer_device_cb.setCurrentIndex(i)
                break

        refresh_dev_btn = QPushButton("刷新")
        refresh_dev_btn.clicked.connect(self._refresh_device_info)
        dr_layout.addWidget(refresh_dev_btn)
        dr_layout.addStretch()
        dev_layout.addWidget(dev_row)

        mem_row = QWidget()
        mem_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        mr_layout = QHBoxLayout(mem_row)
        mr_layout.setContentsMargins(0, 2, 0, 0)
        self._tr_mem_lbl = _styled_label("", "text_3", font_=FONT_MONO)
        mr_layout.addWidget(self._tr_mem_lbl)
        dev_layout.addWidget(mem_row)

        # 数据规模
        data_sec = self._section(page, "数据规模", padding=(16, 6, 6))
        data_layout = data_sec.layout()
        self._tr_data_lbl = _styled_label("估算中…", "text_1")
        data_layout.addWidget(self._tr_data_lbl)
        refresh_data_btn = QPushButton("重新估算")
        refresh_data_btn.clicked.connect(self._refresh_data_size)
        data_layout.addWidget(refresh_data_btn)

        # 可训练算法列表
        list_sec = self._section(page, "可训练算法（PyTorch）", padding=(16, 6, 6))
        list_layout = list_sec.layout()

        hdr = QWidget()
        hdr.setStyleSheet(
            f"background-color: {C['bg_surface']}; "
            f"border: 1px solid {C['border_sub']};"
        )
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(4, 3, 4, 3)
        col_w = [("选择", 50), ("算法", 180), ("ID", 160), ("状态", 170), ("操作", 90)]
        for text, w in col_w:
            lbl = _styled_label(text, "text_2", bold=True, font_=FONT_SM)
            lbl.setFixedWidth(w)
            hdr_layout.addWidget(lbl)
        hdr_layout.addStretch()
        list_layout.addWidget(hdr)

        toolbar = QWidget()
        toolbar.setStyleSheet(f"background-color: {C['bg_elevated']};")
        tl_layout = QHBoxLayout(toolbar)
        tl_layout.setContentsMargins(0, 0, 0, 4)

        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(lambda: self._tr_select_all(True))
        tl_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("全不选")
        deselect_all_btn.clicked.connect(lambda: self._tr_select_all(False))
        tl_layout.addWidget(deselect_all_btn)

        select_untrained_btn = QPushButton("仅选未训练")
        select_untrained_btn.clicked.connect(self._tr_select_untrained)
        tl_layout.addWidget(select_untrained_btn)

        tl_layout.addStretch()
        self._tr_count_lbl = _styled_label("", "text_3", font_=FONT_SM)
        tl_layout.addWidget(self._tr_count_lbl)
        list_layout.addWidget(toolbar)

        sf = ScrollableFrame(bg=C["bg_elevated"])
        list_layout.addWidget(sf, stretch=1)
        self._tr_algo_frame = sf.inner
        self._tr_algo_frame.setStyleSheet(f"background-color: {C['bg_elevated']};")

        self._tr_check_vars = {}
        self._tr_algo_meta = {}

        ctrl_sec = self._section(page, "训练控制", padding=(16, 6, 12))
        ctrl_layout = ctrl_sec.layout()

        param_row = QWidget()
        param_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        pr_layout = QHBoxLayout(param_row)
        pr_layout.setContentsMargins(0, 4, 0, 4)
        pr_layout.addWidget(_styled_label("Epoch:", "text_2", font_=FONT_SM))
        self._tr_epoch_sb = QSpinBox()
        self._tr_epoch_sb.setRange(1, 500)
        self._tr_epoch_sb.setValue(20)
        self._tr_epoch_sb.setFixedWidth(70)
        pr_layout.addWidget(self._tr_epoch_sb)
        pr_layout.addSpacing(12)
        pr_layout.addWidget(_styled_label("Batch:", "text_2", font_=FONT_SM))
        self._tr_batch_sb = QSpinBox()
        self._tr_batch_sb.setRange(1, 512)
        self._tr_batch_sb.setValue(32)
        self._tr_batch_sb.setFixedWidth(70)
        pr_layout.addWidget(self._tr_batch_sb)
        pr_layout.addStretch()
        ctrl_layout.addWidget(param_row)

        btn_row = QWidget()
        btn_row.setStyleSheet(f"background-color: {C['bg_elevated']};")
        btnr_layout = QHBoxLayout(btn_row)
        btnr_layout.setContentsMargins(0, 4, 0, 4)

        self._tr_train_btn = QPushButton("▶ 训练所有勾选")
        self._tr_train_btn.clicked.connect(self._on_train_start)
        self._tr_train_btn.setEnabled(_train() == "normal")
        btnr_layout.addWidget(self._tr_train_btn)

        self._tr_cancel_btn = QPushButton("✕ 取消")
        self._tr_cancel_btn.clicked.connect(self._on_train_cancel)
        self._tr_cancel_btn.setEnabled(False)
        btnr_layout.addWidget(self._tr_cancel_btn)

        btnr_layout.addStretch()

        export_btn = QPushButton("📤 导出模型")
        export_btn.clicked.connect(self._on_export_checkpoints)
        btnr_layout.addWidget(export_btn)

        import_btn = QPushButton("📥 导入模型")
        import_btn.clicked.connect(self._on_import_checkpoints)
        import_btn.setEnabled(_train() == "normal")
        btnr_layout.addWidget(import_btn)

        if _train() != "normal":
            hint_lbl = _styled_label(
                "💡 创建 .enabletraining 文件开启训练 / 完整 devmode 见 README.md",
                "warning", font_=FONT_SM,
            )
            btnr_layout.addWidget(hint_lbl)

        ctrl_layout.addWidget(btn_row)

        self._tr_progress = QProgressBar()
        self._tr_progress.setRange(0, 100)
        self._tr_progress.setValue(0)
        ctrl_layout.addWidget(self._tr_progress)

        self._tr_status_lbl = _styled_label("就绪", "text_3", font_=FONT_SM)
        ctrl_layout.addWidget(self._tr_status_lbl)

        self._tr_thread = None
        self._tr_queue = None
        self._tr_cancel_flag = [False]
        self._tr_t0 = None

        self._refresh_device_info()
        self._refresh_data_size()
        self._refresh_algo_list()


    def _refresh_device_info(self):
        try:
            from algorithms.training.device import get_device_info, is_torch_available, force_cpu

            force_cpu(self._tr_force_cpu_var)
            info = get_device_info()
            if not is_torch_available():
                self._tr_device_lbl.setText("❌ torch 未安装（请 pip install torch）")
                self._tr_device_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent; font-weight: bold;")
            elif info.get("is_gpu"):
                mem = info.get("total_memory_gb", 0)
                self._tr_device_lbl.setText(f"✅ {info['name']} ({mem:.1f} GB) [{info['device']}]")
                self._tr_device_lbl.setStyleSheet(f"color: {C['success']}; background: transparent; font-weight: bold;")
            else:
                self._tr_device_lbl.setText(f"💻 {info['name']} ({info.get('device', 'cpu')})")
                self._tr_device_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent; font-weight: bold;")

            try:
                from utils.memory_guard import format_memory_info
                mem_str = format_memory_info()
                if hasattr(self, "_tr_mem_lbl"):
                    self._tr_mem_lbl.setText(mem_str)
            except Exception:
                pass
        except Exception as e:
            self._tr_device_lbl.setText(f"⚠ 检测失败: {e}")
            self._tr_device_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent; font-weight: bold;")


    def _on_infer_device_changed(self):
        val = self._tr_infer_device_cb.currentText().split(" - ")[0]
        try:
            from algorithms.training.device import set_preferred_device
            set_preferred_device(val)
            self._refresh_device_info()
        except Exception as e:
            logger.debug("设置推理设备失败: %s", e)


    def _refresh_data_size(self):
        self._tr_data_lbl.setText("估算中…")
        self._tr_data_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")

        def _worker():
            try:
                from algorithms.training.trainer import ModelTrainer
                tr = ModelTrainer()
                info = tr.estimate_data_size()
                total_videos = info.get("total_videos", 0)
                valid_videos = info.get("valid_videos", 0)
                total_samples = info.get("total_samples", 0)
                est_s = info.get("estimated_time_s", 0)
                eta_min = est_s / 60
                txt = (
                    f"视频总数: {total_videos}  ·  有效视频: {valid_videos}  ·  "
                    f"训练样本: {total_samples:,}\n"
                    f"预计单算法训练时间: {eta_min:.1f} 分钟"
                )
                QTimer.singleShot(0, lambda: [
                    self._tr_data_lbl.setText(txt),
                    self._tr_data_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
                ])
            except Exception as e:
                QTimer.singleShot(0, lambda e=e: [
                    self._tr_data_lbl.setText(f"⚠ 估算失败: {e}"),
                    self._tr_data_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
                ])

        import threading
        threading.Thread(target=_worker, daemon=True).start()


    def _refresh_algo_list(self):
        # 清空
        layout = self._tr_algo_frame.layout()
        if layout:
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()
        self._tr_check_vars.clear()
        self._tr_algo_meta.clear()

        try:
            from algorithms.registry import AlgorithmRegistry
            algos = AlgorithmRegistry.get_trainable_info()
        except Exception as e:
            err_lbl = _styled_label(f"⚠ 加载算法列表失败: {e}", "danger")
            (self._tr_algo_frame.layout() or QVBoxLayout(self._tr_algo_frame)).addWidget(err_lbl)
            return

        trained_n = sum(1 for a in algos if a["has_ckpt"])
        self._tr_count_lbl.setText(f"{len(algos)} 个算法 · 已训练 {trained_n}")

        for a in algos:
            aid = a["algorithm_id"]
            self._tr_algo_meta[aid] = a

            row = QWidget()
            row.setStyleSheet(
                f"background-color: {C['bg_surface']}; "
                f"border-bottom: 1px solid {C['border_sub']};"
            )
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 2, 4, 2)

            cb = QCheckBox()
            cb.setChecked(not a["has_ckpt"])
            self._tr_check_vars[aid] = cb
            cb.setFixedWidth(50)
            rl.addWidget(cb)

            name_lbl = _styled_label(a["name"], "text_1", font_=FONT)
            name_lbl.setFixedWidth(180)
            rl.addWidget(name_lbl)

            id_lbl = _styled_label(aid, "text_3", font_=FONT_MONO)
            id_lbl.setFixedWidth(160)
            rl.addWidget(id_lbl)

            if a["has_ckpt"]:
                status_txt = f"✅ {a['active_version'][:18]}" + (
                    f" (+{a['version_count'] - 1})" if a["version_count"] > 1 else ""
                )
                status_color = "success"
            else:
                status_txt = "□ 未训练"
                status_color = "text_3"
            status_lbl = _styled_label(status_txt, status_color, font_=FONT_SM)
            status_lbl.setFixedWidth(170)
            rl.addWidget(status_lbl)

            ver_btn = QPushButton("版本管理")
            ver_btn.clicked.connect(lambda checked, aid=aid: self._open_version_manager(aid))
            ver_btn.setFixedWidth(90)
            rl.addWidget(ver_btn)

            rl.addStretch()
            (self._tr_algo_frame.layout() or QVBoxLayout(self._tr_algo_frame)).addWidget(row)


    def _tr_select_all(self, flag: bool):
        for var in self._tr_check_vars.values():
            var.setChecked(flag)


    def _tr_select_untrained(self):
        for aid, var in self._tr_check_vars.items():
            var.setChecked(not self._tr_algo_meta.get(aid, {}).get("has_ckpt", False))


    def _on_train_start(self):
        from algorithms.training.device import is_torch_available

        if not is_torch_available():
            QMessageBox.critical(self.dlg, "torch 未安装", "请先安装 PyTorch:\npip install torch")
            return

        selected = [aid for aid, v in self._tr_check_vars.items() if v.isChecked()]
        if not selected:
            QMessageBox.warning(self.dlg, "提示", "请至少勾选一个算法")
            return

        epochs = max(1, self._tr_epoch_sb.value())
        batch = max(1, self._tr_batch_sb.value())

        if not QMessageBox.question(
            self.dlg, "确认训练",
            f"将训练 {len(selected)} 个算法，epoch={epochs}，batch={batch}。\n"
            "训练过程不可中途暂停（只能取消未开始的算法）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            return

        self._tr_train_btn.setEnabled(False)
        self._tr_cancel_btn.setEnabled(True)
        self._tr_cancel_flag[0] = False
        self._tr_progress.setValue(0)
        self._tr_status_lbl.setText(f"准备训练 {len(selected)} 个算法 …")
        self._tr_status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")

        import threading
        import queue as _q
        import time as _t

        self._tr_t0 = _t.time()
        self._tr_queue = _q.Queue()

        def _cb(payload: Dict):
            payload = dict(payload)
            payload["_total_selected"] = len(selected)
            self._tr_queue.put(payload)

        def _worker():
            try:
                from algorithms.training.trainer import ModelTrainer
                trainer = ModelTrainer()
                remaining = list(selected)
                results = {}
                while remaining:
                    if self._tr_cancel_flag[0]:
                        self._tr_queue.put({"stage": "cancelled", "remaining": remaining})
                        break
                    aid = remaining.pop(0)
                    sub = trainer.train_global([aid], epochs=epochs, batch_size=batch, progress_cb=_cb)
                    results.update(sub)
                self._tr_queue.put({"stage": "all_done", "results": results})
            except Exception as e:
                self._tr_queue.put({"stage": "fatal", "error": str(e)})

        self._tr_thread = threading.Thread(target=_worker, daemon=True)
        self._tr_thread.start()
        QTimer.singleShot(150, self._poll_training_progress)


    def _on_train_cancel(self):
        self._tr_cancel_flag[0] = True
        self._tr_cancel_btn.setEnabled(False)
        self._tr_status_lbl.setText("正在取消（等待当前算法完成）…")
        self._tr_status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")


    def _on_export_checkpoints(self):
        try:
            from utils.checkpoint_io import export_checkpoints
            path = export_checkpoints()
            self._tr_status_lbl.setText(f"导出完成: {os.path.basename(path)}")
            self._tr_status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
            if QMessageBox.question(
                self.dlg, "导出完成",
                f"模型已导出到:\n{path}\n\n是否打开所在文件夹？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes:
                os.startfile(os.path.dirname(path))
        except Exception as e:
            QMessageBox.critical(self.dlg, "导出失败", str(e))
            self._tr_status_lbl.setText(f"导出失败: {e}")
            self._tr_status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")


    def _on_import_checkpoints(self):
        path = QFileDialog.getOpenFileName(
            self.dlg, "选择要导入的 checkpoint 文件", "",
            "Zip 文件 (*.zip);;所有文件 (*.*)",
        )[0]
        if not path:
            return
        try:
            from utils.checkpoint_io import import_checkpoints
            count = import_checkpoints(path)
            QMessageBox.information(self.dlg, "导入完成", f"已导入 {count} 个算法的模型\n\n请刷新算法列表查看更新。")
            self._refresh_algo_list()
        except Exception as e:
            QMessageBox.critical(self.dlg, "导入失败", str(e))


    def _poll_training_progress(self):
        import queue as _q
        import time as _t

        if self._tr_queue is None:
            return

        done_all = False
        while True:
            try:
                msg = self._tr_queue.get_nowait()
            except _q.Empty:
                break
            stage = msg.get("stage")
            total_sel = msg.get("_total_selected", 1)

            if stage == "start":
                aid = msg.get("algo_id", "?")
                txt = f"[{msg.get('current', 0)}/{msg.get('total', 1)}] 开始训练 {aid} …"
                self._tr_status_lbl.setText(txt)
                self._tr_status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
            elif stage == "epoch":
                aid = msg.get("algo_id", "?")
                ep = msg.get("epoch", 0)
                eps = msg.get("epochs", 1)
                tloss = msg.get("train_loss", 0.0)
                vloss = msg.get("val_loss", -1.0)
                elapsed = msg.get("elapsed_s", 0.0)
                pct = min(100, int((ep / max(1, eps)) * 100))
                self._tr_progress.setValue(pct)
                vtxt = f" val={vloss:.4f}" if vloss >= 0 else ""
                eta_total = (_t.time() - self._tr_t0) if self._tr_t0 else 0
                txt = (
                    f"{aid}  ·  epoch {ep}/{eps}  ·  "
                    f"train={tloss:.4f}{vtxt}  ·  本算法 {elapsed:.1f}s  ·  累计 {eta_total:.1f}s"
                )
                self._tr_status_lbl.setText(txt)
                self._tr_status_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
            elif stage == "done":
                aid = msg.get("algo_id", "?")
                cur = msg.get("current", 0)
                ver = msg.get("version", "")
                self._tr_status_lbl.setText(f"✓ {aid} 完成 → {ver}  ({cur}/{total_sel})")
                self._tr_status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
                self._tr_progress.setValue(int(cur / max(1, total_sel) * 100))
            elif stage == "error":
                aid = msg.get("algo_id", "?")
                err = msg.get("error", "")
                self._tr_status_lbl.setText(f"✗ {aid} 失败: {err}")
                self._tr_status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
            elif stage == "cancelled":
                rem = msg.get("remaining", [])
                self._tr_status_lbl.setText(f"已取消，剩余 {len(rem)} 个算法未训练")
                self._tr_status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
                done_all = True
            elif stage == "all_done":
                results = msg.get("results", {})
                ok = sum(1 for v in results.values() if v)
                bad = sum(1 for v in results.values() if not v)
                elapsed = (_t.time() - self._tr_t0) if self._tr_t0 else 0
                self._tr_status_lbl.setText(f"全部完成: ✓ {ok}  ✗ {bad}  ·  耗时 {elapsed:.1f}s")
                self._tr_status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
                self._tr_progress.setValue(100)
                done_all = True
            elif stage == "fatal":
                err = msg.get("error", "")
                self._tr_status_lbl.setText(f"训练进程异常: {err}")
                self._tr_status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
                done_all = True

        if done_all:
            self._tr_train_btn.setEnabled(True)
            self._tr_cancel_btn.setEnabled(False)
            self._refresh_algo_list()
            self._tr_queue = None
            self._tr_thread = None
        else:
            QTimer.singleShot(200, self._poll_training_progress)


    def _open_version_manager(self, algo_id: str):
        from algorithms.training.checkpoint_manager import CheckpointManager
        ckpt = CheckpointManager(algo_id)
        top, tree = self._draw_version_ui(algo_id, ckpt)
        self._bind_version_events(top, tree, ckpt, algo_id)


    def _draw_version_ui(self, algo_id: str, ckpt):
        """构建版本管理窗口和版本列表 Treewidget"""
        top = QDialog(self.dlg)
        top.setWindowTitle(f"版本管理 — {algo_id}")
        top.setStyleSheet(f"background-color: {C['bg_surface']};")
        screen = top.screen()
        if screen:
            sw = screen.size().width()
            sh = screen.size().height()
            top.resize(int(sw * 0.40), int(sh * 0.45))
        else:
            top.resize(600, 400)
        top.setModal(True)

        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(14, 14, 14, 14)

        title_lbl = _styled_label(f"算法: {algo_id}", "text_1", bold=True)
        title_font = QFont("Microsoft YaHei UI", 11)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        top_layout.addWidget(title_lbl)

        cols = ("active", "version", "created", "samples", "val_loss")
        tree = QTreeWidget()
        tree.setHeaderLabels(["●", "版本", "创建时间", "样本数", "val_loss"])
        tree.setColumnCount(5)
        tree.setColumnWidth(0, 36)
        tree.setColumnWidth(1, 200)
        tree.setColumnWidth(2, 150)
        tree.setColumnWidth(3, 80)
        tree.setColumnWidth(4, 90)
        h = tree.headerItem()
        if h:
            h.setTextAlignment(0, Qt.AlignmentFlag.AlignCenter)
            h.setTextAlignment(3, Qt.AlignmentFlag.AlignRight)
            h.setTextAlignment(4, Qt.AlignmentFlag.AlignRight)
        tree.setRootIsDecorated(False)
        top_layout.addWidget(tree, stretch=1)

        self._refresh_version_detail(tree, ckpt)
        return top, tree


    def _refresh_version_detail(self, tree: QTreeWidget, ckpt) -> None:
        """清空并重新加载 TreeWidget 中的所有版本列表"""
        tree.clear()
        for v in ckpt.list_versions():
            marker = "✅" if v["active"] else ""
            val_loss = f"{v['val_loss']:.4f}" if v["val_loss"] >= 0 else "—"
            item = QTreeWidgetItem([marker, v["version"], v["created_at"], str(v["data_count"]), val_loss])
            if v["active"]:
                for col in range(5):
                    item.setForeground(col, Qt.GlobalColor.darkGreen)
            tree.addTopLevelItem(item)


    def _bind_version_events(self, top: QDialog, tree: QTreeWidget, ckpt, algo_id):
        """绑定版本管理的按钮命令（激活/删除/导出/关闭）"""

        def _reload():
            self._refresh_version_detail(tree, ckpt)

        def _selected_version() -> Optional[str]:
            items = tree.selectedItems()
            if not items:
                QMessageBox.warning(top, "提示", "请先选择一个版本")
                return None
            return items[0].text(1)

        def _do_activate():
            v = _selected_version()
            if v and ckpt.activate(v):
                _reload()
                self._refresh_algo_list()

        def _do_delete():
            v = _selected_version()
            if not v:
                return
            if not QMessageBox.question(top, "确认删除", f"确定删除版本 {v} 吗？",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                return
            if ckpt.delete(v):
                _reload()
                self._refresh_algo_list()

        def _do_export():
            v = _selected_version()
            if not v:
                return
            path = QFileDialog.getSaveFileName(
                top, "导出 checkpoint", f"{algo_id}_{v}.pt",
                "PyTorch checkpoint (*.pt);;所有文件 (*.*)",
            )[0]
            if not path:
                return
            try:
                import shutil
                src = project_path("algorithms", "checkpoints", algo_id, f"{v}.pt")
                shutil.copyfile(src, path)
                QMessageBox.information(top, "成功", f"已导出到:\n{path}")
            except Exception as e:
                QMessageBox.critical(top, "失败", f"导出失败: {e}")

        btn_f = QWidget()
        btn_f.setStyleSheet(f"background-color: {C['bg_surface']};")
        bf_layout = QHBoxLayout(btn_f)
        bf_layout.setContentsMargins(0, 4, 0, 0)

        activate_btn = QPushButton("激活")
        activate_btn.clicked.connect(_do_activate)
        bf_layout.addWidget(activate_btn)

        if _hard() == "normal":
            delete_btn = QPushButton("删除")
            delete_btn.clicked.connect(_do_delete)
            bf_layout.addWidget(delete_btn)
        else:
            ckpt_dir = project_path("algorithms", "checkpoints", algo_id)
            hint = _styled_label(f"📁 删除请到: {os.path.relpath(ckpt_dir)}", "text_3", font_=FONT_SM)
            bf_layout.addWidget(hint)

        export_btn = QPushButton("导出 .pt")
        export_btn.clicked.connect(_do_export)
        bf_layout.addWidget(export_btn)

        bf_layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(top.accept)
        bf_layout.addWidget(close_btn)

        (top.layout() or QVBoxLayout(top)).addWidget(btn_f)
