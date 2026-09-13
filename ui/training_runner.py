"""Training worker and thread orchestration."""

from typing import Any, Dict, cast

from queue import Queue

from ui.invoker import invoke
from ui.theme import C
from ui.training_base import _TrainingPanelContract


class TrainingRunnerMixin(_TrainingPanelContract):
    def _start_train_thread(
        self, selected, is_incremental, lr, epochs, batch, parallel, batch_log, interval_val, interval_unit
    ):
        """启动训练线程（支持并行模式 + 可配置 batch 级日志间隔）"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        total = len(selected)
        algo_lr_factors: Dict[str, float] = {}
        completed_count = [0]
        batch_interval, batch_interval_mode = self._parse_batch_interval(interval_val, interval_unit)
        callback = self._make_train_callback(total, is_incremental, batch_log)
        train_one = self._make_train_one_algo(
            is_incremental,
            lr,
            epochs,
            batch,
            batch_log,
            batch_interval,
            batch_interval_mode,
            algo_lr_factors,
            completed_count,
            total,
            callback,
        )
        worker = self._make_train_worker(
            selected, parallel, completed_count, train_one, ThreadPoolExecutor, as_completed
        )
        self._launch_worker(worker)

    def _parse_batch_interval(self, interval_val, interval_unit):
        """解析 batch 日志间隔。"""
        try:
            val = float(interval_val)
            if interval_unit == "%":
                val = max(1, min(100, val))  # 限制 1%~100%
                return val / 100.0, "%"
            return max(1, int(val)), "count"
        except (ValueError, TypeError):
            return 0.1, "%"

    def _make_train_callback(self, total, is_incremental, batch_log):
        def _cb(payload: Dict):
            """训练回调 — 线程安全。batch_log 关闭时过滤 batch 消息。"""
            payload["_total_selected"] = total
            payload["_incremental"] = is_incremental

            if not batch_log and payload.get("stage") == "batch":
                return

            if self._skip_algo_flag[0]:
                payload["_adjustment"] = "⏭ 用户手动跳过"
                payload["early_stop"] = True
                cast(Queue[Any], self._train_queue).put(payload)
                return

            cast(Queue[Any], self._train_queue).put(payload)

        return _cb

    def _make_train_one_algo(
        self,
        is_incremental,
        lr,
        epochs,
        batch,
        batch_log,
        batch_interval,
        batch_interval_mode,
        algo_lr_factors,
        completed_count,
        total,
        callback,
    ):
        def _train_one_algo(aid):
            """在独立线程中训练单个算法。每个算法有自己的 trainer/control/monitor。"""
            if self._cancel_flag[0]:
                return aid, False

            try:
                from algorithms.training.trainer import ModelTrainer

                # 非增量模式：清除旧 checkpoint
                if not is_incremental:
                    from algorithms.training.checkpoint_manager import CheckpointManager

                    _ckpt = CheckpointManager(aid)
                    _n = _ckpt.delete_all()
                    if _n:
                        cast(Queue[Any], self._train_queue).put(
                            {"stage": "log", "text": f"  ✕ 已清除 {aid} 的 {_n} 个旧版本"}
                        )

                self._skip_algo_flag[0] = False
                if self._skip_btn:
                    invoke(lambda: self._skip_btn.setEnabled(False))
                    invoke(lambda: self._skip_btn.setEnabled(True))

                aid_factor = algo_lr_factors.get(aid, 1.0)
                effective_lr = lr * aid_factor
                control = {}
                # 注入 batch 日志间隔配置
                if batch_log and batch_interval is not None:
                    control["_batch_interval"] = batch_interval
                    control["_batch_interval_mode"] = batch_interval_mode
                trainer = ModelTrainer()
                sub = trainer.train_global(
                    [aid],
                    epochs=epochs,
                    batch_size=batch,
                    progress_cb=callback,
                    init_from_global=is_incremental,
                    lr=effective_lr,
                    control_dict=control,
                )
                completed_count[0] += 1
                return aid, bool(sub.get(aid))
            except Exception as e:
                cast(Queue[Any], self._train_queue).put(
                    {"stage": "error", "algo_id": aid, "current": completed_count[0], "total": total, "error": str(e)}
                )
                return aid, False

        return _train_one_algo

    def _make_train_worker(self, selected, parallel, completed_count, train_one, thread_pool_executor, as_completed):
        def _worker():
            """并行训练调度线程"""
            try:
                results = {}
                if parallel <= 1:
                    # 串行模式（保持原有行为）
                    for aid in selected:
                        if self._cancel_flag[0]:
                            cast(Queue[Any], self._train_queue).put(
                                {"stage": "cancelled", "remaining": selected[completed_count[0] :]}
                            )
                            break
                        ok, success = train_one(aid)
                        results[ok] = ok if success else ""
                else:
                    # 并行模式
                    self._append_log(f"⚡ 并行训练 ({parallel} 线程)")
                    with thread_pool_executor(max_workers=parallel) as pool:
                        futures = {pool.submit(train_one, aid): aid for aid in selected}
                        for f in as_completed(futures):
                            if self._cancel_flag[0]:
                                # 取消剩余任务
                                for remaining_f in futures:
                                    if not remaining_f.done():
                                        remaining_f.cancel()
                                remaining_aids = [futures[rf] for rf in futures if not rf.done()]
                                cast(Queue[Any], self._train_queue).put(
                                    {"stage": "cancelled", "remaining": remaining_aids}
                                )
                                break
                            aid, success = f.result()
                            results[aid] = aid if success else ""

                if not self._cancel_flag[0]:
                    cast(Queue[Any], self._train_queue).put({"stage": "all_done", "results": results})
            except Exception as e:
                cast(Queue[Any], self._train_queue).put({"stage": "fatal", "error": str(e)})

        return _worker

    def _on_cancel(self):
        """取消训练按钮回调"""
        self._cancel_flag[0] = True
        if self._cancel_btn:
            self._cancel_btn.setEnabled(False)
        if self._status_lbl:
            self._status_lbl.setText("好哦,天依正在收拾呢…等当前算法唱完这首歌就停 ♪")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        self._append_log("⏹ 用户请求取消训练")
        self._close_log_file()

    def _on_skip_algo(self):
        """跳过当前正在训练的算法，继续下一个。"""
        self._skip_algo_flag[0] = True
        if self._skip_btn:
            self._skip_btn.setEnabled(False)
        if self._status_lbl:
            self._status_lbl.setText("好哦,这次先跳过,天依接着唱下一首 ♪")
            self._status_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        self._append_log("⏭ 用户请求跳过当前算法")
