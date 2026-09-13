"""Batch finetune dialog and worker coordination."""

import logging
import threading

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ui.helpers import FONT_SM
from ui.invoker import invoke
from ui.scrollable_frame import ScrollableFrame
from ui.theme import C

logger = logging.getLogger(__name__)


class TrainingBatchMixin:
    def _on_batch_finetune(self):
        """打开批量微调对话框：选择视频 + 算法，一键微调。"""
        from algorithms.registry import AlgorithmRegistry
        from algorithms.training.checkpoint_manager import CheckpointManager

        AlgorithmRegistry.initialize()
        algo_list = []
        for aid, algo, _adapter in AlgorithmRegistry.get_trainable_algorithms():
            if CheckpointManager(aid).has_checkpoint():
                algo_list.append({"algorithm_id": aid, "name": getattr(algo, "name", aid)})

        if not algo_list:
            QMessageBox.warning(self, "要注意哦…", "还没有训练好的算法可以微调呢…先训练一下,天依才能唱得更准哦 ♪")
            return

        videos = []
        try:
            for v in self.main.monitored_videos:
                bvid = v.get("bvid", "")
                title = v.get("title", bvid)
                if bvid:
                    videos.append({"bvid": bvid, "title": title[:40]})
        except Exception as e:
            logger.debug("忽略异常: %s", e)

        if not videos:
            QMessageBox.warning(self, "要注意哦…", "还没有监控中的视频呢…像点一首新歌那样添加一个,天依就来帮它微调 ♪")
            return

        dialog, ui = self._build_batch_dialog(algo_list, videos)

        def _ft_log(msg):
            # Use QTextCursor for O(1) append instead of O(n²) toPlainText concat
            cursor = ui["log_text"].textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(msg + "\n")
            sb = ui["log_text"].verticalScrollBar()
            if sb is not None:
                sb.setValue(sb.maximum())

        def _start_ft():
            selected_videos = [b for b, v in ui["video_vars"].items() if v.isChecked()]
            selected_algos = [a for a, v in ui["algo_vars"].items() if v.isChecked()]
            if not selected_videos:
                QMessageBox.warning(dialog, "要注意哦…", "至少要选一个视频哦,天依才能开始唱 ♪")
                return
            if not selected_algos:
                QMessageBox.warning(dialog, "要注意哦…", "至少要选一个算法哦 ♪")
                return

            epochs = max(1, ui["ft_epoch_spin"].value())
            batch = max(1, ui["ft_batch_spin"].value())
            total = len(selected_videos) * len(selected_algos)
            _ft_log(f"开始批量微调: {len(selected_videos)} 视频 × {len(selected_algos)} 算法 = {total} 任务")
            ui["start_btn"].setEnabled(False)

            threading.Thread(
                target=lambda: self._start_batch_worker(
                    selected_videos,
                    selected_algos,
                    epochs,
                    batch,
                    total,
                    dialog,
                    ui,
                    _ft_log,
                ),
                daemon=True,
            ).start()

        ui["start_btn"].clicked.connect(_start_ft)
        ui["cancel_btn"].clicked.connect(dialog.close)
        dialog.exec()

    def _build_batch_dialog(self, algo_list, videos):
        """构建批量微调对话框，返回 (dialog, ui_dict)"""
        dialog = QDialog(self)
        dialog.setWindowTitle("批量微调 ♪")
        dialog.resize(650, 500)
        dialog.setModal(True)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(10, 10, 10, 10)

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        dlg_layout.addWidget(main, 1)

        # 选择视频
        video_title = QLabel("选择视频 ♪")
        video_title.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        main_layout.addWidget(video_title)
        video_frame = QFrame(main)
        video_frame.setStyleSheet(f"background-color: {C['bg_elevated']}; border: 1px solid {C['border']};")
        vf_layout = QHBoxLayout(video_frame)
        vf_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(video_frame)
        v_sf = ScrollableFrame(video_frame, bg=C["bg_elevated"], height=100)
        vf_layout.addWidget(v_sf, 1)

        video_vars = {}
        for v in sorted(videos, key=lambda x: x["bvid"]):
            cb = QCheckBox(f"{v['title']}  ({v['bvid']})")
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {C['text_1']};")
            video_vars[v["bvid"]] = cb
            v_sf.addWidget(cb)

        # 选择算法
        algo_title = QLabel("选择算法 ♪")
        algo_title.setStyleSheet(f"color: {C['text_1']}; background: transparent; font: bold;")
        main_layout.addWidget(algo_title)
        algo_frame = QFrame(main)
        algo_frame.setStyleSheet(f"background-color: {C['bg_elevated']}; border: 1px solid {C['border']};")
        af_layout = QHBoxLayout(algo_frame)
        af_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(algo_frame)
        a_sf = ScrollableFrame(algo_frame, bg=C["bg_elevated"], height=100)
        af_layout.addWidget(a_sf, 1)

        algo_vars = {}
        for a in sorted(algo_list, key=lambda x: x["name"]):
            cb = QCheckBox(f"{a['name']}  ({a['algorithm_id']})")
            cb.setChecked(True)
            cb.setStyleSheet(f"color: {C['text_1']};")
            algo_vars[a["algorithm_id"]] = cb
            a_sf.addWidget(cb)

        # 参数行
        param_row = QWidget()
        param_row_layout = QHBoxLayout(param_row)
        param_row_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(param_row)

        epoch_label = QLabel("Epochs:")
        epoch_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        epoch_label.setFont(FONT_SM)
        param_row_layout.addWidget(epoch_label)
        ft_epoch_spin = QSpinBox()
        ft_epoch_spin.setRange(1, 100)
        ft_epoch_spin.setValue(5)
        param_row_layout.addWidget(ft_epoch_spin)
        param_row_layout.addSpacing(12)

        batch_label = QLabel("Batch:")
        batch_label.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        batch_label.setFont(FONT_SM)
        param_row_layout.addWidget(batch_label)
        ft_batch_spin = QSpinBox()
        ft_batch_spin.setRange(1, 512)
        ft_batch_spin.setValue(16)
        param_row_layout.addWidget(ft_batch_spin)
        param_row_layout.addStretch()

        ft_status = QLabel("天依准备好啦 ♪")
        ft_status.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        ft_status.setFont(FONT_SM)
        main_layout.addWidget(ft_status)
        ft_progress = QProgressBar()
        ft_progress.setMaximum(100)
        ft_progress.setValue(0)
        main_layout.addWidget(ft_progress)

        log_text = QPlainTextEdit()
        log_text.setReadOnly(True)
        log_text.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {C['bg_base']};
                color: {C['text_1']};
                font-family: Consolas;
                font-size: 9pt;
                border: 1px solid {C['border']};
            }}
        """)
        main_layout.addWidget(log_text, 1)

        btn_row = QWidget()
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(btn_row)
        start_btn = QPushButton("▶ 开始微调 ♪")
        btn_row_layout.addWidget(start_btn)
        cancel_btn = QPushButton("取消")
        btn_row_layout.addWidget(cancel_btn)
        btn_row_layout.addStretch()

        return dialog, {
            "video_vars": video_vars,
            "algo_vars": algo_vars,
            "ft_epoch_spin": ft_epoch_spin,
            "ft_batch_spin": ft_batch_spin,
            "ft_status": ft_status,
            "ft_progress": ft_progress,
            "log_text": log_text,
            "start_btn": start_btn,
            "cancel_btn": cancel_btn,
        }

    def _start_batch_worker(self, selected_videos, selected_algos, epochs, batch, total, dialog, ui, _ft_log):
        """后台工作线程：依次对每个视频的每个算法进行微调"""
        from algorithms.training.trainer import ModelTrainer

        trainer = ModelTrainer()
        done = 0
        self.main.set_finetune_status(f"◎ 天依开始批量微调啦 ♪ 0/{total}")
        for bvid in selected_videos:
            for aid in selected_algos:
                done += 1
                pct = int(done / total * 100)
                msg = f"[{done}/{total}] 微调 {aid} → {bvid}"
                invoke(lambda m=msg: ui["ft_status"].setText(f"天依在练习第 {done} 首呢 ♪ {m}"))
                invoke(lambda p=pct: ui["ft_progress"].setValue(p))
                invoke(lambda m=msg: _ft_log(m))
                invoke(lambda d=done, t=total: self.main.set_finetune_status(f"◎ 批量微调 {d}/{t} ♪"))
                try:
                    ver = trainer.finetune_for_video(
                        algo_id=aid,
                        bvid=bvid,
                        epochs=epochs,
                        batch_size=batch,
                    )
                    invoke(lambda a=aid, b=bvid, v=ver: _ft_log(f"  ✓ {a}@{b} → {v[:12]}"))
                except Exception as e:
                    invoke(lambda a=aid, b=bvid, e=e: _ft_log(f"  ✗ {a}@{b}: {e}"))
        self._batch_done_callback(dialog, ui, _ft_log, done)

    def _batch_done_callback(self, dialog, ui, _ft_log, done):
        """批量微调完成后的 UI 更新回调"""
        invoke(lambda: ui["ft_status"].setText(f"✓ 微调完成 ({done} 任务) ♪ 像一首首新歌排好队等开唱"))
        invoke(lambda: ui["ft_progress"].setValue(100))
        invoke(lambda: self.main.set_finetune_status(f"✓ 批量微调完成 ({done}) ♪ 像一首首新歌排好队等开唱"))
        invoke(lambda: ui["start_btn"].setEnabled(True))
        invoke(lambda: _ft_log("⚑ 批量微调全部完成"))
