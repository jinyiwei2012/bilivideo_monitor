"""Finetune configuration, worker orchestration, and automatic adjustment logic."""

import logging
from typing import Dict

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from ui.helpers import loss_to_confidence, project_path
from ui.theme import C
from ui.training_base import TrainingMonitor

logger = logging.getLogger(__name__)


class FinetuneJobsMixin:
    """Provide finetune job setup and worker-thread orchestration."""

    def _on_start(self):
        """开始微调：校验选择、确认设置、启动后台训练线程"""
        if self._training:
            return
        config = self._build_finetune_config()
        if config is None:
            return
        selected_videos, selected_algos, epochs, batch, total, mode = config
        self._prepare_training()
        self._video_results.clear()
        self._auto_monitors.clear()
        self._auto_control = {}
        self._last_monitor_status = ""
        self._last_monitor_log_epoch = 0
        mode_label = "重新训练" if mode == "retrain" else "增量微调"
        data_label = "仅新数据" if self._use_new_data_only else "全部数据"
        self._append_log(
            f"♬ 开始{mode_label}（{data_label}）: {len(selected_videos)} 视频 × {len(selected_algos)} 算法, "
            f"epoch={epochs}, batch={batch}"
        )
        self._task_lbl.setText(f"天依正在{mode_label}呢…♪")
        self._task_detail.setText(f"0/{total}")
        self._status_lbl.setText("天依在准备任务呢…♪")
        self._status_lbl.setStyleSheet(f"color: {C['text_2']};")

        def _cb(payload: Dict):
            self._handle_finetune_progress(payload, mode)

        self._start_finetune_worker(selected_videos, selected_algos, epochs, batch, total, mode, _cb)

    def _build_finetune_config(self):
        """校验选择、确认设置、检查增量数据范围，返回训练配置或 None"""
        selected_videos = [b for b, v in self._video_vars.items() if v.isChecked()]
        selected_algos = [a for a, v in self._algo_vars.items() if v.isChecked()]
        if not selected_videos:
            QMessageBox.warning(self, "要注意哦…", "至少要选一个视频哦,天依才能开始唱 ♪")
            return None
        if not selected_algos:
            QMessageBox.warning(self, "要注意哦…", "至少要选一个算法哦 ♪")
            return None

        epochs = max(1, self._epoch_spin.value())
        batch = max(1, self._batch_spin.value())
        total = len(selected_videos) * len(selected_algos)
        mode = "retrain" if self._mode_retrain.isChecked() else "incremental"

        if mode == "retrain":
            reply = QMessageBox.question(
                self,
                "要重新训练吗 ♪",
                "会把所选算法在所有选定视频上的微调版本都删掉,版本号也会重置哦,\n"
                "data/<bvid>/model/ 里的对应文件也会一起消失…\n"
                "确定要继续吗?删掉就像从歌单里划掉一首歌,唱不回来了哦…",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return None

        reply = QMessageBox.question(
            self,
            "要开始微调吗 ♪",
            f"天依要开始微调啦 ♪\n"
            f"模式: {'重新训练' if mode == 'retrain' else '增量微调'}\n"
            f"视频: {len(selected_videos)} 个\n算法: {len(selected_algos)} 个\n"
            f"总任务: {total}\nepoch={epochs}  batch={batch}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return None

        self._use_new_data_only = False
        if mode == "incremental":
            has_prev = False
            try:
                from algorithms.training.checkpoint_manager import CheckpointManager

                for _bv in selected_videos:
                    for _al in selected_algos:
                        _cm = CheckpointManager(_al, bvid=_bv)
                        if _cm.has_checkpoint():
                            has_prev = True
                            break
                    if has_prev:
                        break
            except Exception as e:
                logger.debug("忽略异常: %s", e)
            if has_prev:
                reply = QMessageBox.question(
                    self,
                    "数据范围怎么选呀 ♪",
                    "已经有微调好的 checkpoint 啦,训练数据范围要选哪种呢?\n\n"
                    "「是」 = 只唱上次练习截止后的新歌(续训,速度快)\n"
                    "「否」 = 把这首视频的全部历史数据都唱一遍(更充分)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                self._use_new_data_only = reply == QMessageBox.StandardButton.Yes

        return (selected_videos, selected_algos, epochs, batch, total, mode)

    def _handle_finetune_progress(self, payload: Dict, mode: str):
        """训练回调 — 运行在工作线程中，负责通信 + 自动调整"""
        payload["_mode"] = mode
        payload["_control"] = dict(self._auto_control) if self._auto_control else {}

        if self._skip_algo_flag[0]:
            self._auto_control["early_stop"] = True
            self._auto_control["_force_early_stop"] = True
            payload["_adjustment"] = "⏭ 用户手动跳过"
            self._train_queue.put(payload)
            return

        if payload.get("stage") == "epoch":
            self._handle_finetune_epoch(payload)

        self._train_queue.put(payload)

    def _handle_finetune_epoch(self, payload):
        aid = payload.get("algo_id", "")
        bvid_ = payload.get("bvid", "") or self._current_bvid
        key = f"{aid}@{bvid_}"
        if key not in self._auto_monitors:
            self._auto_monitors[key] = TrainingMonitor()
        mon = self._auto_monitors[key]
        vloss = payload.get("val_loss", -1.0)
        mon.update(payload.get("epoch", 0), payload.get("train_loss", 0.0), vloss if vloss >= 0 else -1)
        if mon.level in ("warning", "danger") and self._auto_control is not None:
            self._apply_finetune_adjustment(payload, aid, mon)

    def _update_finetune_lr(self, aid, scale):
        self._auto_control["lr_scale"] = scale
        self._algo_lr_factors[aid] = max(0.01, min(10.0, self._algo_lr_factors.get(aid, 1.0) * scale))

    def _apply_finetune_adjustment(self, payload, aid, mon):
        status = mon.status
        if "nan" in status.lower():
            self._auto_control["early_stop"] = True
            payload["_adjustment"] = "⚙ NaN 检测 — 提前停止"
        elif "爆炸" in status:
            self._apply_finetune_instability(payload, aid, mon, "explosion", "⚙ Loss 爆炸 — ")
        elif "严重过拟合" in status:
            self._apply_severe_overfitting(payload, mon)
        elif "震荡" in status:
            self._apply_finetune_instability(payload, aid, mon, "oscillation", "⚙ Loss 震荡 — ")
        elif "过拟合" in status:
            self._apply_finetune_overfitting(payload, aid, mon)
        elif "欠拟合" in status or "下降过慢" in status:
            scale = mon.compute_lr_scale("underfitting")
            self._update_finetune_lr(aid, scale)
            payload["_adjustment"] = f"⚙ 欠拟合 — LR×{scale:.2f} (累计×{self._algo_lr_factors[aid]:.2f})"
        elif "不再收敛" in status:
            self._auto_control["early_stop"] = True
            payload["_adjustment"] = "⚙ 不再收敛 — 提前停止"

    def _apply_finetune_instability(self, payload, aid, mon, reason, prefix):
        scale = mon.compute_lr_scale(reason)
        gc = mon.compute_grad_clip(reason)
        self._update_finetune_lr(aid, scale)
        if gc > 0:
            self._auto_control["grad_clip"] = gc
        parts = [f"LR×{scale:.2f}"]
        if gc > 0:
            parts.append(f"梯度裁剪={gc:.2f}")
        parts.append(f"累计×{self._algo_lr_factors[aid]:.2f}")
        payload["_adjustment"] = f"{prefix}{', '.join(parts)}"

    def _apply_severe_overfitting(self, payload, mon):
        self._auto_control["early_stop"] = True
        wd = mon.compute_weight_decay()
        if wd > 0:
            self._auto_control["weight_decay"] = wd
        payload["_adjustment"] = "⚙ 严重过拟合 — 提前停止" + (f", weight_decay={wd:.4f}" if wd > 0 else "")

    def _apply_finetune_overfitting(self, payload, aid, mon):
        scale = mon.compute_lr_scale("overfitting")
        wd = mon.compute_weight_decay()
        self._update_finetune_lr(aid, scale)
        if wd > 0:
            self._auto_control["weight_decay"] = wd
        parts = [f"LR×{scale:.2f}"]
        if wd > 0:
            parts.append(f"weight_decay={wd:.4f}")
        parts.append(f"累计×{self._algo_lr_factors[aid]:.2f}")
        payload["_adjustment"] = f"⚙ 过拟合 — {', '.join(parts)}"

    def _start_finetune_worker(self, selected_videos, selected_algos, epochs, batch, total, mode, progress_cb):
        """创建后台工作线程并启动，遍历选定视频和算法逐一执行微调"""
        self._launch_worker(
            self._make_finetune_worker(selected_videos, selected_algos, epochs, batch, total, mode, progress_cb)
        )

    def _make_finetune_worker(self, selected_videos, selected_algos, epochs, batch, total, mode, progress_cb):
        def _worker():
            from algorithms.training.trainer import ModelTrainer
            from algorithms.training.checkpoint_manager import CheckpointManager
            import os as _os

            trainer = ModelTrainer()
            _data_root = project_path("data")
            done = 0
            for bvid in selected_videos:
                if self._cancel_flag[0]:
                    self._train_queue.put({"stage": "cancelled", "done": done, "total": total})
                    return
                for aid in selected_algos:
                    if self._cancel_flag[0]:
                        self._train_queue.put({"stage": "cancelled", "done": done, "total": total})
                        return
                    done += 1
                    self._run_finetune_task(
                        trainer,
                        CheckpointManager,
                        _os,
                        _data_root,
                        aid,
                        bvid,
                        epochs,
                        batch,
                        done,
                        total,
                        mode,
                        progress_cb,
                    )
            self._train_queue.put({"stage": "all_done", "done": done, "total": total})

        return _worker

    def _run_finetune_task(
        self,
        trainer,
        checkpoint_manager,
        os_module,
        data_root,
        aid,
        bvid,
        epochs,
        batch,
        done,
        total,
        mode,
        progress_cb,
    ):
        if mode == "retrain":
            self._clear_finetune_task(checkpoint_manager, os_module, data_root, aid, bvid)
        self._skip_algo_flag[0] = False
        QTimer.singleShot(0, lambda: self._skip_btn.setEnabled(True))
        self._train_queue.put({"stage": "start", "done": done, "total": total, "aid": aid, "bvid": bvid})
        self._auto_control = {}
        self._algo_lr_factors[aid] = 1.0
        effective_lr = (self._previous_finetune_lr(checkpoint_manager, aid, bvid) or 0.001) * self._algo_lr_factors.get(
            aid, 1.0
        )
        try:
            ver = trainer.finetune_for_video(
                algo_id=aid,
                bvid=bvid,
                epochs=epochs,
                batch_size=batch,
                progress_cb=progress_cb,
                control_dict=self._auto_control,
                lr=effective_lr,
                use_new_data_only=self._use_new_data_only,
            )
            versions = checkpoint_manager(aid, bvid=bvid).list_versions()
            val_loss = versions[0].get("val_loss", -1.0) if versions else -1.0
            self._train_queue.put(
                {
                    "stage": "done",
                    "done": done,
                    "total": total,
                    "aid": aid,
                    "bvid": bvid,
                    "version": ver[:12],
                    "confidence": loss_to_confidence(val_loss),
                    "val_loss": val_loss,
                }
            )
        except Exception as e:
            self._train_queue.put(
                {"stage": "error", "done": done, "total": total, "aid": aid, "bvid": bvid, "error": str(e)}
            )

    def _clear_finetune_task(self, checkpoint_manager, os_module, data_root, aid, bvid):
        deleted = checkpoint_manager(aid, bvid=bvid).delete_all()
        model_path = os_module.path.join(data_root, bvid, "model", f"{aid}.pt")
        try:
            if os_module.path.exists(model_path):
                os_module.remove(model_path)
        except Exception as e:
            logger.debug("忽略异常: %s", e)
        if deleted:
            self._train_queue.put({"stage": "log", "text": f"  ✕ 已清除 {aid}@{bvid} 的 {deleted} 个旧版本"})

    def _previous_finetune_lr(self, checkpoint_manager, aid, bvid):
        try:
            prev_versions = checkpoint_manager(aid, bvid=bvid).list_versions()
            if prev_versions:
                for version in prev_versions:
                    if version["active"]:
                        learning_rate = version.get("learning_rate", -1.0)
                        return learning_rate if learning_rate > 0 else None
        except Exception as e:
            logger.debug("忽略异常: %s", e)
        return None

    def _on_cancel(self):
        """取消当前正在运行的全部微调任务"""
        self._cancel_flag[0] = True
        if self._cancel_btn:
            self._cancel_btn.setEnabled(False)
        self._append_log("⏹ 用户请求取消")
        self.main.set_finetune_status("⏹ 好哦,微调先停一停,天依随时可以继续 ♪", color=C["warning"])

    def _on_skip_algo(self):
        """跳过当前正在微调的（视频,算法）对，继续下一个。"""
        self._skip_algo_flag[0] = True
        if self._skip_btn:
            self._skip_btn.setEnabled(False)
        self._append_log("⏭ 用户请求跳过当前任务")
