"""Training progress and epoch event handling."""

import logging
import time
from typing import List

from ui.helpers import format_confidence, load_algo_confidence, loss_to_confidence
from ui.theme import C

logger = logging.getLogger(__name__)


class TrainingEventsMixin:
    STAGE_HANDLERS = {
        "start": "_on_stage_start",
        "batch": "_on_stage_batch",
        "epoch": "_on_stage_epoch",
        "done": "_on_stage_done",
        "error": "_on_stage_error",
        "auto_adjust": "_on_stage_auto_adjust",
        "cancelled": "_on_stage_cancelled",
        "all_done": "_on_stage_all_done",
        "fatal": "_on_stage_fatal",
    }

    def _handle_stage(self, msg) -> bool:
        """根据消息 stage 分发给对应的事件处理器"""
        stage = msg.get("stage")
        handler_name = self.STAGE_HANDLERS.get(stage)
        if handler_name:
            return getattr(self, handler_name)(msg)
        return False

    def _on_stage_start(self, msg):
        """处理训练开始事件"""
        aid = msg.get("algo_id", "?")
        cur = msg.get("current", 0)
        tot = msg.get("total", 1)
        self._current_aid = aid
        self._total_algos = tot
        self._algo_start_time = time.time()
        self._epoch_times: List[float] = []  # 当前算法各 epoch 耗时（秒）
        self._last_epoch_elapsed = 0.0
        if self._status_lbl:
            self._status_lbl.setText(f"[{cur}/{tot}] 天依在训练 {aid} 呢…♪")
            self._status_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        self._append_log(f"── [{cur}/{tot}] 开始训练 {aid} ──")
        self._update_algo_row(aid, status="▶ 训练中", status_color=C["accent"])
        self._monitor.reset()
        # 状态栏 + 进度条动画
        self._safe_sb("algo", f"◉ [{cur}/{tot}] {aid}", color=C["accent"])
        if self._progress:
            self._progress.setValue(0)
            self._progress.setMinimum(0)
            self._progress.setMaximum(100)

    def _on_stage_batch(self, msg):
        """处理 batch 完成事件 — 更新状态栏并写入详细日志"""
        aid = msg.get("algo_id", "?")
        b = msg.get("batch", 0)
        tot_b = msg.get("total_batches", 1)
        avg_loss = msg.get("avg_loss", 0)
        batch_loss = msg.get("batch_loss", 0)
        try:
            self.main._sb("status", f"⟳ {aid} batch {b}/{tot_b} loss={avg_loss:.4f} ♪", color=C["text_2"])
        except Exception:
            pass
        # 详细日志：batch 级损失写入日志面板和文件
        pct = b / max(tot_b, 1) * 100
        self._append_log(
            f"  ◧ {aid} batch {b}/{tot_b} ({pct:.0f}%) | batch_loss={batch_loss:.6f} | avg_loss={avg_loss:.6f}"
        )
        return False

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        """格式化时长为可读字符串"""
        if seconds < 0:
            return "--"
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            m, s = divmod(int(seconds), 60)
            return f"{m}m{s}s" if s > 0 else f"{m}m"
        h, r = divmod(int(seconds), 3600)
        m = r // 60
        return f"{h}h{m}m" if m > 0 else f"{h}h"

    def _on_stage_epoch(self, msg):
        """处理每个 epoch 完成事件 — 更新图表、进度、日志、EMA 加权 ETA"""
        aid = msg.get("algo_id", "?")
        ep = msg.get("epoch", 0)
        eps = msg.get("epochs", 1)
        tloss = msg.get("train_loss", 0.0)
        vloss = msg.get("val_loss", -1.0)
        elapsed = msg.get("elapsed_s", 0.0)

        conf = loss_to_confidence(vloss) if vloss >= 0 else 0.0
        conf_str, conf_color = format_confidence(conf)

        if ep == 1 or ep % 5 == 0 or ep == eps:
            self._update_algo_row(aid, conf=conf_str, conf_color=conf_color)

        pct = min(100, int((ep / max(1, eps)) * 100))
        if self._progress:
            self._progress.setValue(pct)
        vtxt = f"  val={vloss:.4f}" if vloss >= 0 else ""

        # ── EMA 加权 ETA：最近 epoch 权重更高 ──
        epoch_duration = max(0, elapsed - self._last_epoch_elapsed)
        self._last_epoch_elapsed = elapsed
        if epoch_duration > 0 and epoch_duration < 3600:  # 排除异常值
            self._epoch_times.append(epoch_duration)
            if len(self._epoch_times) > 10:
                self._epoch_times = self._epoch_times[-10:]

        total_eta_str = ""
        if self._epoch_times:
            # EMA：衰减因子 0.7，最近 epoch 权重指数级更高
            alpha = 0.7
            recent_weights = [alpha ** (len(self._epoch_times) - 1 - i) for i in range(len(self._epoch_times))]
            weight_sum = sum(recent_weights)
            ema_epoch = sum(t * w for t, w in zip(self._epoch_times, recent_weights)) / max(weight_sum, 1e-10)

            # 本算法剩余时间
            algo_remaining = ema_epoch * (eps - ep)
            algo_eta = self._fmt_duration(algo_remaining)

            # 总训练剩余时间 = 本算法剩余 + 未开始算法预估
            cur = msg.get("current", 0)
            tot = msg.get("total", 1)
            remaining_algos = tot - cur
            if remaining_algos > 0 and hasattr(self, "_algo_durations") and self._algo_durations:
                avg_algo_time = sum(self._algo_durations) / len(self._algo_durations)
                # 已完成算法数较少时，用本算法当前速率补充
                if len(self._algo_durations) < 2:
                    avg_algo_time = max(avg_algo_time, ema_epoch * eps * 0.8)
                other_remaining = avg_algo_time * (remaining_algos - 1)  # -1 因为当前算法已在算
            else:
                # 无历史数据：用本算法速率外推
                other_remaining = ema_epoch * eps * max(0, remaining_algos - 1)

            total_remaining = algo_remaining + other_remaining
            total_eta_str = f"  ⏱本{algo_eta} 总{self._fmt_duration(total_remaining)}"

        if self._status_lbl:
            self._status_lbl.setText(
                f"♪ {aid} 第 {ep}/{eps} 轮,天依越唱越准啦  train={tloss:.4f}{vtxt}  {conf_str}  {elapsed:.0f}s{total_eta_str}"
            )
            self._status_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")

        # 主窗口状态栏（含 ETA）
        cur = msg.get("current", 0)
        tot = msg.get("total", 1)
        status_text = f"◉ [{cur}/{tot}] {aid} 第{ep}/{eps}轮  {elapsed:.0f}s ♪"
        if total_eta_str:
            # 提取总 ETA 部分
            parts = total_eta_str.split("总")
            if len(parts) > 1:
                status_text += f"  ⇨{parts[1]}"
        self._safe_sb("algo", status_text, color=C["accent"])
        self._safe_sb("status", f"训练中…天依越唱越准啦 ♪ loss={tloss:.4f}", color=C["text_2"])

        self._monitor.update(ep, tloss, vloss if vloss >= 0 else -1)
        self._refresh_monitor()

        adj = msg.get("_adjustment", "")
        if adj:
            self._append_log(f"  {adj}")

        self._loss_history.append(
            {
                "algo": aid,
                "epoch": ep,
                "train_loss": tloss,
                "val_loss": vloss,
            }
        )
        self._update_chart()
        self._append_log(
            f"  epoch {ep:>3}/{eps}  |  "
            f"train_loss={tloss:.6f}  |  "
            f"{f'val_loss={vloss:.6f}' if vloss >= 0 else 'val_loss=N/A'}  |  "
            f"confidence={conf_str}  |  "
            f"{elapsed:.1f}s"
        )

    def _on_stage_done(self, msg):
        """处理单个算法训练完成事件"""
        total_sel = msg.get("_total_selected", 1)
        aid = msg.get("algo_id", "?")
        cur = msg.get("current", 0)
        ver = msg.get("version", "")
        algo_elapsed = time.time() - getattr(self, "_algo_start_time", time.time())

        # 记录算法耗时用于跨算法 ETA
        if not hasattr(self, "_algo_durations"):
            self._algo_durations = []
        self._algo_durations.append(algo_elapsed)

        if self._status_lbl:
            self._status_lbl.setText(f"✓ {aid} 唱好啦 ♪ → {ver} ({cur}/{total_sel})  {algo_elapsed:.0f}s")
            self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        if self._progress:
            self._progress.setValue(int(cur / max(1, total_sel) * 100))

        # 计算总体 ETA
        remaining = total_sel - cur
        total_eta = ""
        if remaining > 0 and self._algo_durations:
            avg_dur = sum(self._algo_durations) / len(self._algo_durations)
            total_eta = f"  ⇨剩余≈{self._fmt_duration(avg_dur * remaining)}"

        # 主窗口状态栏
        self._safe_sb(
            "algo", f"◉ ✓ [{cur}/{total_sel}] {aid} 唱好啦 ♪  {algo_elapsed:.0f}s{total_eta}", color=C["success"]
        )

        # 从 checkpoint 读取 val_loss 和置信度
        from algorithms.training.checkpoint_manager import CheckpointManager

        _val_loss = -1.0
        try:
            _ckpt = CheckpointManager(aid)
            _versions = _ckpt.list_versions()
            if _versions:
                _val_loss = _versions[0].get("val_loss", -1.0)
        except Exception as e:
            logger.debug("忽略异常: %s", e)
        conf = loss_to_confidence(_val_loss) if _val_loss >= 0 else load_algo_confidence(aid)
        conf_str, conf_color = format_confidence(conf)
        self._algo_confidence[aid] = conf
        if _val_loss >= 0:
            self._append_log(f"  ✓ {aid} → {ver}  置信度={conf_str}  val_loss={_val_loss:.4f}")
        else:
            self._append_log(f"  ✓ {aid} → {ver}")
        self._update_algo_row(
            aid,
            status=f"✓ {ver[:10]}",
            status_color=C["success"],
            conf=conf_str,
            conf_color=conf_color,
            ver=f"v{self._algo_meta.get(aid, {}).get('version_count', 0) + 1}",
        )

    def _on_stage_error(self, msg):
        """处理训练错误事件"""
        aid = msg.get("algo_id", "?")
        err = msg.get("error", "")
        if self._status_lbl:
            self._status_lbl.setText(f"呜…{aid} 没学会呢,天依不会放弃的,看看日志再试一次哦 ♪")
            self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
        self._append_log(f"✗ {aid} 训练失败: {err}")
        self._update_algo_row(aid, status="✗ 失败", status_color=C["danger"])
        self._safe_sb("algo", f"◉ ✗ {aid} 没学会呢…天依会再试试的 ♪", color=C["danger"])

    def _on_stage_auto_adjust(self, msg):
        """处理自动调整事件"""
        message = msg.get("message", "")
        self._append_log(f"  ⚙ 自动调整: {message}")
        if self._status_lbl:
            self._status_lbl.setText(f"⚡ {message} ♪")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")

    def _on_stage_cancelled(self, msg):
        """处理取消训练事件"""
        rem = msg.get("remaining", [])
        if self._status_lbl:
            self._status_lbl.setText(f"好哦,先停在这里,还剩 {len(rem)} 个下次再唱 ♪")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        self._append_log(f"⏹ 已取消, 剩余 {len(rem)} 个算法")
        self._safe_sb("algo", f"⏹ 训练已取消 (剩余{len(rem)}个) ♪", color=C["warning"])
        return True

    def _on_stage_all_done(self, msg):
        """处理所有算法训练完成事件"""
        results = msg.get("results", {})
        self._last_training_results = results
        ok = sum(1 for v in results.values() if v)
        bad = sum(1 for v in results.values() if not v)
        elapsed = time.time() - self._train_t0 if self._train_t0 else 0

        conf_summary = ""
        for aid, ver in results.items():
            if not ver:
                continue
            conf = load_algo_confidence(aid)
            self._algo_confidence[aid] = conf
            conf_str, _ = format_confidence(conf)
            conf_summary += f"  {aid}: {conf_str}"

        if self._status_lbl:
            self._status_lbl.setText(f"训练完成啦!♪ 天依的歌声又准了一点呢~  ✓ {ok}  ✗ {bad}  · {elapsed:.0f}s")
            self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
        if self._progress:
            self._progress.setValue(100)
        self._append_log(f"⚑ 训练全部完成: {ok} 成功, {bad} 失败, 耗时 {elapsed:.0f}s")
        self._append_log(f"◧ 各算法最终置信度:{conf_summary}")
        # 主窗口状态栏
        self._safe_sb("algo", f"◉ ✓ 训练完成啦 ({ok}成功 {bad}失败) ♪  {elapsed:.0f}s", color=C["success"])
        return True

    def _on_stage_fatal(self, msg):
        """处理训练进程致命错误事件"""
        err = msg.get("error", "")
        if self._status_lbl:
            self._status_lbl.setText("呜…训练出了点小状况,天依不会放弃的,看看日志再试一次哦 ♪")
            self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
        self._append_log(f"✹ 训练进程异常: {err}")
        return True

    def _cleanup_training(self):
        """训练清理：关闭日志、刷新列表、通知完成"""
        self._close_log_file()
        super()._cleanup_training()
        self._refresh_algo_list()
        try:
            self.main._refresh_model_status()
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        # 恢复窗口标题和状态栏
        try:
            if self._saved_title:
                self.window().setWindowTitle(self._saved_title)
        except Exception:
            pass
        self._safe_sb("status", "天依准备好啦 ♪", color=C["text_3"])

        # 训练自动回调：通知 + 重新预测
        trained = getattr(self, "_last_training_results", {})
        ok = [aid for aid, v in trained.items() if v]
        if ok:
            detail = ", ".join(ok[:6])
            if len(ok) > 6:
                detail += f" …等{len(ok)}个"
            try:
                self.main._on_training_completed("训练", len(ok), detail)
            except Exception as e:
                logger.debug("忽略异常: %s", e)
