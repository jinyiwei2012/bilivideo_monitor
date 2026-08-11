"""
预测回测面板 — 基于 RolloutBacktester 滚动窗口交叉验证
评估各算法在历史数据上的离线预测表现（RMSE / MAE / MAPE）
"""

import threading
import numpy as np
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QCheckBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSpinBox, QFrame,
)
from PyQt6.QtCore import Qt, QTimer

from ui.theme import C
from ui.helpers import FONT, FONT_SM, fmt_num
from ui.dialog_base import DialogBase
from ui.invoker import invoke
from algorithms.rollout_backtest import (
    RollingBacktester,
    make_linear_fn,
    make_moving_avg_fn,
    make_exp_fn,
    make_theta_fn,
)


class BacktestPanel:
    """预测回测面板：使用滚动窗口交叉验证评估算法离线表现"""

    def __init__(self, parent, gui):
        self.gui = gui
        self.dlg = DialogBase(parent, "◧ 预测回测", "820x580")
        self.dlg.header("预测回测 — 滚动窗口交叉验证", "在历史数据上评估各算法预测准确度")
        self._build_ui()

    def _build_ui(self):
        """构建界面"""
        top = QWidget()
        top.setStyleSheet(f"background-color: {C['bg_base']};")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(10, 4, 10, 4)

        lbl = QLabel("选择视频:")
        lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        lbl.setFont(FONT)
        top_layout.addWidget(lbl)

        self._video_combo = QComboBox()
        self._video_combo.setStyleSheet(f"""
            QComboBox {{ background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px 6px; }}
        """)
        top_layout.addWidget(self._video_combo)

        # 参数
        win_lbl = QLabel("窗口:")
        win_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        win_lbl.setFont(FONT_SM)
        top_layout.addWidget(win_lbl)
        self._window_spin = QSpinBox()
        self._window_spin.setRange(5, 50)
        self._window_spin.setValue(10)
        self._window_spin.setStyleSheet(f"""
            QSpinBox {{ background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px; }}
        """)
        top_layout.addWidget(self._window_spin)

        step_lbl = QLabel("步长:")
        step_lbl.setStyleSheet(f"color: {C['text_2']}; background: transparent;")
        step_lbl.setFont(FONT_SM)
        top_layout.addWidget(step_lbl)
        self._step_spin = QSpinBox()
        self._step_spin.setRange(1, 10)
        self._step_spin.setValue(3)
        self._step_spin.setStyleSheet(f"""
            QSpinBox {{ background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']}; padding: 2px; }}
        """)
        top_layout.addWidget(self._step_spin)

        # 算法来源
        self._use_factories = QCheckBox("基础模型")
        self._use_factories.setChecked(True)
        self._use_factories.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        top_layout.addWidget(self._use_factories)
        self._use_algorithms = QCheckBox("注册算法")
        self._use_algorithms.setChecked(True)
        self._use_algorithms.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        top_layout.addWidget(self._use_algorithms)

        analyze_btn = QPushButton("◧ 开始回测")
        analyze_btn.clicked.connect(self._analyze)
        top_layout.addWidget(analyze_btn)

        # 状态区
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        self._status_lbl.setFont(FONT_SM)
        top_layout.addWidget(self._status_lbl)

        # 摘要区（在 top 下方）
        self._summary_frame = QWidget()
        self._summary_frame.setStyleSheet(f"background-color: {C['bg_base']};")
        self._summary_layout = QVBoxLayout(self._summary_frame)
        self._summary_layout.setContentsMargins(10, 0, 10, 4)

        # 表格
        columns = ["算法", "RMSE", "MAE", "MAPE", "测试次数", "排名"]
        self._tree = QTreeWidget()
        self._tree.setColumnCount(len(columns))
        self._tree.setHeaderLabels(columns)
        self._tree.setAlternatingRowColors(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {C['bg_elevated']}; color: {C['text_1']};
                border: 1px solid {C['border']};
                alternate-background-color: {C['bg_surface']};
            }}
            QHeaderView::section {{
                background-color: {C['bg_surface']}; color: {C['text_2']};
                font-weight: bold; padding: 4px;
                border: 1px solid {C['border']};
            }}
        """)
        hdr = self._tree.header()
        hdr.setStretchLastSection(True) if hdr else None
        self._tree.setColumnWidth(0, 180)
        self._tree.setColumnWidth(1, 90)
        self._tree.setColumnWidth(2, 90)
        self._tree.setColumnWidth(3, 70)
        self._tree.setColumnWidth(4, 70)
        self._tree.setColumnWidth(5, 50)

        area = self.dlg.content_area()
        outer = QVBoxLayout(area)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(top)
        outer.addWidget(self._summary_frame)
        outer.addWidget(self._tree, 1)

        # 填充视频列表
        videos = self.gui.monitored_videos
        names = [f"{v.get('title', v.get('bvid', ''))[:35]} ({v.get('bvid', '')})" for v in videos]
        self._video_combo.addItems(names)
        if names:
            self._video_combo.setCurrentIndex(0)
            self._video_combo.currentIndexChanged.connect(lambda: self._analyze())
            QTimer.singleShot(200, self._analyze)

    def _get_series(self, bvid: str):
        """从数据库提取播放量时间序列（一维 numpy 数组）"""
        video_db = self.gui.video_dbs.get(bvid)
        if not video_db:
            return None
        try:
            records = video_db.get_all_records(limit=3000)
            if not records:
                return None
            views = []
            for r in records:
                v = r.get("view_count", 0)
                if isinstance(v, (int, float)) and v > 0:
                    views.append(float(v))
            return np.array(views, dtype=np.float64) if views else None
        except Exception as e:
            import logging; logging.getLogger(__name__).debug("回测数据解析失败: %s", e)
            return None

    def _make_algo_predict_fn(self, algo_name: str):
        """为注册算法创建 predict_fn 适配器。

        将算法需要的 video_data dict 封装为 backtester 所需的
        predict_fn(series) -> float 接口。
        """
        from algorithms.registry import AlgorithmRegistry

        adapter = AlgorithmRegistry.get_algorithm(algo_name)
        if adapter is None:
            return None

        def predict_fn(train: np.ndarray) -> float:
            current_views = float(train[-1])
            n = len(train)
            # 构建 history_data（算法需要的格式）
            history = []
            for i in range(n):
                history.append({
                    "view_count": int(train[i]),
                    "view": int(train[i]),
                    "timestamp": datetime.now(),  # 不影响速度计算
                })
            video_data = {
                "view_count": int(current_views),
                "history_data": history,
                "timestamp": datetime.now(),
                "data_points": n,
            }
            try:
                result = adapter.predict(video_data, threshold=100000)
                predicted_hours = getattr(result, "predicted_hours", float("inf"))
                velocity = getattr(result, "current_velocity", 0)
                # 用预测小时数和速度反推下一个值
                if velocity > 0 and predicted_hours != float("inf") and predicted_hours > 0:
                    remaining = (predicted_hours * 3600) * velocity / 3600
                    return current_views + velocity * (75.0 / 3600.0)  # 75秒短周期
                elif velocity > 0:
                    return current_views + velocity * (75.0 / 3600.0)
                else:
                    return current_views * 1.005
            except Exception as e:
                import logging; logging.getLogger(__name__).debug("回测预测回退: %s", e)
                return current_views * 1.01

        return predict_fn

    def _analyze(self):
        """在后台线程执行回测，避免阻塞 UI"""
        self._status_lbl.setText("⏳ 回测中…")
        self._status_lbl.setStyleSheet(f"color: {C['accent']}; background: transparent;")

        idx = self._video_combo.currentIndex()
        if idx < 0:
            return
        video = self.gui.monitored_videos[idx]
        bvid = video.get("bvid", "")

        params = {
            "bvid": bvid,
            "min_train": self._window_spin.value(),
            "step": self._step_spin.value(),
            "use_factories": self._use_factories.isChecked(),
            "use_algorithms": self._use_algorithms.isChecked(),
        }
        threading.Thread(target=self._run_backtest, args=(params,), daemon=True).start()

    def _run_backtest(self, params):
        """后台执行回测并更新 UI"""
        bvid = params["bvid"]
        series = self._get_series(bvid)
        if series is None or len(series) < params["min_train"] + 5:
            msg = "数据不足" if series is None else f"数据点不足（{len(series)} < {params['min_train'] + 5}）"
            invoke(lambda m=msg: [
                self._status_lbl.setText(m),
                self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
            ])
            return

        invoke(lambda n=len(series): [
            self._status_lbl.setText(f"⏳ 回测中… {n} 个数据点"),
            self._status_lbl.setStyleSheet(f"color: {C['accent']}; background: transparent;")
        ])

        # 构建预测器字典
        predictors = {}

        # 基础模型工厂
        if params["use_factories"]:
            predictors.update({
                "线性回归": make_linear_fn(order=1),
                "二次回归": make_linear_fn(order=2),
                "移动平均(5)": make_moving_avg_fn(window=5),
                "移动平均(10)": make_moving_avg_fn(window=10),
                "指数增长": make_exp_fn(),
                "Theta(2.0)": make_theta_fn(theta=2.0),
            })

        # 注册算法
        if params["use_algorithms"]:
            try:
                from algorithms.registry import AlgorithmRegistry
                AlgorithmRegistry.initialize()
                # 取前 30 个算法（避免回测太慢）
                algo_names = AlgorithmRegistry.get_algorithm_names()[:30]
                for name in algo_names:
                    fn = self._make_algo_predict_fn(name)
                    if fn:
                        short = name.replace("[Model] ", "")
                        predictors[short] = fn
            except Exception as e:
                err_msg = f"加载算法失败: {e}"
                invoke(lambda: [
                    self._status_lbl.setText(err_msg),
                    self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
                ])
                return

        if not predictors:
            invoke(lambda: [
                self._status_lbl.setText("无可用预测器"),
                self._status_lbl.setStyleSheet(f"color: {C['danger']}; background: transparent;")
            ])
            return

        # 执行回测
        backtester = RollingBacktester(
            min_train=params["min_train"],
            step=params["step"],
            horizon=1,
        )
        results = backtester.backtest_multi_predictor(series, predictors)

        # 更新 UI（主线程）
        invoke(lambda: self._show_results(results, params))

    def _show_results(self, results, params):
        """在主线程更新 UI 显示回测结果"""
        # 清空旧数据
        self._tree.clear()
        # 清空 summary_frame
        while self._summary_layout.count():
            item = self._summary_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        # 过滤和排序
        valid = [
            (name, r["rmse"], r["mae"], r["mape"], r["n_tests"])
            for name, r in results.items()
            if r["n_tests"] >= 3 and r["mape"] != float("inf")
        ]
        valid.sort(key=lambda x: x[3])  # 按 MAPE 升序

        if not valid:
            lbl = QLabel("无有效回测结果（测试次数不足）")
            lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            lbl.setFont(FONT)
            self._summary_layout.addWidget(lbl)
            self._status_lbl.setText("完成（无有效结果）")
            self._status_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
            return

        # 摘要
        best = valid[0]
        worst = valid[-1] if len(valid) > 1 else None
        summary = f"◎ 最佳: {best[0]} (MAPE={best[3]*100:.1f}%, RMSE={int(best[1])})"
        if worst and len(valid) > 1:
            summary += f"  |  ✗ 最差: {worst[0]} (MAPE={worst[3]*100:.1f}%)"
        sum_lbl = QLabel(summary)
        sum_lbl.setStyleSheet(f"color: {C['text_1']}; background: transparent;")
        sum_lbl.setFont(FONT)
        self._summary_layout.addWidget(sum_lbl)

        detail_lbl = QLabel(
            f"数据点: {params['min_train']} 窗口 / {params['step']} 步长 / 共 {len(valid)} 个预测器"
        )
        detail_lbl.setStyleSheet(f"color: {C['text_3']}; background: transparent;")
        detail_lbl.setFont(FONT_SM)
        self._summary_layout.addWidget(detail_lbl)

        # 表格
        success_color = C["success"]
        danger_color = C["danger"]
        for rank, (name, rmse, mae, mape, n_tests) in enumerate(valid, 1):
            vals = [name[:25], fmt_num(int(rmse)), fmt_num(int(mae)),
                    f"{mape*100:.1f}%", str(n_tests), f"#{rank}"]
            item = QTreeWidgetItem(vals)
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight)
            item.setTextAlignment(2, Qt.AlignmentFlag.AlignRight)
            item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight)
            item.setTextAlignment(4, Qt.AlignmentFlag.AlignCenter)
            item.setTextAlignment(5, Qt.AlignmentFlag.AlignCenter)
            if rank <= 3:
                item.setForeground(0, Qt.GlobalColor.darkGreen)
            elif rank >= len(valid) - 2:
                item.setForeground(0, Qt.GlobalColor.red)
            self._tree.addTopLevelItem(item)

        self._status_lbl.setText(f"✓ 完成 — {len(valid)} 个预测器")
        self._status_lbl.setStyleSheet(f"color: {C['success']}; background: transparent;")
