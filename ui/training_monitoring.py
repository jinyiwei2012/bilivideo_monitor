"""Training quality monitor reactions."""

from PyQt6.QtWidgets import QLineEdit

from ui.training_base import _TrainingPanelContract


class TrainingMonitoringMixin(_TrainingPanelContract):
    _lr_entry: QLineEdit

    def _on_monitor_changed(self):
        """日志记录：状态变化时记录，同状态每 8 epoch 持续监测提醒。"""
        if self._monitor.level in ("warning", "danger") and self._monitor.suggestions:
            cur_status = self._monitor.status
            last_status = getattr(self, "_last_monitor_status", "")
            last_epoch = getattr(self, "_last_monitor_log_epoch", 0)
            cur_epoch = len(self._monitor._points)

            if cur_status != last_status or cur_epoch - last_epoch >= 8:
                self._last_monitor_status = cur_status
                self._last_monitor_log_epoch = cur_epoch
                prefix = "◉ 训练质量检测" if cur_status != last_status else "⟳ 持续监测"
                self._append_log(f"{prefix}: {cur_status}")
                for s in self._monitor.suggestions:
                    self._append_log(f"  ✦ {s}")

                # 学习率建议：显示当前值和推荐值
                lr_suggestion = self._compute_lr_suggestion()
                if lr_suggestion:
                    self._append_log(f"  ◫ {lr_suggestion}")

    def _compute_lr_suggestion(self) -> str:
        """根据 TrainingMonitor 的 loss 数据动态计算推荐学习率。"""
        suggestions_text = " ".join(self._monitor.suggestions).lower()
        if "增大学习率" in suggestions_text or "下降过慢" in self._monitor.status:
            scale = self._monitor.compute_lr_scale("underfitting")
            try:
                cur_lr = float(self._lr_entry.text())
            except (ValueError, TypeError):
                cur_lr = 0.001
            new_lr = cur_lr * scale
            return f"学习率 {cur_lr:.6f} → {new_lr:.6f} (×{scale:.2f}) — 点击 LR 输入框可手动应用"
        elif "大幅降低" in suggestions_text:
            scale = self._monitor.compute_lr_scale("explosion")
            try:
                cur_lr = float(self._lr_entry.text())
            except (ValueError, TypeError):
                cur_lr = 0.001
            new_lr = cur_lr * scale
            return f"学习率 {cur_lr:.6f} → {new_lr:.6f} (×{scale:.2f}) — 点击 LR 输入框可手动应用"
        elif "降低学习率" in suggestions_text:
            status = self._monitor.status
            issue = "oscillation" if "波动" in status else "overfitting"
            scale = self._monitor.compute_lr_scale(issue)
            try:
                cur_lr = float(self._lr_entry.text())
            except (ValueError, TypeError):
                cur_lr = 0.001
            new_lr = cur_lr * scale
            return f"学习率 {cur_lr:.6f} → {new_lr:.6f} (×{scale:.2f}) — 点击 LR 输入框可手动应用"
        return ""
