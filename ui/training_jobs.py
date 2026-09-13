"""Training parameter validation and configuration."""

from typing import List

from PyQt6.QtWidgets import QMessageBox

from ui.theme import C
from utils.update_checker import _confirm_risky

_torch_available = True
try:
    import torch  # noqa: F401
except ImportError:
    _torch_available = False


class TrainingJobsMixin:
    def _on_lr_auto_toggle(self):
        """自动/手动学习率切换：自动时锁定输入框，并填入推荐值。"""
        if self._lr_auto_cb.isChecked():
            self._lr_entry.setReadOnly(True)
            auto_lr = self._auto_compute_lr()
            self._lr_entry.setText(f"{auto_lr:.6f}")
        else:
            if _confirm_risky("切换到手动学习率模式", self):
                self._lr_entry.setReadOnly(False)
            else:
                self._lr_auto_cb.setChecked(True)

    def _auto_compute_lr(self) -> float:
        """根据数据规模和常用经验自动推荐学习率。"""
        try:
            from algorithms.training.trainer import ModelTrainer

            info = ModelTrainer().estimate_data_size()
            samples = info.get("total_samples", 1000)
        except Exception:
            samples = 1000

        # 样本越多 → 学习率应越小（避免在大数据集上震荡）
        if samples < 500:
            return 5e-3  # 小数据集：较大学习率快速收敛
        elif samples < 5000:
            return 2e-3  # 中等
        elif samples < 20000:
            return 1e-3  # 标准 Adam 默认值
        elif samples < 100000:
            return 5e-4  # 大数据集
        else:
            return 1e-4  # 超大数据集

    def _on_train_start(self):
        """开始训练按钮回调 — 验证参数、确认、启动训练线程"""
        config = self._validate_train_params()
        if config is None:
            return

        (
            selected,
            epochs,
            batch,
            is_incremental,
            lr,
            mode_label,
            lr_label,
            parallel,
            batch_log,
            interval_val,
            interval_unit,
        ) = config
        self._build_train_config(selected, epochs, batch, mode_label, lr)
        self._start_train_thread(
            selected, is_incremental, lr, epochs, batch, parallel, batch_log, interval_val, interval_unit
        )

    def _validate_train_params(self):
        """校验训练参数并弹出确认对话框，返回训练配置或 None"""
        if self._training:
            return None
        if not _torch_available:
            QMessageBox.critical(self, "呜…torch 未安装", "呜…要先安装 PyTorch 哦:\npip install torch ♪")
            return None

        selected = [aid for aid, cb in self._check_vars.items() if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "要注意哦…", "至少要勾选一个算法哦,天依才能开唱 ♪")
            return None

        epochs = max(1, self._epoch_spin.value())
        batch = max(1, self._batch_spin.value())
        is_incremental = self._mode_incremental.isChecked()
        mode_label = "增量训练" if is_incremental else "重新训练"

        # 并行数 + VRAM 安全检查
        parallel = max(1, min(4, self._parallel_spin.value()))
        if parallel > len(selected):
            parallel = len(selected)
        parallel_warning = ""
        try:
            from algorithms.training.device import get_device_info

            dev_info = get_device_info()
            if dev_info.get("is_gpu") and dev_info.get("total_memory_gb", 0) > 0:
                vram_gb = dev_info["total_memory_gb"]
                # 保守估计每个模型 ~0.4GB（实际模型多数 < 50MB，0.4GB 已含余量）
                est_per_model_gb = 0.4
                max_safe = max(1, int(vram_gb / est_per_model_gb))
                if parallel > max_safe:
                    parallel = max_safe
                    parallel_warning = (
                        f"\n♪ 显存的小舞台只有 {vram_gb:.1f}GB 呢,"
                        f"天依先把并行降到 {parallel},免得歌声挤在一起卡住哦"
                    )
        except Exception:
            pass

        if self._lr_auto_cb.isChecked():
            lr = self._auto_compute_lr()
            self._lr_entry.setText(f"{lr:.6f}")
            lr_label = f"自动 ({lr:.6f})"
        else:
            try:
                lr = float(self._lr_entry.text())
            except (ValueError, TypeError):
                QMessageBox.critical(self, "呜…学习率无效", "呜…天依看不懂这个学习率呢…请输入有效的数字哦 ♪")
                return None
            lr = max(1e-8, min(1.0, lr))
            lr_label = f"手动 ({lr:.6f})"

        reply = QMessageBox.question(
            self,
            "要开始训练吗 ♪",
            f"天依要开始训练啦 ♪\n"
            f"模式: {mode_label}  并行: {parallel}\n"
            f"算法: {len(selected)} 个\n"
            f"epoch={epochs}  batch={batch}  LR={lr_label}"
            f"{parallel_warning}\n"
            f"训练过程不能中途暂停哦(只能取消还没开始的算法)…♪",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return None

        return (
            selected,
            epochs,
            batch,
            is_incremental,
            lr,
            mode_label,
            lr_label,
            parallel,
            self._batch_log_cb.isChecked(),
            self._batch_interval_entry.text(),
            self._batch_interval_combo.currentText(),
        )

    def _build_train_config(self, selected, epochs, batch, mode_label, lr):
        """重置训练状态、打开日志文件、更新状态标签"""
        self._prepare_training()
        self._open_log_file(len(selected), epochs, batch, mode_label, lr)
        self._append_log(
            f"♬ 开始训练: {mode_label}, {len(selected)} 个算法, epoch={epochs}, batch={batch}, lr={lr:.6f}"
        )
        if self._batch_log_cb.isChecked():
            val = self._batch_interval_entry.text()
            unit = self._batch_interval_combo.currentText()
            self._append_log(f"☰ 详细日志：每 {val}{unit} batch 输出进度")
        self._status_lbl.setText(f"天依在准备哦…要训练 {len(selected)} 个算法呢 ♪")
        self._status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")

        # ── 全局反馈：窗口标题 + 主界面状态栏 ──
        try:
            top = self.window()
            if top and top.window():
                self._saved_title = top.windowTitle()
                top.setWindowTitle(f"● 训练中 — {self._saved_title}")
        except Exception:
            self._saved_title = None
        self._safe_sb("algo", f"◉ 训练: 0/{len(selected)} 算法 ♪", color=C["accent"])
        self._safe_sb("status", "天依正在认真练习呢…像准备演唱会一样,再等等哦 ♪", color=C["accent"])
        self._algo_durations: List[float] = []  # 各算法耗时（用于跨算法 ETA）
