"""
极验（Geetest）滑块验证码自动求解模块

本模块实现了完整的极验滑块验证码自动求解流程，用于绕过 B站 等网站的验证码防护。

求解流程：
1. GET api.geetest.com/get.php         → 获取背景图 URL 和滑块图 URL
2. 下载背景图和滑块图                   → OpenCV 加载为 NumPy 数组
3. 模板匹配 (TM_CCOEFF_NORMED)         → 定位滑块在背景图中的水平缺口位置
4. 生成类人鼠标拖动轨迹                 → 模拟加速→减速→微回调→停顿的人类行为
5. 构造 w 参数 (AES-CBC 加密)          → 封装求解数据
6. POST api.geetest.com/ajax.php        → 提交求解并获取 validate/seccode

依赖：opencv-python, numpy, requests, pycryptodomex
"""

import logging
import time
import random
import json
from typing import Optional, Tuple, List, Dict

import cv2
import numpy as np
import requests

logger = logging.getLogger(__name__)

# ── 极验 API 配置 ──────────────────────────────────────
_GEETEST_API = "https://api.geetest.com"  # 极验验证码 API 服务器
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " "KHTML, like Gecko Chrome/120.0.0.0 Safari/537.36"
)


def _get_challenge_data(gt: str, challenge: str) -> Optional[Dict]:
    """从极验 API 获取验证码素材（背景图和滑块图的 URL）。

    向 api.geetest.com/get.php 发送 GET 请求，获取验证码所需的基础数据。
    包括背景图 URL (bg)、滑块图 URL (slice)、fullbg 等。

    Args:
        gt: 极验验证 ID（从目标网站获取）
        challenge: 极验 challenge 值（从目标网站获取）

    Returns:
        dict | None: 验证码素材数据字典，包含 bg/slice/fullbg 等字段；失败返回 None
    """
    url = f"{_GEETEST_API}/get.php"
    params = {
        "is_next": "false",
        "type": "slide",  # 滑块类型验证码
        "gt": gt,
        "challenge": challenge,
        "lang": "zh-cn",
        "https": "true",
        "protocol": "https://",
        "offline": "false",
        "product": "popup",  # 弹窗式验证码
        "api_version": "1.5.4",
        "client_type": "web",
    }
    try:
        resp = requests.get(url, params=params, headers={"User-Agent": _USER_AGENT}, timeout=15)
        if resp.status_code != 200:
            logger.warning("geetest get.php HTTP %s", resp.status_code)
            return None
        data = resp.json()
        if not data.get("success"):
            logger.warning("geetest get.php not successful: %s", data)
            return None
        return data
    except Exception as e:
        logger.warning("geetest get.php error: %s", e)
        return None


def _download_image(url: str) -> Optional[np.ndarray]:
    """下载图片并解码为 OpenCV 的 BGR 格式 NumPy 数组。

    支持完整 URL 和相对路径（自动拼接 _GEETEST_API 前缀）。

    Args:
        url: 图片 URL（完整或相对路径）

    Returns:
        np.ndarray | None: BGR 格式的图片数据（shape: H×W×3）；下载失败返回 None
    """
    if url.startswith("/"):
        url = f"{_GEETEST_API}{url}"
    try:
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
        if resp.status_code != 200:
            return None
        arr = np.frombuffer(resp.content, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)  # 解码为 BGR 彩色图
    except Exception as e:
        logger.warning("download image error: %s", e)
        return None


def _detect_gap(bg_img: np.ndarray, slice_img: np.ndarray) -> int:
    """通过多尺度模板匹配检测滑块在背景图中的水平缺口位置。

    算法流程：
    1. 将背景图和滑块图转为灰度
    2. 对滑块图做 Canny 边缘增强（部分极验滑块为半透明，直接匹配效果差）
    3. 在多个缩放比例下（1.0, 0.9, 0.8）做 TM_CCOEFF_NORMED 模板匹配
    4. 取所有比例中相关系数最高的位置作为缺口坐标

    Args:
        bg_img: 带缺口的背景图 (BGR, H×W×3)
        slice_img: 滑块图 (BGR, h×w×3)

    Returns:
        int: 缺口左上角的 x 坐标（水平像素偏移量）
    """
    # 转为灰度图（OpenCV 模板匹配需要单通道）
    bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
    sl_gray = cv2.cvtColor(slice_img, cv2.COLOR_BGR2GRAY)

    # 对滑块图做边缘增强：Canny 提取轮廓边缘，半透明滑块也能提取出有效特征
    sl_edge = cv2.Canny(sl_gray, 100, 200)

    # 多尺度模板匹配：遍历多个缩放比例以提高匹配成功率
    best_val = -1
    best_loc = (0, 0)
    for scale in [1.0, 0.9, 0.8]:
        w = int(sl_gray.shape[1] * scale)
        h = int(sl_gray.shape[0] * scale)
        if w < 10 or h < 10:
            continue
        resized_sl = cv2.resize(sl_edge, (w, h), interpolation=cv2.INTER_AREA)

        # TM_CCOEFF_NORMED: 归一化相关系数匹配，值越接近 1 匹配度越高
        result = cv2.matchTemplate(bg_gray, resized_sl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val > best_val:
            best_val = max_val
            best_loc = max_loc

    logger.debug("geetest gap match value: %.4f", best_val)
    return best_loc[0]


def _calc_userresponse(distance: float, challenge: str) -> str:
    """计算极验验证码的 userresponse 参数。

    算法：取 challenge 前 32 位作为密钥，与距离字符串逐位 XOR 加密。

    Args:
        distance: 滑动距离（像素值）
        challenge: 极验 challenge 值

    Returns:
        str: 计算出的 userresponse 字符串
    """
    key = challenge[:32]  # 取 challenge 前 32 位作为 XOR 密钥
    dist_str = str(round(distance))
    res = []
    for i, c in enumerate(dist_str):
        # 距离字符串的每个字符与密钥对应位置字符进行 XOR
        res.append(chr(ord(c) ^ ord(key[i % len(key)])))
    return "".join(res)


def _generate_trace(distance: float) -> Tuple[List[Dict], int]:
    """生成类人鼠标滑动轨迹，模拟真实用户拖动滑块的行为。

    轨迹特点：
    1. 起始停顿 100~300ms（模拟用户反应时间）
    2. 前段快速加速拖到总距离的 65%~80%
    3. 中段缓慢逼近目标位置
    4. 40% 概率小幅过头再回拉（模拟人类修正行为）
    5. 结束时停顿 50~150ms
    6. 全过程伴有垂直方向小幅随机抖动（±2px）

    Args:
        distance: 需要滑动的总距离（像素值）

    Returns:
        (trace, passtime):
        - trace: [{"x": int, "y": int, "t": int}, ...] 鼠标轨迹点列表
        - passtime: 总耗时（毫秒）
    """
    trace = []
    x, y = 0, 0  # 滑块起始位置
    t = 0  # 累计时间（毫秒）

    # 起始停顿（模拟用户看到滑块后的反应延迟，100~300ms）
    pause = random.randint(100, 300)
    t += pause
    trace.append({"x": x, "y": y, "t": t})

    # 总距离拆分为"前段快速 65-80% + 后段慢速精确对准"
    remain = distance
    fast_part = remain * random.uniform(0.65, 0.8)

    # 前段: 快速加速拖动（步长 5-15px，间隔 15-35ms）
    while fast_part > 0:
        step = random.randint(5, 15)
        if step > fast_part:
            step = fast_part
        x += step
        fast_part -= step
        y += random.randint(-2, 2)  # 垂直方向小幅随机抖动，模拟人手不稳定
        t += random.randint(15, 35)
        trace.append({"x": int(x), "y": int(y), "t": t})

    # 中段: 缓慢精确逼近（步长 1-5px，间隔 20-45ms）
    while remain - x > 3:
        step = random.randint(1, 5)
        if x + step > remain:
            step = remain - x
        x += step
        y += random.randint(-1, 1)
        t += random.randint(20, 45)
        trace.append({"x": int(x), "y": int(y), "t": t})

    # 40% 概率模拟"微微过头再回拉"的人类修正行为
    if random.random() < 0.4:
        overshoot = random.uniform(2, 6)
        x += overshoot  # 过头
        t += random.randint(15, 30)
        trace.append({"x": int(x), "y": int(y), "t": t})
        # 回拉到位
        x -= overshoot + random.uniform(0, 2)
        t += random.randint(10, 25)
        trace.append({"x": int(x), "y": int(y), "t": t})

    # 结束停顿（模拟放手前的短暂停顿）
    t += random.randint(50, 150)

    passtime = t  # 总耗时
    return trace, passtime


def _encrypt_w(gt: str, challenge: str, userresponse: str, trace: List[Dict], passtime: int) -> str:
    """构造极验验证码的 w 参数（AES-CBC 加密）。

    加密流程：
    1. 计算 rp = md5(gt + challenge[:32] + passtime)
    2. 构造 JSON payload（含 gt, challenge, userresponse, passtime, trace, rp）
    3. Key = md5(challenge[:24])[:16], IV = md5(gt[:16])[:16]
    4. AES-CBC 加密 + PKCS7 填充
    5. Base64 编码输出

    Args:
        gt: 极验验证 ID
        challenge: 极验 challenge 值
        userresponse: 通过 _calc_userresponse 计算的用户响应值
        trace: 鼠标轨迹列表
        passtime: 总滑动耗时（毫秒）

    Returns:
        str: Base64 编码的加密 w 参数

    Raises:
        ImportError: 缺少 pycryptodomex 库时抛出
    """
    import hashlib
    import base64

    try:
        from Cryptodome.Cipher import AES
    except ImportError:
        raise ImportError("缺少 Cryptodome 库，请执行: pip install pycryptodomex")

    # 计算 rp 参数（随机化指纹防护）
    rp = hashlib.md5(f"{gt}{challenge[:32]}{passtime}".encode(), usedforsecurity=False).hexdigest()

    # 构造待加密的 JSON payload（紧凑格式，无空格）
    payload = json.dumps(
        {
            "gt": gt,
            "challenge": challenge[:32],
            "userresponse": userresponse,
            "passtime": passtime,
            "imgload": random.randint(100, 350),  # 图片加载耗时（随机）
            "trace": trace,
            "rp": rp,
        },
        separators=(",", ":"),
    )

    # 派生 AES 密钥和 IV
    key = hashlib.md5(challenge[:24].encode(), usedforsecurity=False).digest()[:16]
    iv = hashlib.md5(gt[:16].encode(), usedforsecurity=False).digest()[:16]

    # PKCS7 填充：将 payload 长度补齐到 16 字节的倍数
    pad_len = 16 - len(payload) % 16
    payload += chr(pad_len) * pad_len

    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(payload.encode())
    return base64.b64encode(encrypted).decode()


def _submit_solution(gt: str, challenge: str, w: str) -> Optional[Tuple[str, str]]:
    """向极验 API 提交求解结果，获取 validate 和 seccode。

    向 api.geetest.com/ajax.php 发送 GET 请求，
    解析 JSONP 格式的响应（geetest_xxx({...})）。

    Args:
        gt: 极验验证 ID
        challenge: 极验 challenge 值（取前 32 位）
        w: 加密后的求解数据（由 _encrypt_w 生成）

    Returns:
        (validate, seccode) | None: 验证通过时返回 validate 和 seccode；失败返回 None
    """
    url = f"{_GEETEST_API}/ajax.php"
    params = {
        "gt": gt,
        "challenge": challenge[:32],
        "lang": "zh-cn",
        "pt": "0",
        "client_type": "web",
        "w": w,
        "callback": f"geetest_{int(time.time() * 1000)}",  # JSONP 回调函数名
    }
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("geetest ajax.php HTTP %s", resp.status_code)
            return None

        text = resp.text
        # JSONP 回调格式: geetest_1730000000000({...})
        # 剥离回调函数包裹，提取纯 JSON 部分
        if text.startswith("geetest_"):
            idx = text.index("(")
            text = text[idx + 1:-1]  # 去除 "geetest_xxx(" 前缀和 ")" 后缀
        data = json.loads(text)

        validate = data.get("validate", "")
        seccode = data.get("seccode", "")
        if validate:
            logger.info("geetest 验证通过, validate=%s...", validate[:16])
            return validate, seccode

        logger.warning("geetest 验证失败: %s", data.get("message", "unknown"))
        return None
    except Exception as e:
        logger.warning("geetest ajax.php error: %s", e)
        return None


def solve(gt: str, challenge: str) -> Optional[Tuple[str, str]]:
    """完整的极验滑块验证码自动求解主入口函数。

    这是一个"一键求解"的便捷函数，内部串联了完整的 6 步求解流程：
    获取素材 → 下载图片 → 检测缺口 → 生成轨迹 → 加密数据 → 提交验证

    Args:
        gt: 极验验证 ID（从目标网站的 captcha 配置中获取）
        challenge: 极验 challenge 值（从目标网站的 captcha 配置中获取）

    Returns:
        (validate, seccode) | None: 验证通过时返回 validate 和 seccode 元组；
        任何步骤失败返回 None

    Example:
        >>> validate, seccode = solve("abc123...", "def456...")
        >>> if validate:
        ...     print(f"验证通过: {validate} / {seccode}")
    """
    # 第1步：获取验证码素材
    challenge_data = _get_challenge_data(gt, challenge)
    if not challenge_data:
        return None

    # 第2步：下载背景图和滑块图
    bg_url = challenge_data.get("bg", "")
    slice_url = challenge_data.get("slice", "")
    if not bg_url or not slice_url:
        logger.warning("geetest 缺少图片 URL")
        return None

    bg_img = _download_image(bg_url)
    slice_img = _download_image(slice_url)
    if bg_img is None or slice_img is None:
        logger.warning("geetest 图片下载失败")
        return None

    # 第3步：模板匹配检测缺口位置
    x = _detect_gap(bg_img, slice_img)
    logger.debug("geetest 缺口 x=%d", x)

    # 部分 geetest 的滑块本身有一定偏移量（通常是 6~10px）
    # x - slice_width/2 可以得到更准确的滑动距离
    distance = max(0, x)
    if distance < 5:
        logger.warning("geetest 缺口距离过小: %d", distance)
        return None

    # 第4步：生成类人鼠标轨迹
    trace, passtime = _generate_trace(distance)

    # 第5步：计算 userresponse 并加密构造 w 参数
    userresponse = _calc_userresponse(distance, challenge)
    w = _encrypt_w(gt, challenge, userresponse, trace, passtime)

    # 第6步：提交验证并返回结果
    return _submit_solution(gt, challenge, w)
