"""
弹幕/评论情绪分析模块 — 基于规则的情感词典 + 关键词提取

纯规则实现，不依赖外部 API 或深度学习框架，适合离线环境使用。

核心功能：
1. 情感分析 (analyze_sentiment): 分析文本列表的正向/中性/负向比例
2. 关键词提取 (extract_keywords): 基于改进 TF-IDF 提取高频关键词
3. 词频统计 (generate_word_freq): 生成词频字典（用于词云可视化）

算法特点：
- 使用预定义的情感词典（正向词 + 负向词），覆盖 B站 弹幕/评论常用词汇
- 支持程度副词的权重放大（如"非常""超级"等）
- 支持否定词的反转逻辑（如"不好"→负向，"不太好看"→正向被反转）
- 分词基于最长匹配策略，无需安装 jieba 等第三方分词库
"""

import re
import math
from collections import Counter
from typing import List, Dict, Tuple

# ── 情感词典 ───────────────────────────────────────────
# 正向/积极词汇：表达赞赏、喜爱、认可的关键词
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

# 负向/消极词汇：表达不满、批评、反感的关键词
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

# 程度副词：用于放大相邻情感词的权重
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

# 否定词：用于反转相邻情感词的极性
_NEGATORS = {"不", "没", "别", "无", "勿", "莫", "未", "不曾", "不太"}


def _tokenize(text: str) -> List[str]:
    """简单分词器：基于词典的最长匹配策略。

    分词优先级：
    1. 先尝试匹配已知的多字词（情感词典+程度副词+否定词），4字 → 1字的降序最长匹配
    2. 无法匹配的汉字按单字切分
    3. 英文单词按连续字母序列切分

    优点：不需要安装 jieba，对弹幕/评论这种短文本效果好
    缺点：OOV（词典外）词汇不会被完整识别

    Args:
        text: 待分词的原始文本

    Returns:
        list[str]: 分词后的 token 列表
    """
    tokens = []
    text_copy = text
    i = 0
    while i < len(text_copy):
        matched = False
        # 最长匹配：从 4 字词降到 1 字（降序匹配）
        for length in range(4, 0, -1):
            chunk = text_copy[i : i + length]
            if chunk in _POSITIVE_WORDS or chunk in _NEGATIVE_WORDS or chunk in _INTENSIFIERS or chunk in _NEGATORS:
                tokens.append(chunk)
                i += length
                matched = True
                break
        if not matched:
            # 未匹配到词典词汇：按字符类型切分
            if re.match(r"[\u4e00-\u9fff]", text_copy[i]):
                tokens.append(text_copy[i])  # 单个汉字
            elif re.match(r"[a-zA-Z]+", text_copy[i:]):
                m = re.match(r"[a-zA-Z]+", text_copy[i:])
                tokens.append(m.group())  # 连续英文字母序列
                i += m.end()
                continue
            i += 1
    return tokens


def analyze_sentiment(texts: List[str]) -> Dict:
    """分析文本列表的整体情绪分布。

    对每条文本进行情感打分：
    1. 分词并遍历各 token
    2. 遇到情感词：累加/减分数
    3. 遇到程度副词：将下一个情感词的权重放大 1.5 倍
    4. 遇到否定词：将下一个情感词的极性反转
    5. score > 0.5 → 正向；score < -0.5 → 负向；否则 → 中性

    Args:
        texts: 文本列表（弹幕或评论的字符串列表）

    Returns:
        dict: {"positive": 正向比例, "neutral": 中性比例, "negative": 负向比例}
              各值范围 0-1，三者和为 1.0

    Example:
        >>> result = analyze_sentiment(["好棒！太厉害了！", "无聊死了，浪费时间", "一般般吧"])
        >>> print(result)
        {"positive": 0.3333, "neutral": 0.3333, "negative": 0.3333, ...}
    """
    pos_count = neg_count = neutral_count = 0
    for text in texts:
        if not text or not isinstance(text, str):
            neutral_count += 1  # 空文本视为中性
            continue
        tokens = _tokenize(text.strip())
        score = 0  # 该条文本的累计情感得分
        for i, token in enumerate(tokens):
            weight = 1.0
            # 检查前面是否有程度副词（向后看 1-2 个 token）
            if i >= 1 and tokens[i - 1] in _INTENSIFIERS:
                weight *= 1.5  # 紧邻的程度副词：1.5 倍权重
            elif i >= 2 and tokens[i - 2] in _INTENSIFIERS:
                weight *= 1.3  # 间隔一个词的程度副词：1.3 倍权重
            # 检查前面是否有否定词（向后看最多 2 个 token）
            if any(tokens[j] in _NEGATORS for j in range(max(0, i - 2), i)):
                weight *= -1.0  # 否定词反转极性

            if token in _POSITIVE_WORDS:
                score += weight
            elif token in _NEGATIVE_WORDS:
                score -= weight

        # 根据得分判定情感类别（阈值 0.5 用于消除微小噪声）
        if score > 0.5:
            pos_count += 1
        elif score < -0.5:
            neg_count += 1
        else:
            neutral_count += 1

    total = pos_count + neg_count + neutral_count
    if total == 0:
        return {"positive": 0.33, "neutral": 0.34, "negative": 0.33}  # 无数据时默认均匀分布
    return {
        "positive": round(pos_count / total, 4),
        "neutral": round(neutral_count / total, 4),
        "negative": round(neg_count / total, 4),
    }


def extract_keywords(texts: List[str], top_n: int = 20) -> List[Tuple[str, float]]:
    """基于改进的 TF-IDF（TF + 模拟 IDF）提取关键词。

    算法：
    1. 统计所有文本中每个词的出现次数（TF）
    2. 用 (text_count / word_count) 的对数模拟 IDF
    3. 排序取 Top-N

    注意：这里不依赖语料库，IDF 是模拟的，因此更适合单次会话内的关键词提取。

    Args:
        texts: 文本列表
        top_n: 返回前 N 个关键词，默认 20

    Returns:
        list[(word, score)]: 按权重降序排列的关键词列表，如 [("好棒", 0.95), ("无聊", 0.72), ...]
    """
    counter: Counter = Counter()
    for text in texts:
        if not text:
            continue
        tokens = _tokenize(text.strip())
        # 过滤单字词汇（信息量太低）
        counter.update(t for t in tokens if len(t) > 1)

    if not counter:
        return []

    max_count = max(counter.values())
    total = sum(counter.values())

    results = []
    for word, count in counter.most_common(top_n * 3):  # 先取 top_n * 3 再二次过滤
        # 词频归一化（TF）
        tf = count / max_count
        # 模拟 IDF：低频词权重略降
        idf = math.log(1 + total / (count + 1))
        score = tf * idf
        results.append((word, round(score, 4)))

    results.sort(key=lambda x: -x[1])  # 按权重降序
    return results[:top_n]


def generate_word_freq(texts: List[str]) -> Dict[str, int]:
    """生成词频字典（用于词云可视化）。

    统计所有文本中长度 > 1 的词的频率，返回 Top 100 高频词。

    Args:
        texts: 文本列表

    Returns:
        dict[str, int]: {"词": 频率, ...}，如 {"好棒": 15, "无聊": 8, ...}
    """
    counter: Counter = Counter()
    for text in texts:
        if not text:
            continue
        tokens = _tokenize(text.strip())
        counter.update(t for t in tokens if len(t) > 1)  # 过滤单字
    return dict(counter.most_common(100))


# ── 模块测试 ───────────────────────────────────────────


def _test():
    """内部测试函数：验证情感分析和关键词提取的正确性"""
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
