"""
权重设置界面
"""
import tkinter as tk
from tkinter import ttk, messagebox, LEFT, RIGHT, BOTH, X, Y, W
import sys
import os

# 添加algorithms路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'algorithms'))

from algorithms.registry import AlgorithmRegistry
from algorithms.weight_manager import weight_manager
from ui.theme import C


class WeightSettingsWindow:
    """权重设置窗口"""
    
    def __init__(self, parent=None):
        self.window = tk.Toplevel(parent)
        self.window.title("算法权重设置")
        self.window.geometry("700x500")
        self.window.transient(parent)
        
        # 权重输入框字典
        self.weight_vars = {}
        self.check_vars = {}
        
        self.setup_ui()
        self.load_weights()
    
    def setup_ui(self):
        """设置UI"""
        # 说明
        info_frame = ttk.LabelFrame(self.window, text="说明", padding=10)
        info_frame.pack(fill=X, padx=10, pady=5)
        
        info_text = """
权重设置：
• 用户自定义权重优先级最高
• 机器学习会自动根据准确率调整未自定义的权重
• 权重范围：0.01 ~ 10.0
• 权重越高，该算法在综合预测中占比越大
        """
        ttk.Label(info_frame, text=info_text, justify=LEFT).pack(anchor=W)
        
        # 算法权重列表
        list_frame = ttk.LabelFrame(self.window, text="算法权重", padding=10)
        list_frame.pack(fill=BOTH, expand=True, padx=10, pady=5)
        
        # 表头
        header_frame = ttk.Frame(list_frame)
        header_frame.pack(fill=X)
        
        ttk.Label(header_frame, text="算法", width=20, font=('Arial', 9, 'bold')).grid(row=0, column=0, sticky=W)
        ttk.Label(header_frame, text="自定义", width=8, font=('Arial', 9, 'bold')).grid(row=0, column=1)
        ttk.Label(header_frame, text="权重值", width=10, font=('Arial', 9, 'bold')).grid(row=0, column=2)
        ttk.Label(header_frame, text="ML权重", width=10, font=('Arial', 9, 'bold')).grid(row=0, column=3)
        ttk.Label(header_frame, text="准确率", width=10, font=('Arial', 9, 'bold')).grid(row=0, column=4)
        ttk.Label(header_frame, text="样本数", width=8, font=('Arial', 9, 'bold')).grid(row=0, column=5)
        
        # 算法列表容器
        self.algo_frame = ttk.Frame(list_frame)
        self.algo_frame.pack(fill=BOTH, expand=True)
        
        # 按钮框架
        btn_frame = ttk.Frame(self.window, padding=10)
        btn_frame.pack(fill=X)
        
        ttk.Button(btn_frame, text="重置所有权重", command=self._reset_all).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="刷新", command=self.load_weights).pack(side=LEFT, padx=5)
        ttk.Button(btn_frame, text="保存", command=self._save).pack(side=RIGHT, padx=5)
        ttk.Button(btn_frame, text="取消", command=self.window.destroy).pack(side=RIGHT, padx=5)
    
    def load_weights(self):
        """加载权重"""
        # 清除旧数据
        for widget in self.algo_frame.winfo_children():
            widget.destroy()
        
        self.weight_vars.clear()
        self.check_vars.clear()
        
        # 获取算法信息
        algo_info = AlgorithmRegistry.get_weights_info()
        
        for i, info in enumerate(algo_info):
            row_frame = ttk.Frame(self.algo_frame)
            row_frame.pack(fill=X, pady=2)
            
            # 算法名称
            ttk.Label(row_frame, text=info['name'], width=20).grid(row=0, column=0, sticky=W)
            
            # 自定义复选框
            var = tk.BooleanVar(value=info['is_customized'])
            self.check_vars[info['name']] = var
            ttk.Checkbutton(row_frame, variable=var, command=lambda n=info['name']: self._on_check_change(n)).grid(row=0, column=1)
            
            # 权重输入
            weight_var = tk.DoubleVar(value=info.get('user_weight') or info.get('final_weight', 1.0))
            self.weight_vars[info['name']] = weight_var
            
            weight_entry = ttk.Entry(row_frame, textvariable=weight_var, width=10)
            weight_entry.grid(row=0, column=2)
            
            # ML权重（只读）
            ml_weight = info.get('ml_weight', 1.0)
            ttk.Label(row_frame, text=f"{ml_weight:.2f}", width=10, foreground=C["text_3"]).grid(row=0, column=3)
            
            # 准确率
            accuracy = info.get('accuracy', 0)
            ttk.Label(row_frame, text=f"{accuracy*100:.1f}%", width=10).grid(row=0, column=4)
            
            # 样本数
            samples = info.get('samples', 0)
            ttk.Label(row_frame, text=str(samples), width=8).grid(row=0, column=5)
    
    def _on_check_change(self, name: str):
        """复选框变化"""
        var = self.check_vars[name]
        weight_var = self.weight_vars[name]
        
        if var.get():
            # 启用自定义
            weight_var.set(weight_manager.ml_weights.get(name, 1.0))
        else:
            # 恢复自动
            weight_var.set(weight_manager.ml_weights.get(name, 1.0))
    
    def _reset_all(self):
        """重置所有权重"""
        if messagebox.askyesno("确认", "确定要重置所有自定义权重吗？"):
            weight_manager.reset_weights()
            self.load_weights()
            messagebox.showinfo("成功", "已重置所有权重")
    
    def _save(self):
        """保存权重"""
        for name, check_var in self.check_vars.items():
            weight_var = self.weight_vars[name]
            
            try:
                weight = float(weight_var.get())
                weight = max(0.01, min(10.0, weight))  # 限制范围
                
                if check_var.get():
                    # 保存用户自定义权重
                    weight_manager.set_user_weight(name, weight)
                else:
                    # 清除用户自定义
                    weight_manager.clear_user_weight(name)
            except ValueError:
                messagebox.showerror("错误", f"算法 {name} 的权重值无效")
                return
        
        messagebox.showinfo("成功", "权重设置已保存")
        self.window.destroy()
