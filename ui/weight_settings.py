"""
现代化权重设置界面
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "algorithms"))

from algorithms.registry import AlgorithmRegistry
from algorithms.weight_manager import weight_manager
from ui.theme import C
from ui.helpers import FONT, FONT_SM, FONT_MONO
from ui.dialog_base import DialogBase


class WeightSettingsWindow:
    """权重设置窗口（现代化风格）"""

    def __init__(self, parent=None):
        self.dlg = DialogBase(parent, "算法权重设置", "860x640", resizable=(True, True), modal=False)
        self.window = self.dlg.window

        self.weight_vars = {}
        self.check_vars = {}
        self.setup_ui()
        self.load_weights()

    def setup_ui(self):
        self.dlg.header("算法权重", "自定义各算法在集成预测中的权重")

        # 说明卡片
        info_sec = self.dlg.section(padding=8)
        info_lines = [
            "• 用户自定义权重优先级最高，机器学习不会修改已自定义的权重",
            "• 权重范围：0.01 ~ 10.0",
            "• 权重越高，该算法在综合预测中占比越大",
        ]
        for line in info_lines:
            tk.Label(info_sec, text=line, bg=C["bg_elevated"], fg=C["text_2"], font=FONT_SM, anchor="w").pack(
                fill=tk.X, padx=4
            )

        # 权重列表
        list_sec = tk.Frame(self.dlg.container, bg=C["bg_base"])
        list_sec.pack(fill=tk.BOTH, expand=True, padx=24, pady=(10, 0))

        # 表头
        hdr = tk.Frame(list_sec, bg=C["bg_surface"], highlightthickness=1, highlightbackground=C["border_sub"])
        hdr.pack(fill=tk.X)
        for col_i, (text, w) in enumerate(
            [
                ("算法", 24),
                ("自定义", 8),
                ("权重值", 10),
                ("ML权重", 10),
                ("准确率", 10),
                ("样本数", 8),
            ]
        ):
            tk.Label(
                hdr,
                text=text,
                bg=C["bg_surface"],
                fg=C["text_2"],
                font=("Microsoft YaHei UI", 8, "bold"),
                width=w,
                anchor="w",
            ).grid(row=0, column=col_i, padx=6, pady=4, sticky="w")

        # 滚动列表
        canvas_frame = tk.Frame(list_sec, bg=C["bg_base"])
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(canvas_frame, orient="vertical")
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.algo_canvas = tk.Canvas(canvas_frame, bg=C["bg_elevated"], highlightthickness=0, yscrollcommand=vsb.set)
        self.algo_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.config(command=self.algo_canvas.yview)

        self.algo_frame = tk.Frame(self.algo_canvas, bg=C["bg_elevated"])
        self.algo_canvas.create_window((0, 0), window=self.algo_frame, anchor="nw")
        self.algo_frame.bind(
            "<Configure>", lambda e: self.algo_canvas.configure(scrollregion=self.algo_canvas.bbox("all"))
        )

        # 按钮行
        self.dlg.button_row(
            [
                ("取消", self.window.destroy, ""),
                ("重置所有权重", self._reset_all, ""),
                ("刷新", self.load_weights, ""),
                ("💾 保存", self._save, "primary"),
            ]
        )

    def load_weights(self):
        for widget in self.algo_frame.winfo_children():
            widget.destroy()
        self.weight_vars.clear()
        self.check_vars.clear()

        algo_info = AlgorithmRegistry.get_weights_info()

        for info in algo_info:
            row = tk.Frame(
                self.algo_frame, bg=C["bg_surface"], highlightthickness=1, highlightbackground=C["border_sub"]
            )
            row.pack(fill=tk.X, pady=1)

            # 名称
            tk.Label(row, text=info["name"], bg=C["bg_surface"], fg=C["text_1"], font=FONT, width=24, anchor="w").grid(
                row=0, column=0, padx=4, pady=3, sticky="w"
            )

            # 自定义复选框
            var = tk.BooleanVar(value=info["is_customized"])
            self.check_vars[info["name"]] = var
            ttk.Checkbutton(row, variable=var, command=lambda n=info["name"]: self._on_check_change(n)).grid(
                row=0, column=1, padx=2
            )

            # 权重输入
            wv = tk.DoubleVar(value=info.get("user_weight") or info.get("final_weight", 1.0))
            self.weight_vars[info["name"]] = wv
            ttk.Entry(row, textvariable=wv, width=10).grid(row=0, column=2, padx=4)

            # ML权重
            ml_w = info.get("ml_weight", 1.0)
            tk.Label(
                row, text=f"{ml_w:.2f}", bg=C["bg_surface"], fg=C["text_3"], font=FONT_MONO, width=12, anchor="w"
            ).grid(row=0, column=3)

            # 准确率
            acc = info.get("accuracy", 0)
            tk.Label(
                row, text=f"{acc*100:.1f}%", bg=C["bg_surface"], fg=C["success"], font=FONT_MONO, width=10, anchor="w"
            ).grid(row=0, column=4)

            # 样本数
            samples = info.get("samples", 0)
            tk.Label(
                row, text=str(samples), bg=C["bg_surface"], fg=C["text_2"], font=FONT_MONO, width=8, anchor="w"
            ).grid(row=0, column=5)

    def _on_check_change(self, name: str):
        var = self.check_vars[name]
        wv = self.weight_vars[name]
        wv.set(weight_manager.ml_weights.get(name, 1.0))

    def _reset_all(self):
        if messagebox.askyesno("确认", "确定要重置所有自定义权重吗？", parent=self.window):
            weight_manager.reset_weights()
            self.load_weights()
            messagebox.showinfo("成功", "已重置所有权重", parent=self.window)

    def _save(self):
        for name, check_var in self.check_vars.items():
            wv = self.weight_vars[name]
            try:
                weight = float(wv.get())
                weight = max(0.01, min(10.0, weight))
                if check_var.get():
                    weight_manager.set_user_weight(name, weight)
                else:
                    weight_manager.clear_user_weight(name)
            except ValueError:
                messagebox.showerror("错误", f"算法 {name} 的权重值无效", parent=self.window)
                return
        messagebox.showinfo("成功", "权重设置已保存", parent=self.window)
        self.window.destroy()
