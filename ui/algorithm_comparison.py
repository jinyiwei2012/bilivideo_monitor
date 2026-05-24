"""算法可视化比较：准确率 / 权重 / 详细数据对比"""

import tkinter as tk
from tkinter import ttk
import logging
from typing import List, Dict

from ui.theme import C
from ui.helpers import FONT, FONT_SM

logger = logging.getLogger(__name__)

# 图表边距
_ML, _MR, _MT, _MB = 60, 20, 32, 80
_BAR_H = 18
_BAR_GAP = 6

# 按类别分配颜色
_CATEGORY_COLORS = {
    "速度类": "#0969da",
    "时间衰减": "#8250df",
    "扩散模型": "#1a7f37",
    "时间序列": "#bf3989",
    "统计模型": "#d1242f",
    "集成学习": "#9a6700",
    "深度学习": "#0550ae",
    "高级分析": "#0e765c",
    "基础": "#6e40c9",
    "其他": "#8b949e",
}
_CATEGORY_FALLBACK = list(_CATEGORY_COLORS.values())


def _cat_color(cat: str) -> str:
    return _CATEGORY_COLORS.get(cat, "#8b949e")


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


class AlgorithmComparisonWindow:
    """算法可视化比较窗口"""

    def __init__(self, parent=None):
        self.window = tk.Toplevel(parent)
        self.window.title("算法可视化比较")
        sw = parent.winfo_screenwidth() if parent else 1920
        sh = parent.winfo_screenheight() if parent else 1080
        self.window.geometry(f"{int(sw * 0.52)}x{int(sh * 0.72)}")
        self.window.minsize(700, 500)
        self.window.configure(bg=C["bg_surface"])

        self._algo_info: List[Dict] = []
        self._load_data()

        self._setup_ui()

    # ── 数据加载 ────────────────────────────────────────

    def _load_data(self):
        """从注册器和权重管理器加载算法信息"""
        try:
            from algorithms.registry import AlgorithmRegistry

            self._algo_info = AlgorithmRegistry.get_weights_info()
            # 补充 category
            for info in self._algo_info:
                name = info.get("name", "")
                # 去除 [Model] 等前缀后再次尝试匹配
                clean_name = name.split("] ", 1)[-1] if "] " in name else name
                algo = AlgorithmRegistry.get_algorithm(clean_name) or AlgorithmRegistry.get_algorithm(name)
                if algo is not None:
                    info["category"] = getattr(algo, "category", "其他")
                else:
                    info["category"] = "其他"
                info.setdefault("samples", 0)
                info.setdefault("accuracy", 0.5)
                info.setdefault("final_weight", 1.0)
        except Exception as e:
            logger.warning("加载算法信息失败: %s", e)

    # ── UI ──────────────────────────────────────────────

    def _setup_ui(self):
        # 标题
        tk.Label(
            self.window,
            text=f"算法可视化比较（共 {len(self._algo_info)} 个算法）",
            bg=C["bg_surface"],
            fg=C["text_1"],
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(14, 4))

        # 控制栏：类别过滤 + 排序
        ctrl = tk.Frame(self.window, bg=C["bg_surface"])
        ctrl.pack(fill=tk.X, padx=14, pady=(0, 6))

        tk.Label(ctrl, text="类别过滤:", bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT, padx=(0, 4))
        self._cat_var = tk.StringVar(value="全部")
        cats = self._collect_categories()
        self._cat_combo = ttk.Combobox(ctrl, textvariable=self._cat_var, values=cats, width=16, state="readonly", font=FONT)
        self._cat_combo.pack(side=tk.LEFT, padx=(0, 12))
        self._cat_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        tk.Label(ctrl, text="排序:", bg=C["bg_surface"], fg=C["text_2"], font=FONT).pack(side=tk.LEFT, padx=(0, 4))
        self._sort_var = tk.StringVar(value="准确率 ↓")
        sorts = ["准确率 ↓", "准确率 ↑", "权重 ↓", "权重 ↑", "样本数 ↓", "名称"]
        self._sort_combo = ttk.Combobox(ctrl, textvariable=self._sort_var, values=sorts, width=12, state="readonly", font=FONT)
        self._sort_combo.pack(side=tk.LEFT, padx=(0, 12))
        self._sort_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh())

        # 统计摘要
        self._summary_lbl = tk.Label(ctrl, text="", bg=C["bg_surface"], fg=C["text_3"], font=FONT_SM)
        self._summary_lbl.pack(side=tk.LEFT, padx=6)

        # 刷新按钮
        ttk.Button(ctrl, text="↻ 刷新", command=self._refresh).pack(side=tk.RIGHT)

        # Notebook
        nb = ttk.Notebook(self.window)
        nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        tab_acc = tk.Frame(nb, bg=C["bg_base"])
        tab_weight = tk.Frame(nb, bg=C["bg_base"])
        tab_detail = tk.Frame(nb, bg=C["bg_base"])

        nb.add(tab_acc, text="  准确率对比  ")
        nb.add(tab_weight, text="  权重对比  ")
        nb.add(tab_detail, text="  详细数据  ")

        self._acc_canvas = tk.Canvas(tab_acc, bg=C["bg_base"], highlightthickness=0)
        self._acc_canvas.pack(fill=tk.BOTH, expand=True)

        self._weight_canvas = tk.Canvas(tab_weight, bg=C["bg_base"], highlightthickness=0)
        self._weight_canvas.pack(fill=tk.BOTH, expand=True)

        self._setup_detail_tab(tab_detail)

        self._refresh()

    def _collect_categories(self) -> list:
        cats = set()
        for info in self._algo_info:
            cats.add(info.get("category", "其他"))
        return ["全部"] + sorted(cats)

    # ── 数据过滤与排序 ──────────────────────────────────

    def _get_filtered(self) -> list:
        cat = self._cat_var.get()
        filtered = [info for info in self._algo_info if cat == "全部" or info.get("category") == cat]

        s = self._sort_var.get()
        if s == "准确率 ↓":
            filtered.sort(key=lambda x: x.get("accuracy", 0), reverse=True)
        elif s == "准确率 ↑":
            filtered.sort(key=lambda x: x.get("accuracy", 0))
        elif s == "权重 ↓":
            filtered.sort(key=lambda x: x.get("final_weight", 1), reverse=True)
        elif s == "权重 ↑":
            filtered.sort(key=lambda x: x.get("final_weight", 1))
        elif s == "样本数 ↓":
            filtered.sort(key=lambda x: x.get("samples", 0), reverse=True)
        else:
            filtered.sort(key=lambda x: x.get("name", ""))
        return filtered

    # ── 准确率柱状图 ────────────────────────────────────

    def _draw_accuracy_chart(self):
        c = self._acc_canvas
        c.delete("all")
        W = c.winfo_width()
        H = c.winfo_height()
        if W < 100 or H < 100:
            self.window.after(200, self._draw_accuracy_chart)
            return

        filtered = self._get_filtered()
        if not filtered:
            c.create_text(W // 2, H // 2, text="无数据", fill=C["text_3"], font=FONT)
            return

        n = len(filtered)
        cw = W - _ML - _MR
        ch = max(50, H - _MT - _MB)
        bar_unit = _BAR_H + _BAR_GAP
        total_h = n * bar_unit
        # 如果内容超长，不绘制（需要滚动，但简单起见只适配可见区域）
        visible = filtered[:max(1, int(ch / bar_unit))]

        # 标题
        c.create_text(W // 2, 14, text="算法准确率对比", fill=C["text_1"], font=FONT)

        for i, info in enumerate(visible):
            y0 = _MT + i * bar_unit
            name = info.get("name", "?")[:28]
            acc = max(0, min(1, info.get("accuracy", 0.5)))
            bar_w = acc * cw
            color = _cat_color(info.get("category", "其他"))

            # 类别色条（左侧小色块）
            c.create_rectangle(_ML - 10, y0, _ML - 4, y0 + _BAR_H, fill=color, outline="")

            # 柱体
            if bar_w > 0:
                c.create_rectangle(_ML, y0, _ML + bar_w, y0 + _BAR_H, fill=color, outline="", stipple="" if bar_w > 4 else "gray25")

            # 名称（右对齐到柱体起始）
            c.create_text(_ML - 14, y0 + _BAR_H // 2, text=name, anchor="e", fill=C["text_2"], font=FONT_SM)

            # 数值标签
            lbl = _fmt_pct(acc)
            c.create_text(_ML + bar_w + 6, y0 + _BAR_H // 2, text=lbl, anchor="w", fill=C["text_1"], font=FONT_SM)

            # 样本数
            samples = info.get("samples", 0)
            if samples:
                c.create_text(_ML + cw, y0 + _BAR_H // 2, text=f"n={samples}", anchor="e", fill=C["text_3"], font=("Consolas", 7))

        # 图例 —— 用到的类别
        used_cats = {info.get("category", "其他") for info in visible}
        lx = _ML
        ly = _MT + len(visible) * bar_unit + 10
        for cat in sorted(used_cats):
            c.create_rectangle(lx, ly, lx + 12, ly + 12, fill=_cat_color(cat), outline="")
            c.create_text(lx + 16, ly + 6, text=cat, anchor="w", fill=C["text_2"], font=FONT_SM)
            lx += 70

        self._update_summary(filtered)

    # ── 权重柱状图 ────────────────────────────────────

    def _draw_weight_chart(self):
        c = self._weight_canvas
        c.delete("all")
        W = c.winfo_width()
        H = c.winfo_height()
        if W < 100 or H < 100:
            self.window.after(200, self._draw_weight_chart)
            return

        filtered = self._get_filtered()
        if not filtered:
            c.create_text(W // 2, H // 2, text="无数据", fill=C["text_3"], font=FONT)
            return

        n = len(filtered)
        cw = W - _ML - _MR
        ch = max(50, H - _MT - _MB)
        bar_unit = _BAR_H + _BAR_GAP
        visible = filtered[:max(1, int(ch / bar_unit))]

        max_w = max(info.get("final_weight", 1) for info in visible) or 1

        c.create_text(W // 2, 14, text="算法权重对比", fill=C["text_1"], font=FONT)

        for i, info in enumerate(visible):
            y0 = _MT + i * bar_unit
            name = info.get("name", "?")[:28]
            w = max(0, info.get("final_weight", 1.0))
            bar_w = w / max_w * cw
            color = "#0969da"

            c.create_rectangle(_ML, y0, _ML + bar_w, y0 + _BAR_H, fill=color, outline="")

            c.create_text(_ML - 14, y0 + _BAR_H // 2, text=name, anchor="e", fill=C["text_2"], font=FONT_SM)

            is_custom = info.get("is_customized", False)
            suffix = " ✎" if is_custom else ""
            lbl = f"{w:.2f}{suffix}"
            c.create_text(_ML + bar_w + 6, y0 + _BAR_H // 2, text=lbl, anchor="w", fill=C["text_1"], font=FONT_SM)

    # ── 详细数据表格 ────────────────────────────────────

    def _setup_detail_tab(self, parent):
        cols = ("name", "category", "accuracy", "final_weight", "samples", "is_customized")
        headers = {"name": "算法名称", "category": "类别", "accuracy": "准确率", "final_weight": "权重", "samples": "样本数", "is_customized": "自定义"}

        container = tk.Frame(parent, bg=C["bg_base"])
        container.pack(fill=tk.BOTH, expand=True)

        vsb = ttk.Scrollbar(container, orient="vertical")
        hsb = ttk.Scrollbar(container, orient="horizontal")
        self._tree = ttk.Treeview(
            container,
            columns=cols,
            show="headings",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            height=20,
        )
        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)

        for cid, header in headers.items():
            self._tree.heading(cid, text=header, command=lambda c=cid: self._sort_tree(c))
            self._tree.column(cid, width=80, anchor="center")

        self._tree.column("name", width=220, anchor="w")
        self._tree.column("category", width=80, anchor="center")

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

    def _populate_tree(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        filtered = self._get_filtered()
        for info in filtered:
            self._tree.insert(
                "",
                "end",
                values=(
                    info.get("name", ""),
                    info.get("category", ""),
                    _fmt_pct(info.get("accuracy", 0.5)),
                    f"{info.get('final_weight', 1.0):.2f}",
                    info.get("samples", 0),
                    "是" if info.get("is_customized") else "否",
                ),
            )

    def _sort_tree(self, col):
        """点击表头排序"""
        if hasattr(self, "_tree_sort_rev") and self._tree_sort_col == col:
            self._tree_sort_rev = not self._tree_sort_rev
        else:
            self._tree_sort_col = col
            self._tree_sort_rev = False

        items = [(self._tree.set(k, col), k) for k in self._tree.get_children("")]
        reverse = self._tree_sort_rev
        # 数值列按数值排序
        if col in ("accuracy", "final_weight", "samples"):
            items.sort(key=lambda x: float(x[0].replace("%", "")) if x[0].replace("%", "").replace(".", "").isdigit() else 0, reverse=reverse)
        else:
            items.sort(key=lambda x: x[0], reverse=reverse)

        for idx, (_, k) in enumerate(items):
            self._tree.move(k, "", idx)

    # ── 通用 ────────────────────────────────────────────

    def _update_summary(self, filtered):
        n_total = len(self._algo_info)
        n_filtered = len(filtered)
        avg_acc = sum(info.get("accuracy", 0) for info in filtered) / max(1, n_filtered)
        avg_weight = sum(info.get("final_weight", 1) for info in filtered) / max(1, n_filtered)
        self._summary_lbl.config(text=f"展示 {n_filtered}/{n_total} | 平均准确率 {_fmt_pct(avg_acc)} | 平均权重 {avg_weight:.2f}")

    def _refresh(self):
        self._draw_accuracy_chart()
        self._draw_weight_chart()
        self._populate_tree()
