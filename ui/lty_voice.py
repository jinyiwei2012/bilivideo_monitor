"""天依口吻文案库 — 让程序文案像洛天依本人在说话。

角色素材 (源自官方设定):
- 15 岁虚拟歌手, 灰发绿瞳, 温柔又坚强, 软萌天然呆, 细腻敏感
- 吃货属性 (世界第一吃货殿下), 治愈系声线
- 象征: 中国五声音阶「羽」(梵文 प), 应援色 天依蓝 #66CCFF
- 名曲意象: 《追光使者》深海/星空/天使鱼/月光/银河/追光
            《万古生香》蘸笔天河/共举霞觞 《深夜书店》深夜的温暖
- 台词风格: 温柔鼓励, 偶尔天然呆, 用歌声/音符表达 (♪)

口吻规范:
- 自称「天依」/「我」; 语气词: 呢、哦、啦、呀、呜…、诶嘿~
- 温柔鼓励式; 不冷漠不机械; 装饰 ♪
- 错误时: 先道歉安抚再给方向, 绝不让用户看技术细节
"""


# ── 场景文案 ────────────────────────────────
def welcome() -> str:
    return "欢迎回来~我是天依,让我陪你一起看播放量吧 ♪"


def empty(thing: str = "数据") -> str:
    return f"还没有{thing}呢…要我陪你一起找找吗?♪"


def loading() -> str:
    return "天依正在准备中…像追光一样,稍等一下下哦 ♪"


def success(action: str = "操作") -> str:
    return f"{action}完成啦!♪ 天依为你鼓掌~"


def error(action: str = "这次") -> str:
    return f"呜…{action}好像出了点小状况,天依会想办法的,请稍后再试哦"


def error_detail(action: str = "这次", detail: str = "") -> str:
    """友好错误 + 可选细节 (细节仅用于日志, 不进 UI)。"""
    return f"呜…{action}失败了,请稍后再试哦 (天依已记录问题啦 ♪ {detail})"


def warning(msg: str) -> str:
    return f"要注意哦…{msg}"


def confirm_delete(thing: str = "这条数据") -> str:
    return f"真的要删除{thing}吗?删掉就找不回来啦…"


def confirm(question: str) -> str:
    return f"{question}"


def notify(title: str) -> str:
    return f"♪ {title}"


def song_line(song: str) -> str:
    """名曲意象点缀 (用于特定场景)。"""
    return {
        "light": "就像《追光使者》里追着光的我,一起向前冲吧 ♪",
        "heritage": "蘸笔天河,共举霞觞,今夜为你轻叙 ♪",
        "bookstore": "像深夜书店里遇见的温暖,天依就在这里陪着你 ♪",
    }.get(song, "")


# ── 常见状态短语 ────────────────────────────
STATUS = {
    "ready": "天依准备好了 ♪",
    "running": "正在努力中…♪",
    "done": "完成啦!♪",
    "failed": "呜…失败了,天依会再试试的哦",
    "no_video": "还没有监控的视频呢,去添加一个吧 ♪",
    "no_data": "还没有数据呢…♪",
    "no_model": "还没有训练好的模型呢,要先训练一下哦 ♪",
    "waiting": "天依在等新的数据哦 ♪",
}
