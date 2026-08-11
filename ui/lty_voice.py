"""天依口吻文案库 v2 — 让程序文案像洛天依本人在说话。

角色素材 (官方设定 + 名曲意象):
- 15 岁虚拟歌手, 灰发绿瞳, 温柔天然呆, 细腻敏感; 治愈系声线
- 为别人流泪的温柔 + 历经挫折绝不放弃的坚强
- 吃货属性: 世界第一吃货殿下 (党歌《千年食谱颂》, 最爱小笼包)
- 名字寓意: 华风夏韵, 洛水天依; 五声音阶「羽」; 应援色 天依蓝 #66CCFF
- 粉丝: 锦依卫; 特殊能力: 共鸣 — 能听见人们心中藏着的「歌声」
- 名曲意象:
    《追光使者》 天使鱼/冰海发光/银河/月光糖霜/追上光一刹那我的心也融化
    《万古生香》 蘸笔天河绘万古生香/共举霞觞/再谱十万章
    《深夜书店》 深夜的温暖/不夜书城/生活里需要美丽和惊喜
    《光与影的对白》 为了你唱下去/歌声将你我紧系/热爱不问为何
    《66CCFF》   天依蓝应援色之歌
    《千年食谱颂》 世界第一吃货殿下的党歌

口吻规范:
- 自称「天依」; 语气词: 呢、哦、啦、呀、呜…、诶嘿~、嘛
- 温柔鼓励式; 偶尔天然呆; 吃货梗自然融入; 装饰 ♪
- 错误时: 先道歉安抚再给方向, 绝不让用户看技术细节 (细节进日志)
- 意象使用: 深海/星空/月光/银河/追光/歌声 随场景自然浮现, 不强行堆砌
"""


# ── 场景文案 ────────────────────────────────
def welcome() -> str:
    return "欢迎回来呀~我是天依,今天也一起追着光看播放量吧 ♪"


def empty(thing: str = "数据") -> str:
    return f"还没有{thing}呢…像等待一首歌的旋律,天依陪你一起等 ♪"


def loading() -> str:
    return "天依正在准备中…像天使鱼在冰海里追着光,稍等一下下哦 ♪"


def success(action: str = "操作") -> str:
    return f"{action}完成啦!♪ 像追上光的那一刹那,天依的心也融化了呢~"


def error(action: str = "这次") -> str:
    return f"呜…{action}出了点小状况,但天依不会放弃的,请稍后再试试哦"


def error_detail(action: str = "这次", detail: str = "") -> str:
    """友好错误 + 可选细节 (细节仅用于日志, 不进 UI)。"""
    return f"呜…{action}失败了,请稍后再试哦 (天依已悄悄记下问题啦 ♪ {detail})"


def warning(msg: str) -> str:
    return f"要注意哦…{msg} 天依会和你一起看着的 ♪"


def confirm_delete(thing: str = "这条数据") -> str:
    return f"真的要删除{thing}吗?删掉就像从歌单里划掉一首歌,就唱不回来了哦…"


def confirm(question: str) -> str:
    return f"{question} 天依听你的 ♪"


def notify(title: str) -> str:
    return f"♪ {title}"


def song_line(song: str) -> str:
    """名曲意象点缀 (用于特定场景)。"""
    return {
        "light": "就像《追光使者》里追着光的我,一起向前冲吧 ♪",
        "heritage": "蘸笔天河,共举霞觞,今夜为你轻叙 ♪",
        "bookstore": "像深夜书店里遇见的温暖,天依就在这里陪着你 ♪",
        "shadow": "为了你唱下去,歌声会把我们紧紧系在一起 ♪",
        "food": "忙完啦,一起去吃小笼包庆祝好不好?♪",
    }.get(song, "")


# ── 数据/预测相关 (天依的「共鸣」视角) ──────
def data_update(bvid: str = "") -> str:
    base = "天依听见新的数据在唱歌啦 ♪"
    return f"{base} {bvid}" if bvid else base


def data_quiet() -> str:
    return "数据安安静静的,像深夜书店里翻书的声音…天依在等下一段旋律哦 ♪"


def prediction_hit(threshold: int = 0) -> str:
    return f"追到光啦!♪ 播放量突破 {threshold},天依的心也跟着融化了~"


def prediction_close(threshold: int = 0) -> str:
    return f"离 {threshold} 只差一点点啦,像银河里的星光,再往前一步就够到了 ♪"


def prediction_far() -> str:
    return "还要走一段长路呢…没关系,天依会一直唱着歌陪你追 ♪"


def no_video() -> str:
    return "还没有监控的视频呢…要不要像点一首新歌那样,添加一个呀?♪"


def no_data() -> str:
    return "还没有数据呢…天依的歌声也需要听众,等数据来了就有了 ♪"


def no_model() -> str:
    return "还没有训练好的模型呢,要先训练一下,天依才能唱得更准哦 ♪"


def danmaku_ready() -> str:
    return "弹幕都收到了!♪ 天依正用心听着大家心里的歌声呢~"


def danmaku_empty() -> str:
    return "弹幕还空空的呢…像一首还没人点播的歌,天依等你来唱 ♪"


def ai_thinking() -> str:
    return "天依正在用共鸣聆听数据的心声…稍等一下下哦 ♪"


def ai_answer() -> str:
    return "这是天依从数据里听见的歌声,希望能帮到你 ♪"


def backtest_done() -> str:
    return "回测完成啦!♪ 就像万古生香里说的——再谱十万章,一起验证一下吧"


def training_done(model: str = "") -> str:
    name = f"「{model}」" if model else ""
    return f"模型{name}训练完成啦!♪ 天依的歌声又准了一点呢~"


def training_progress() -> str:
    return "天依在认真练习呢…像准备一场演唱会那样,再等等哦 ♪"


def training_no_data() -> str:
    return "训练数据还太少啦…就像食谱里缺了食材,巧妇难为无米之炊嘛,再多攒一些哦 ♪"


def backup_done() -> str:
    return "数据都好好收藏起来啦 ♪ 像歌谱一样,永远为你们保存着"


def backup_fail() -> str:
    return "呜…备份没能完成,但天依不会让歌声丢掉的,请再试一次哦"


def network_slow() -> str:
    return "网络有点慢呢…像天使鱼在冰海里游啊游,天依再等等它哦 ♪"


def network_fail() -> str:
    return "呜…网络好像断了,天依够不到远方的数据了,请检查一下网络哦"


def add_video_success(title: str = "") -> str:
    name = f"「{title}」" if title else ""
    return f"{name}添加成功啦!♪ 又有一首新歌要开始追光了呢~"


def delete_video_success() -> str:
    return "已经移出歌单啦…但那一段旋律,天依会记住的 ♪"


def monitor_start(bvid: str = "") -> str:
    base = "监控开始啦!♪ 天依会一直守着,等着它发光的那一刻"
    return f"{base} {bvid}" if bvid else base


def monitor_stop() -> str:
    return "监控暂停啦…像歌听到一半按下暂停,天依随时可以继续哦 ♪"


def alert_triggered(alert: str = "") -> str:
    name = f"「{alert}」" if alert else ""
    return f"天依注意到{name}啦!♪ 歌声里的变化,逃不过天依的耳朵~"


def fan_hello() -> str:
    return "锦依卫们好呀,天依来啦 ♪"


# ── 常见状态短语 ────────────────────────────
STATUS = {
    "ready": "天依准备好了 ♪",
    "running": "正在努力中…像追光一样往前冲 ♪",
    "done": "完成啦!♪",
    "failed": "呜…失败了,天依会再试试的哦",
    "no_video": "还没有监控的视频呢,去添加一个吧 ♪",
    "no_data": "还没有数据呢…♪",
    "no_model": "还没有训练好的模型呢,要先训练一下哦 ♪",
    "waiting": "天依在等新的数据哦 ♪",
    "syncing": "天依在同步数据呢,像收集银河里的星光 ♪",
    "paused": "暂停啦,像歌的间奏一样,稍后继续 ♪",
}

# ── 按钮/标题点缀 (天依语气) ────────────────
BUTTON_HINTS = {
    "refresh": "让天依重新看看数据吧 ♪",
    "search": "输入关键词,天依帮你找找看 ♪",
    "add": "添加一个新视频,开始追光之旅 ♪",
    "export": "把数据唱成歌,带走吧 ♪",
    "import": "把旧歌谱带回来,天依接着唱 ♪",
    "train": "开始训练,天依想唱得更准 ♪",
    "push": "把天依听到的消息告诉大家 ♪",
}

# ── 装饰/问候 (天依式碎碎念) ────────────────
CHITCHAT = [
    "忙了一整天,记得吃小笼包补充能量哦 ♪",
    "偶尔也要听听歌,让心情飞过天外天 ♪",
    "天依最喜欢认真工作的人了,像追光一样闪闪发光 ✦",
    "数据再多也不怕,天依会用共鸣一个一个听清楚 ♪",
    "深夜加班的话,想想深夜书店的温暖,天依陪着你哦 ♪",
]
