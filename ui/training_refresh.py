"""Device, data, and algorithm-list refresh behavior."""

import logging
import threading
from typing import Any, Dict, List, cast

from PyQt6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QLayout

from ui.helpers import FONT, FONT_MONO, FONT_SM, format_confidence, load_algo_confidence
from ui.invoker import invoke
from ui.theme import C
from ui.training_base import _TrainingPanelContract

logger = logging.getLogger(__name__)


class TrainingRefreshMixin(_TrainingPanelContract):
    _algo_frame: QFrame
    _algo_count_lbl: QLabel
    _check_vars: Dict[str, QCheckBox]
    _algo_meta: Dict[str, Dict[str, Any]]
    _algo_row_refs: Dict[str, List[QLabel]]

    def _safe_sb(self, key, text, color=None):
        """线程安全的状态栏更新 — 统一 try/except，消除 11 处重复模板"""
        try:
            self.main._sb(key, text, color=color)
        except Exception:
            pass

    def on_show(self):
        """此面板被切换到前台时调用"""
        self._refresh_device()
        self._refresh_data_size()
        self._refresh_algo_list()

    def _refresh_all(self):
        """刷新所有数据：设备、数据规模、算法列表"""
        self._refresh_device()
        self._refresh_data_size()
        self._refresh_algo_list()

    def _refresh_device(self):
        """刷新训练设备信息显示"""
        try:
            from algorithms.training.device import get_device_info, is_torch_available, force_cpu

            force_cpu(self._force_cpu_cb.isChecked())
            info = get_device_info()
            if not is_torch_available():
                self._device_lbl.setText("呜…还没安装 torch 呢,装好天依才能唱歌哦 ♪")
                self._device_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
            elif info.get("is_gpu"):
                mem = info.get("total_memory_gb", 0)
                self._device_lbl.setText(f"✓ {info['name']} ({mem:.1f} GB)")
                self._device_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
            else:
                self._device_lbl.setText(f"▮ {info['name']}")
                self._device_lbl.setStyleSheet(f"color: {C['warning']}; background: transparent;")
        except Exception as e:
            logger.debug("刷新设备信息失败: %s", e)
            self._device_lbl.setText("呜…设备检测失败啦,请稍后再试哦 ♪")
            self._device_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")

    def _on_force_cpu(self):
        """强制 CPU 切换时重新检测设备"""
        self._refresh_device()

    def _refresh_data_size(self):
        """刷新数据规模估算信息（异步线程）"""
        self._data_lbl.setText("天依在估算数据规模呢…♪")
        self._data_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")

        def _worker():
            try:
                from algorithms.training.trainer import ModelTrainer

                info = ModelTrainer().estimate_data_size()
                total = info.get("total_videos", 0)
                valid = info.get("valid_videos", 0)
                samples = info.get("total_samples", 0)
                eta = info.get("estimated_time_s", 0)
                txt = f"天依估算好啦 ♪ {total} 视频 · {valid} 有效 · {samples:,} 样本 · 约 {eta / 60:.1f} min/algo"
                invoke(lambda: self._data_lbl.setText(txt))
                invoke(lambda: self._data_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;"))
            except Exception as e:
                logger.debug("估算数据规模失败: %s", e)
                invoke(lambda: self._data_lbl.setText("呜…数据估算失败啦,请稍后再试哦 ♪"))
                invoke(lambda: self._data_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;"))

        threading.Thread(target=_worker, daemon=True).start()

    def _discover_algorithms(self) -> List[Dict]:
        """扫描有 build_model 的算法"""
        from algorithms.registry import AlgorithmRegistry

        algorithms: List[Dict[str, Any]] = AlgorithmRegistry.get_trainable_info()
        return algorithms

    def _refresh_algo_list(self):
        """刷新算法列表，显示每个算法的状态、置信度和版本"""
        # Clear existing rows
        layout = self._algo_frame.layout()
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                if item is None:
                    continue
                w = item.widget()
                if w is not None:
                    w.deleteLater()
        self._check_vars.clear()
        self._algo_meta.clear()
        self._algo_row_refs.clear()

        try:
            algos = self._discover_algorithms()
        except Exception as e:
            logger.error("加载可训练算法列表失败: %s", e)
            err_lbl = QLabel("呜…算法列表加载失败啦,请稍后再试哦 ♪")
            err_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
            err_lbl.setFont(FONT)
            cast(QLayout, self._algo_frame.layout()).addWidget(err_lbl)
            return

        trained = sum(1 for a in algos if a["has_ckpt"])
        self._algo_count_lbl.setText(f"天依数了数 ♪ {len(algos)} 算法 · 已训练 {trained}")

        for a in algos:
            aid = a["algorithm_id"]
            self._algo_meta[aid] = a

            row = QFrame(self._algo_frame)
            row.setStyleSheet(f"background-color: {C['bg_surface']}; border: 1px solid {C['border_sub']};")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 1, 4, 1)
            row_layout.setSpacing(2)
            cast(QLayout, self._algo_frame.layout()).addWidget(row)

            cb = QCheckBox("")
            cb.setChecked(not a["has_ckpt"])
            self._check_vars[aid] = cb
            row_layout.addWidget(cb)

            name_lbl = QLabel(a["name"])
            name_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
            name_lbl.setFont(FONT)
            name_lbl.setFixedWidth(130)
            row_layout.addWidget(name_lbl)

            id_lbl = QLabel(aid)
            id_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            id_lbl.setFont(FONT_MONO)
            id_lbl.setFixedWidth(100)
            row_layout.addWidget(id_lbl)

            if a["has_ckpt"]:
                st = f"✓ {a['active_version'][:10]}"
                sf = C["success"]
            else:
                st = "□ 还没训练呢…♪"
                sf = C["text_3"]
            status_lbl = QLabel(st)
            status_lbl.setStyleSheet(f"color: {sf}; background: transparent;")
            status_lbl.setFont(FONT_SM)
            status_lbl.setFixedWidth(90)
            row_layout.addWidget(status_lbl)

            # 置信度列
            conf = load_algo_confidence(aid)
            conf_text, conf_color = format_confidence(conf)
            conf_lbl = QLabel(conf_text)
            conf_lbl.setStyleSheet(f"color: {conf_color}; background: transparent;")
            conf_lbl.setFont(FONT_SM)
            conf_lbl.setFixedWidth(80)
            row_layout.addWidget(conf_lbl)

            ver_lbl = QLabel(f"v{a['version_count']}")
            ver_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            ver_lbl.setFont(FONT_SM)
            ver_lbl.setFixedWidth(50)
            row_layout.addWidget(ver_lbl)

            row_layout.addStretch()
            self._algo_row_refs[aid] = [status_lbl, conf_lbl, ver_lbl]

    def _select_all(self, flag: bool):
        """全选或全不选所有算法"""
        for cb in self._check_vars.values():
            cb.setChecked(flag)

    def _select_untrained(self):
        """仅选中尚未训练的算法"""
        for aid, cb in self._check_vars.items():
            cb.setChecked(not self._algo_meta.get(aid, {}).get("has_ckpt", False))

    def _update_algo_row(
        self,
        aid: str,
        status: str | None = None,
        status_color: str | None = None,
        conf: str | None = None,
        conf_color: str | None = None,
        ver: str | None = None,
    ):
        """动态更新算法列表行的状态/置信度/版本列。"""
        refs = self._algo_row_refs.get(aid)
        if not refs:
            return
        status_lbl, conf_lbl, ver_lbl = refs
        if status is not None:
            status_lbl.setText(status)
            if status_color:
                status_lbl.setStyleSheet(f"color: {status_color}; background: transparent;")
                status_lbl.setFont(FONT_SM)
        if conf is not None:
            conf_lbl.setText(conf)
            if conf_color:
                conf_lbl.setStyleSheet(f"color: {conf_color}; background: transparent;")
                conf_lbl.setFont(FONT_SM)
        if ver is not None:
            ver_lbl.setText(ver)
