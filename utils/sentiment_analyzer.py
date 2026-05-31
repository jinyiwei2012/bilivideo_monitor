"""
弹幕/评论情绪分析模块 — 基于规则的情感词典 + 关键词提取
不依赖外部API或深度学习框架，纯规则实现
"""

import re
import math
from collections import Counter
from typing import List, Dict, Tuple

# ── 情感词典（积极/消极） ─────────────────────────────
_POSITIVE_WORDS = {
    "好",
    "棒",
    "赞",
    "强",
    "厉害",
    "优秀",
    "精彩",
    "喜欢",
    "爱",
    "美",
    "好看",
    "好听",
    "好棒",
    "了不起",
    "绝了",
    "神作",
    "神仙",
    "大佬",
    "太强了",
    "感动",
    "泪目",
    "震撼",
    "牛逼",
    "无敌",
    "炸裂",
    "起飞",
    "神",
    "宝藏",
    "精品",
    "良心",
    "超爱",
    "好用",
    "完美",
    "经典",
    "收藏",
    "三连",
    "一键三连",
    "关注",
    "投币",
    "加油",
    "支持",
}

_NEGATIVE_WORDS = {
    "差",
    "烂",
    "垃",
    "圾",
    "恶心",
    "难听",
    "难看",
    "无聊",
    "没意思",
    "浪费",
    "浪费时间",
    "垃圾",
    "不行",
    "不好",
    "失望",
    "差评",
    "反感",
    "作呕",
    "低俗",
    "垃圾中的战斗机",
    "水",
    "灌水",
    "骗",
    "虚假",
    "抄袭",
    "盗用",
    "举报",
    "取关",
    "退钱",
    "尴尬",
    "无语",
    "暴躁",
    "生气了",
    "呵呵",
    "呵呵哒",
    "呸",
    "糟蹋",
    "败笔",
    "烂活",
}

# 程度副词
_INTENSIFIERS = {
    "非常",
    "很",
    "太",
    "超级",
    "极其",
    "特别",
    "十分",
    "无比",
    "绝",
    "极",
    "爆",
    "死",
    "疯",
    "炸",
    "透",
    "坏",
}

# 否定词
_NEGATORS = {"不", "没", "别", "无", "勿", "莫", "未", "不曾", "不太"}


def _tokenize(text: str) -> List[str]:
    """简单分词（基于正则，不依赖 jieba）"""
    # 匹配中文词组（2-4字常用词优先）+ 单个汉字 + 英文单词
    tokens = []
    # 先尝试匹配已知多字词
    text_copy = text
    i = 0
    while i < len(text_copy):
        matched = False
        # 最长匹配 4 字词
        for length in range(4, 0, -1):
            chunk = text_copy[i : i + length]
            if chunk in _POSITIVE_WORDS or chunk in _NEGATIVE_WORDS or chunk in _INTENSIFIERS or chunk in _NEGATORS:
                tokens.append(chunk)
                i += length
                matched = True
                break
        if not matched:
            if re.match(r"[\u4e00-\u9fff]", text_copy[i]):
                tokens.append(text_copy[i])
            elif re.match(r"[a-zA-Z]+", text_copy[i:]):
                m = re.match(r"[a-zA-Z]+", text_copy[i:])
                tokens.append(m.group())
                i += m.end()
                continue
            i += 1
    return tokens


def analyze_sentiment(texts: List[str]) -> Dict:
    """分析文本列表的情绪倾向

    Returns:
        dict: {positive, neutral, negative} 各比例 (0-1)
    """
    pos_count = neg_count = neutral_count = 0
    for text in texts:
        if not text or not isinstance(text, str):
            neutral_count += 1
            continue
        tokens = _tokenize(text.strip())
        score = 0
        for i, token in enumerate(tokens):
            weight = 1.0
            # 检查前面是否有程度副词
            if i >= 1 and tokens[i - 1] in _INTENSIFIERS:
                weight *= 1.5
            elif i >= 2 and tokens[i - 2] in _INTENSIFIERS:
                weight *= 1.3
            # 检查前面是否有否定词（向后看最多2个token）
            if any(tokens[j] in _NEGATORS for j in range(max(0, i - 2), i)):
                weight *= -1.0

            if token in _POSITIVE_WORDS:
                score += weight
            elif token in _NEGATIVE_WORDS:
                score -= weight

        if score > 0.5:
            pos_count += 1
        elif score < -0.5:
            neg_count += 1
        else:
            neutral_count += 1

    total = pos_count + neg_count + neutral_count
    if total == 0:
        return {"positive": 0.33, "neutral": 0.34, "negative": 0.33}
    return {
        "positive": round(pos_count / total, 4),
        "neutral": round(neutral_count / total, 4),
        "negative": round(neg_count / total, 4),
    }


def extract_keywords(texts: List[str], top_n: int = 20) -> List[Tuple[str, float]]:
    """基于 TF（词频）提取关键词，返回 [(词, 权重)]"""
    counter: Counter = Counter()
    for text in texts:
        if not text:
            continue
        tokens = _tokenize(text.strip())
        # 过滤单字
        counter.update(t for t in tokens if len(t) > 1)

    if not counter:
        return []

    max_count = max(counter.values())
    total = sum(counter.values())

    results = []
    for word, count in counter.most_common(top_n * 3):
        # TF 归一化
        tf = count / max_count
        # IDF 模拟：低频词权重略降
        idf = math.log(1 + total / (count + 1))
        score = tf * idf
        results.append((word, round(score, 4)))

    results.sort(key=lambda x: -x[1])
    return results[:top_n]


def generate_word_freq(texts: List[str]) -> Dict[str, int]:
    """生成词频字典（用于词云）"""
    counter: Counter = Counter()
    for text in texts:
        if not text:
            continue
        tokens = _tokenize(text.strip())
        counter.update(t for t in tokens if len(t) > 1)
    return dict(counter.most_common(100))


def _test():
    """测试函数"""
    texts = [
        "好棒！太厉害了！",
        "真好看，支持UP主",
        "无聊死了，浪费时间",
        "一般般吧",
        "绝了，这质量太强了",
        "呵呵，垃圾内容",
    ]
    sa = analyze_sentiment(texts)
    print("Sentiment:", sa)
    kw = extract_keywords(texts, top_n=10)
    print("Keywords:", kw)


if __name__ == "__main__":
    _test()
