"""洛天依主题图标集 — 全程序统一换装, 替代分散的 emoji 表情。

设计语言: 天依蓝 + 音符音乐符号 (洛天依是虚拟歌手)
- 导航/功能按钮使用 ♪ ♫ ♬ ♩ 音符体系 (语义由文字标签承载)
- 功能性图标保留可读性 (⚙ 设置 / ⇪ 推送 / ⌕ 搜索)
- 装饰元素: ♪ 音符、羽 (五音之羽, 洛天依象征)

用法:
    from ui.icons import ICONS
    btn.setText(f"{ICONS['nav_monitor']} 监控列表")
"""
from ui.theme import C  # noqa: F401 — 确保主题已加载

# ── 主题图标映射 ─────────────────────────────
ICONS = {
    # 导航 (音符体系)
    "nav_monitor": "♪",      # 监控列表
    "nav_log": "♫",          # 日志
    "nav_train": "♬",        # 模型训练
    "nav_finetune": "♩",     # 微调训练
    # 功能区
    "settings": "⚙",         # 设置
    "push": "⇪",             # 全部推送
    "model_act": "◉",        # 激活模型
    "search": "⌕",           # 搜索
    "refresh": "⟳",          # 刷新
    "add": "＋",             # 添加
    "remove": "－",          # 移除
    "export": "↧",           # 导出
    "import": "↥",           # 导入
    # 状态/装饰
    "success": "✓",
    "error": "✗",
    "note": "♪",
    "feather": "羽",         # 洛天依象征 (五音之羽)
    "star": "★",
}

# ── 装饰字符 (天依主题点缀) ───────────────────
DECOR = {
    "wave": "〰",      # 水波 (洛水天依意象)
    "sparkle": "✦",
    "heart": "♡",
}
