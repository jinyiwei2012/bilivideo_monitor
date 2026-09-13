"""Finetune queue-stage handling and UI progress updates."""

import logging
import time

from ui.helpers import format_confidence, loss_to_confidence
from ui.theme import C

logger = logging.getLogger(__name__)


class FinetuneProgressMixin:
    """Handle queued finetune progress messages on the UI thread."""

    STAGE_HANDLERS = {
        "start": "_on_stage_start",
        "epoch": "_on_stage_epoch",
        "done": "_on_stage_done",
        "error": "_on_stage_error",
        "auto_adjust": "_on_stage_auto_adjust",
        "log": "_on_stage_log",
        "cancelled": "_on_stage_cancelled",
        "all_done": "_on_stage_all_done",
    }

    def _handle_stage(self, msg) -> bool:
        """根据消息阶段字段分发到对应的处理函数"""
        stage = msg.get("stage")
        handler_name = self.STAGE_HANDLERS.get(stage)
        if handler_name:
            return getattr(self, handler_name)(msg)
        return False

    def _on_stage_start(self, msg):
        """处理微调任务开始阶段：更新 UI 状态和进度"""
        done = msg.get("done", 0)
        total = msg.get("total", 1)
        aid = msg.get("aid", "?")
        bvid = msg.get("bvid", "?")
        self._current_bvid = bvid
        self._current_aid = aid

        if bvid not in self._video_results:
            self._loss_history.clear()
            self._clear_chart()
            self._monitor.reset()
            self._task_lbl.setText(f"◎ 天依开始微调 {aid} → {bvid} 啦 ♪")
            self._task_lbl.setStyleSheet(f"color: {C['accent']}; background: transparent;")
        else:
            self._task_lbl.setText(f"◎ 天依在微调 {aid} → {bvid} 呢 ♪")
            self._task_lbl.setStyleSheet(f"color: {C['accent']}; background: transparent;")
        self._task_detail.setText(f"{done}/{total}")
        pct = min(100, int(done / max(1, total) * 100))
        self._progress.setValue(pct)
        self._status_lbl.setText(f"[{done}/{total}] 天依在练习 {aid} → {bvid} 呢 ♪")
        self._status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        self._append_log(f"── [{done}/{total}] 开始微调 {aid}@{bvid} ──")
        self.main.set_finetune_status(f"◎ 天依在微调 {bvid}: [{done}/{total}] {aid} ♪")
        self._refresh_algo_row(0, aid, "▶ 训练中", C["accent"], "", "", "")

    def _on_stage_epoch(self, msg):
        """处理每个 epoch 的进度更新：更新 Loss 图表、进度条和质量监控"""
        aid = msg.get("algo_id", self._current_aid)
        bvid = msg.get("bvid", self._current_bvid)
        ep = msg.get("epoch", 0)
        eps = msg.get("epochs", 1)
        total_ep = msg.get("total_epoch", ep)
        total_eps = msg.get("total_epochs", eps)
        tloss = msg.get("train_loss", 0.0)
        vloss = msg.get("val_loss", -1.0)
        elapsed = msg.get("elapsed_s", 0.0)

        conf = loss_to_confidence(vloss) if vloss >= 0 else 0.0
        conf_str, _ = format_confidence(conf)

        # 计算并更新进度百分比
        pct = min(100, int((ep / max(1, eps)) * 100))
        self._progress.setValue(pct)
        vtxt = f"  val={vloss:.4f}" if vloss >= 0 else ""
        ctrl_data = msg.get("_control", {})
        ep_display = f"{total_ep}/{total_eps}" if total_eps != eps else f"{ep}/{eps}"
        if ctrl_data.get("early_stop"):
            self._status_lbl.setText(f"{aid}@{bvid}  第 {ep_display} 轮 ⏹ 天依要提前停下啦 ♪")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        elif ctrl_data.get("lr_scale"):
            self._status_lbl.setText(f"{aid}@{bvid}  第 {ep_display} 轮 ⚡ 天依在调整音准呢 ♪")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        else:
            self._status_lbl.setText(
                f"{aid}@{bvid}  第 {ep_display} 轮,天依越唱越准啦 ♪  train={tloss:.4f}{vtxt}  {conf_str}  {elapsed:.0f}s"
            )
            self._status_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")

        self._monitor.update(ep, tloss, vloss if vloss >= 0 else -1)
        self._refresh_monitor()

        self._loss_history.append(
            {
                "algo": aid,
                "bvid": bvid,
                "epoch": ep,
                "train_loss": tloss,
                "val_loss": vloss,
            }
        )
        self._update_chart()
        adj = msg.get("_adjustment", "")
        adj_suffix = f"  |  {adj}" if adj else ""
        self._append_log(
            f"  epoch {total_ep:>3}/{total_eps}  |  "
            f"train_loss={tloss:.6f}  |  "
            f"{f'val_loss={vloss:.6f}' if vloss >= 0 else 'val_loss=N/A'}  |  "
            f"confidence={conf_str}  |  "
            f"{elapsed:.1f}s{adj_suffix}"
        )

    def _on_stage_done(self, msg):
        """处理单个算法微调完成阶段：更新结果缓存和 UI"""
        done = msg.get("done", 0)
        total = msg.get("total", 1)
        aid = msg.get("aid", "?")
        bvid = msg.get("bvid", "?")
        ver = msg.get("version", "")
        conf = msg.get("confidence", 0.0)
        val_loss = msg.get("val_loss", -1.0)

        pct = min(100, int(done / max(1, total) * 100))
        self._progress.setValue(pct)
        self._task_detail.setText(f"{done}/{total}")
        conf_str, conf_color = format_confidence(conf)

        if bvid not in self._video_results:
            self._video_results[bvid] = []
        self._video_results[bvid].append(
            {
                "aid": aid,
                "version": ver,
                "confidence": conf,
                "val_loss": val_loss,
            }
        )

        self._refresh_algo_row(0, aid, f"✓ {ver}", C["success"], conf_str, conf_color, f"v{msg.get('done', 0)}")

        self._status_lbl.setText(f"✓ {aid}@{bvid} 唱好啦 ♪ → {ver}  conf={conf_str}  ({done}/{total})")
        self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        self._append_log(f"  ✓ {aid}@{bvid} → {ver}  置信度={conf_str}  val_loss={val_loss:.4f}")

    def _on_stage_error(self, msg):
        """处理微调出错阶段：显示错误信息并更新 UI"""
        done = msg.get("done", 0)
        total = msg.get("total", 1)
        aid = msg.get("aid", "?")
        bvid = msg.get("bvid", "?")
        err = msg.get("error", "")
        pct = min(100, int(done / max(1, total) * 100))
        self._progress.setValue(pct)
        self._task_detail.setText(f"{done}/{total}")
        self._status_lbl.setText(f"呜…{aid}@{bvid} 没学会呢,天依不会放弃的,看看日志再试一次哦 ♪")
        self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
        self._append_log(f"  ✗ {aid}@{bvid}: {err}")
        self._refresh_algo_row(0, aid, "✗ 失败", C["danger"], "", "", "")

    def _on_stage_auto_adjust(self, msg):
        """处理自动调整事件：记录调整操作到日志"""
        action = msg.get("action", "")
        message = msg.get("message", "")
        self._append_log(f"  ⚙ 自动调整: {message}")
        self._status_lbl.setText(f"⚡ {message} ♪")
        self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        if action == "early_stop":
            self._monitor_status.setText("⏹ 天依提前停下啦 ♪")
            self._monitor_status.setStyleSheet(f"color: {C['warning']}; background: transparent;")

    def _on_stage_log(self, msg):
        """处理日志消息：追加到日志面板"""
        self._append_log(msg.get("text", ""))

    def _on_stage_cancelled(self, msg):
        """处理取消事件：显示当前完成进度"""
        done = msg.get("done", 0)
        total = msg.get("total", 1)
        self._status_lbl.setText(f"好哦,先停在这里 ({done}/{total}) ♪")
        self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        self._append_log(f"⏹ 已取消, {done}/{total} 已完成")
        return True

    def _on_stage_all_done(self, msg):
        """处理全部微调完成事件：输出汇总信息并清理状态"""
        done = msg.get("done", 0)
        elapsed = time.time() - self._train_t0 if self._train_t0 else 0

        conf_summary = ""
        for bvid, results in self._video_results.items():
            for r in results:
                cs, _ = format_confidence(r["confidence"])
                conf_summary += f"\n  {bvid} → {r['aid']}: {cs}"

        self._task_lbl.setText("✓ 全部唱完啦 ♪")
        self._task_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        self._task_detail.setText(f"{done}/{done}")
        self._status_lbl.setText(f"微调完成啦!♪ 像一首首新歌排好队等开唱 ({done} 任务 · {elapsed:.0f}s)")
        self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        self._progress.setValue(100)
        self._append_log(f"⚑ 批量微调全部完成: {done} 任务, 耗时 {elapsed:.0f}s")
        self._append_log(f"◧ 各算法最终置信度:{conf_summary}")
        self.main.set_finetune_status(f"✓ 批量微调完成 ({done}) ♪ 像一首首新歌排好队等开唱")
        self._last_finetune_count = done
        return True

    def _cleanup_training(self):
        """微调结束后的清理工作：刷新模型状态并触发完成回调"""
        super()._cleanup_training()
        try:
            self.main._refresh_model_status()
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        # 微调完成自动回调
        n = getattr(self, "_last_finetune_count", 0)
        if n > 0:
            try:
                self.main._on_training_completed("微调", n)
            except Exception as e:
                logger.debug("忽略异常: %s", e)
