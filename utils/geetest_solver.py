"""
Geetest 滑块验证码自动求解

流程：
1. GET api.geetest.com/get.php → 获取背景图 + 滑块图 URL
2. OpenCV 模板匹配定位缺口
3. 生成类人鼠标轨迹
4. POST api.geetest.com/ajax.php → 提交求解
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

_GEETEST_API = "https://api.geetest.com"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " "KHTML, like Gecko Chrome/120.0.0.0 Safari/537.36"
)


def _get_challenge_data(gt: str, challenge: str) -> Optional[Dict]:
    """从极验 API 获取验证码素材"""
    url = f"{_GEETEST_API}/get.php"
    params = {
        "is_next": "false",
        "type": "slide",
        "gt": gt,
        "challenge": challenge,
        "lang": "zh-cn",
        "https": "true",
        "protocol": "https://",
        "offline": "false",
        "product": "popup",
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
    """下载图片并转为 OpenCV 数组"""
    if url.startswith("/"):
        url = f"{_GEETEST_API}{url}"
    try:
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
        if resp.status_code != 200:
            return None
        arr = np.frombuffer(resp.content, np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        logger.warning("download image error: %s", e)
        return None


def _detect_gap(bg_img: np.ndarray, slice_img: np.ndarray) -> int:
    """通过模板匹配检测缺口水平位置

    Args:
        bg_img: 带缺口的背景图 (BGR)
        slice_img: 滑块图 (BGR)

    Returns:
        缺口左上角的 x 坐标
    """
    # 转为灰度
    bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
    sl_gray = cv2.cvtColor(slice_img, cv2.COLOR_BGR2GRAY)

    # 对滑块图做边缘增强（部分 geetest 滑块为半透明）
    sl_edge = cv2.Canny(sl_gray, 100, 200)

    # 多尺度模板匹配
    best_val = -1
    best_loc = (0, 0)
    for scale in [1.0, 0.9, 0.8]:
        w = int(sl_gray.shape[1] * scale)
        h = int(sl_gray.shape[0] * scale)
        if w < 10 or h < 10:
            continue
        resized_sl = cv2.resize(sl_edge, (w, h), interpolation=cv2.INTER_AREA)

        result = cv2.matchTemplate(bg_gray, resized_sl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val > best_val:
            best_val = max_val
            best_loc = max_loc

    logger.debug("geetest gap match value: %.4f", best_val)
    return best_loc[0]


def _calc_userresponse(distance: float, challenge: str) -> str:
    """计算 userresponse（challenge 前 32 位与距离字符串逐位 XOR）"""
    key = challenge[:32]
    dist_str = str(round(distance))
    res = []
    for i, c in enumerate(dist_str):
        res.append(chr(ord(c) ^ ord(key[i % len(key)])))
    return "".join(res)


def _generate_trace(distance: float) -> Tuple[List[Dict], int]:
    """生成类人鼠标滑动轨迹

    模拟真实人类拖动行为：
    - 短暂停顿后开始
    - 先加速后减速
    - 可能小幅过头再回拉
    - 结束时停顿

    Returns:
        (trace, passtime)
        trace: [{"x": int, "y": int, "t": int}, ...]
        passtime: 总耗时(ms)
    """
    trace = []
    x, y = 0, 0
    t = 0

    # 起始停顿（100~300ms）
    pause = random.randint(100, 300)
    t += pause
    trace.append({"x": x, "y": y, "t": t})

    # 总距离拆分为"前段快速 + 后段慢速 + 微调"
    remain = distance
    fast_part = remain * random.uniform(0.65, 0.8)

    # 前段: 快速加速
    while fast_part > 0:
        step = random.randint(5, 15)
        if step > fast_part:
            step = fast_part
        x += step
        fast_part -= step
        y += random.randint(-2, 2)  # 垂直方向小幅抖动
        t += random.randint(15, 35)
        trace.append({"x": int(x), "y": int(y), "t": t})

    # 中段: 缓慢逼近
    while remain - x > 3:
        step = random.randint(1, 5)
        if x + step > remain:
            step = remain - x
        x += step
        y += random.randint(-1, 1)
        t += random.randint(20, 45)
        trace.append({"x": int(x), "y": int(y), "t": t})

    # 可能微过头再回拉（模拟人类修正）
    if random.random() < 0.4:
        overshoot = random.uniform(2, 6)
        x += overshoot
        t += random.randint(15, 30)
        trace.append({"x": int(x), "y": int(y), "t": t})
        # 回拉
        x -= overshoot + random.uniform(0, 2)
        t += random.randint(10, 25)
        trace.append({"x": int(x), "y": int(y), "t": t})

    # 结束停顿
    t += random.randint(50, 150)

    passtime = t
    return trace, passtime


def _encrypt_w(gt: str, challenge: str, userresponse: str, trace: List[Dict], passtime: int) -> str:
    """构造 w 参数（AES-CBC 加密）

    使用 md5(gt[:16]) 作为 IV，md5(challenge[:24])[:16] 作为 Key
    """
    from Cryptodome.Cipher import AES
    import hashlib
    import base64

    rp = hashlib.md5(f"{gt}{challenge[:32]}{passtime}".encode()).hexdigest()

    payload = json.dumps(
        {
            "gt": gt,
            "challenge": challenge[:32],
            "userresponse": userresponse,
            "passtime": passtime,
            "imgload": random.randint(100, 350),
            "trace": trace,
            "rp": rp,
        },
        separators=(",", ":"),
    )

    key = hashlib.md5(challenge[:24].encode()).hexdigest()[:16]
    iv = hashlib.md5(gt[:16].encode()).hexdigest()[:16]

    # PKCS7 填充
    pad_len = 16 - len(payload) % 16
    payload += chr(pad_len) * pad_len

    cipher = AES.new(key.encode(), AES.MODE_CBC, iv.encode())
    encrypted = cipher.encrypt(payload.encode())
    return base64.b64encode(encrypted).decode()


def _submit_solution(gt: str, challenge: str, w: str) -> Optional[Tuple[str, str]]:
    """向极验 API 提交求解结果

    Returns:
        (validate, seccode) or None
    """
    url = f"{_GEETEST_API}/ajax.php"
    params = {
        "gt": gt,
        "challenge": challenge[:32],
        "lang": "zh-cn",
        "pt": "0",
        "client_type": "web",
        "w": w,
        "callback": f"geetest_{int(time.time() * 1000)}",
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
        # JSONP 回调格式: geetest_xxx({...})
        if text.startswith("geetest_"):
            idx = text.index("(")
            text = text[idx + 1 : -1]
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
    """完整 Geetest 滑块验证码求解流程

    Args:
        gt: Geetest ID
        challenge: Geetest challenge

    Returns:
        (validate, seccode) or None
    """
    challenge_data = _get_challenge_data(gt, challenge)
    if not challenge_data:
        return None

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

    # 检测缺口位置
    x = _detect_gap(bg_img, slice_img)
    logger.debug("geetest 缺口 x=%d", x)

    # 部分 geetest 的滑块本身有一定偏移量（通常是 6~10px）
    # x - slice_width/2 可以得到更准确的滑动距离
    distance = max(0, x)
    if distance < 5:
        logger.warning("geetest 缺口距离过小: %d", distance)
        return None

    # 生成轨迹
    trace, passtime = _generate_trace(distance)

    # 计算 userresponse
    userresponse = _calc_userresponse(distance, challenge)

    # 加密构造 w 参数
    w = _encrypt_w(gt, challenge, userresponse, trace, passtime)

    # 提交验证
    return _submit_solution(gt, challenge, w)
