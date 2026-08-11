"""通用异步队列轮询 mixin —— 训练/长任务的线程 + Queue + QTimer 轮询机制。

从 BaseTrainingPanel 中提取的通用机制, 供训练面板与设置面板共同复用,
消除两套重复的线程/轮询/进度条脉冲动画实现。

用法:
    class MyWidget(AsyncQueueRunner, QWidget):
        def _handle_stage(self, msg) -> bool:
            \"\"\"处理单条消息。返回 True 表示任务全部结束。\"\"\"
            ...
        def _cleanup_run(self):
            \"\"\"任务结束后恢复 UI。\"\"\"
            ...
        def start(self):
            def _worker():
                self._run_queue.put({"stage": "done"})
            self._launch_worker(_worker)
"""
import queue
import threading
import time

from PyQt6.QtCore import QTimer


class AsyncQueueRunner:
    """线程 + 队列 + QTimer 轮询的通用载体。

    约定属性 (子类无需显式初始化):
        _train_queue: 消息队列; None 表示无进行中的任务
        _train_thread: 后台工作线程
        _train_t0: 任务启动时间戳
        _last_msg_time: 最后一条消息时间 (脉冲动画判定用)
        _progress / _tr_progress: 进度条 (脉冲动画用, 自动识别前缀)
    """

    def _launch_worker(self, worker_func):
        """创建队列并启动工作线程 + 轮询循环。"""
        self._train_t0 = time.time()
        self._train_queue = queue.Queue()
        self._train_thread = threading.Thread(target=worker_func, daemon=True)
        self._train_thread.start()
        self._last_msg_time = time.time()  # 跟踪最后一条消息的时间
        QTimer.singleShot(150, self._poll_progress)

    def _poll_progress(self):
        """主轮询循环：从队列取消息 → _handle_stage → 完成时 _cleanup_training。

        超过 2 秒无消息时, 进度条切换为脉冲动画避免用户以为卡死。
        """
        if self._train_queue is None:
            return
        done_all = False
        had_msg = False
        try:
            while True:
                msg = self._train_queue.get_nowait()
                if self._handle_stage(msg):
                    done_all = True
                had_msg = True
                self._last_msg_time = time.time()
        except queue.Empty:
            pass
        # 长时间无消息 → 脉冲动画提示仍在运行
        progress = getattr(self, "_progress", None) or getattr(self, "_tr_progress", None)
        if progress is not None and not done_all:
            idle_s = time.time() - self._last_msg_time
            if idle_s > 2:
                if progress.minimum() == 0 and progress.maximum() == 0:
                    pass  # already indeterminate
                else:
                    # 切换为脉冲模式（QProgressBar indeterminate = minimum == maximum == 0）
                    progress.setMinimum(0)
                    progress.setMaximum(0)
            elif had_msg and progress.minimum() == 0 and progress.maximum() == 0:
                progress.setMinimum(0)
                progress.setMaximum(100)
        if done_all:
            self._cleanup_training()
        else:
            QTimer.singleShot(200, self._poll_progress)

    def _handle_stage(self, msg) -> bool:
        """处理单条进度消息。返回 True 表示任务全部结束。子类必须实现。"""
        raise NotImplementedError

    def _cleanup_training(self):
        """任务结束后恢复 UI。子类必须实现 (或 super() 扩展)。"""
        raise NotImplementedError
