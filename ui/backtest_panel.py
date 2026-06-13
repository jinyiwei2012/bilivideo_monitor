"""
预测回测面板 — 基于 RolloutBacktester 滚动窗口交叉验证
评估各算法在历史数据上的离线预测表现（RMSE / MAE / MAPE）
"""

import tkinter as tk
from tkinter import ttk
import threading
import numpy as np
from datetime import datetime

from ui.theme import C
from ui.helpers import FONT, FONT_SM, fmt_num
from ui.dialog_base import DialogBase
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
        self.dlg = DialogBase(parent, "📊 预测回测", "820x580")
        self.dlg.header("预测回测 — 滚动窗口交叉验证", "在历史数据上评估各算法预测准确度")
        self._build_ui()

    def _build_ui(self):
        """构建界面"""
        top = tk.Frame(self.dlg.content_area(), bg=C["bg_base"])
        top.pack(fill=tk.X, padx=10, pady=4)

        tk.Label(top, text="选择视频:", bg=C["bg_base"], fg=C["text_1"], font=FONT).pack(side=tk.LEFT)
        self._video_var = tk.StringVar()
        self._video_combo = ttk.Combobox(top, textvariable=self._video_var, font=FONT, state="readonly", width=40)
        self._video_combo.pack(side=tk.LEFT, padx=6)

        # 参数
        tk.Label(top, text="窗口:", bg=C["bg_base"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(8, 2))
        self._window_var = tk.IntVar(value=10)
        ttk.Spinbox(top, from_=5, to=50, textvariable=self._window_var, width=4).pack(side=tk.LEFT, padx=2)

        tk.Label(top, text="步长:", bg=C["bg_base"], fg=C["text_2"], font=FONT_SM).pack(side=tk.LEFT, padx=(6, 2))
        self._step_var = tk.IntVar(value=3)
        ttk.Spinbox(top, from_=1, to=10, textvariable=self._step_var, width=4).pack(side=tk.LEFT, padx=2)

        # 算法来源
        self._use_factories = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="基础模型", variable=self._use_factories).pack(side=tk.LEFT, padx=(8, 2))
        self._use_algorithms = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="注册算法", variable=self._use_algorithms).pack(side=tk.LEFT, padx=2)

        ttk.Button(top, text="📊 开始回测", command=self._analyze).pack(side=tk.LEFT, padx=(8, 4))

        # 状态区
        self._status_lbl = tk.Label(top, text="", bg=C["bg_base"], fg=C["text_3"], font=FONT_SM)
        self._status_lbl.pack(side=tk.LEFT, padx=8)

        # 摘要
        self._summary_frame = tk.Frame(self.dlg.content_area(), bg=C["bg_base"])
        self._summary_frame.pack(fill=tk.X, padx=10, pady=4)

        # 表格
        columns = ("algo", "rmse", "mae", "mape", "n_tests", "rank")
        self._tree = ttk.Treeview(self.dlg.content_area(), columns=columns, show="headings", height=18)
        self._tree.heading("algo", text="算法")
        self._tree.heading("rmse", text="RMSE")
        self._tree.heading("mae", text="MAE")
        self._tree.heading("mape", text="MAPE")
        self._tree.heading("n_tests", text="测试次数")
        self._tree.heading("rank", text="排名")
        self._tree.column("algo", width=180)
        self._tree.column("rmse", width=90, anchor="e")
        self._tree.column("mae", width=90, anchor="e")
        self._tree.column("mape", width=70, anchor="e")
        self._tree.column("n_tests", width=70, anchor="center")
        self._tree.column("rank", width=50, anchor="center")
        self._tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        # 填充视频列表
        videos = self.gui.monitored_videos
        names = [f"{v.get('title', v.get('bvid', ''))[:35]} ({v.get('bvid', '')})" for v in videos]
        self._video_combo["values"] = names
        if names:
            self._video_combo.current(0)
            self._video_combo.bind("<<ComboboxSelected>>", lambda e: self._analyze())
            self.dlg.window.after(200, self._analyze)

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
        except Exception:
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
            except Exception:
                return current_views * 1.01

        return predict_fn

    def _analyze(self):
        """在后台线程执行回测，避免阻塞 UI"""
        self._status_lbl.config(text="⏳ 回测中…", fg=C["accent"])

        idx = self._video_combo.current()
        if idx < 0:
            return
        video = self.gui.monitored_videos[idx]
        bvid = video.get("bvid", "")

        params = {
            "bvid": bvid,
            "min_train": self._window_var.get(),
            "step": self._step_var.get(),
            "use_factories": self._use_factories.get(),
            "use_algorithms": self._use_algorithms.get(),
        }
        threading.Thread(target=self._run_backtest, args=(params,), daemon=True).start()

    def _run_backtest(self, params):
        """后台执行回测并更新 UI"""
        bvid = params["bvid"]
        series = self._get_series(bvid)
        if series is None or len(series) < params["min_train"] + 5:
            self.dlg.window.after(0, lambda: self._status_lbl.config(
                text="数据不足" if series is None else f"数据点不足（{len(series)} < {params['min_train'] + 5}）",
                fg=C["danger"]
            ))
            return

        self.dlg.window.after(0, lambda: self._status_lbl.config(
            text=f"⏳ 回测中… {len(series)} 个数据点", fg=C["accent"]
        ))

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
                self.dlg.window.after(0, lambda: self._status_lbl.config(
                    text=f"加载算法失败: {e}", fg=C["danger"]
                ))
                return

        if not predictors:
            self.dlg.window.after(0, lambda: self._status_lbl.config(
                text="无可用预测器", fg=C["danger"]
            ))
            return

        # 执行回测
        backtester = RollingBacktester(
            min_train=params["min_train"],
            step=params["step"],
            horizon=1,
        )
        results = backtester.backtest_multi_predictor(series, predictors)

        # 更新 UI（主线程）
        self.dlg.window.after(0, lambda: self._show_results(results, params))

    def _show_results(self, results, params):
        """在主线程更新 UI 显示回测结果"""
        # 清空旧数据
        for row in self._tree.get_children():
            self._tree.delete(row)
        for w in self._summary_frame.winfo_children():
            w.destroy()

        # 过滤和排序
        valid = [
            (name, r["rmse"], r["mae"], r["mape"], r["n_tests"])
            for name, r in results.items()
            if r["n_tests"] >= 3 and r["mape"] != float("inf")
        ]
        valid.sort(key=lambda x: x[3])  # 按 MAPE 升序

        if not valid:
            tk.Label(
                self._summary_frame, text="无有效回测结果（测试次数不足）",
                fg=C["text_3"], bg=C["bg_base"], font=FONT
            ).pack()
            self._status_lbl.config(text="完成（无有效结果）", fg=C["text_3"])
            return

        # 摘要
        best = valid[0]
        worst = valid[-1] if len(valid) > 1 else None
        summary = f"🎯 最佳: {best[0]} (MAPE={best[3]*100:.1f}%, RMSE={int(best[1])})"
        if worst and len(valid) > 1:
            summary += f"  |  ❌ 最差: {worst[0]} (MAPE={worst[3]*100:.1f}%)"
        tk.Label(self._summary_frame, text=summary, bg=C["bg_base"], fg=C["text_1"], font=FONT).pack(anchor="w")
        tk.Label(
            self._summary_frame,
            text=f"数据点: {params['min_train']} 窗口 / {params['step']} 步长 / 共 {len(valid)} 个预测器",
            bg=C["bg_base"], fg=C["text_3"], font=FONT_SM,
        ).pack(anchor="w")

        # 表格
        for rank, (name, rmse, mae, mape, n_tests) in enumerate(valid, 1):
            # 颜色：top 3 绿色，后 3 红色
            tag = ""
            if rank <= 3:
                tag = "best"
            elif rank >= len(valid) - 2:
                tag = "worst"
            self._tree.insert("", tk.END, values=(
                name[:25], fmt_num(int(rmse)), fmt_num(int(mae)),
                f"{mape*100:.1f}%", n_tests, f"#{rank}",
            ), tags=(tag,) if tag else ())

        self._tree.tag_configure("best", foreground=C["success"])
        self._tree.tag_configure("worst", foreground=C["danger"])
        self._status_lbl.config(text=f"✅ 完成 — {len(valid)} 个预测器", fg=C["success"])
