"""
B站弹幕 Protobuf 解码模块
========================

B站新版弹幕 API（/x/v2/dm/web/seg.so）返回 Protobuf 二进制（DmSegMobileReply），
不再是旧版 XML。本模块手写轻量 Protobuf wire-format 解码器，零外部依赖。

用法:
    from core.bilibili_danmaku_proto import parse_danmaku_segment, parse_danmaku_view

    elems = parse_danmaku_segment(raw_bytes)         # 解析 seg.so 响应
    view  = parse_danmaku_view(raw_bytes)            # 解析 dm/web/view 响应

参考:
    github.com/SocialSisterYi/bilibili-API-collect - dm.proto
    github.com/xmcp/pakku.js
"""

import struct
from typing import List, Dict, Optional, Tuple, Any


# ═══════════════════════════════════════════════════════════
#  Protobuf Wire Format 基础解码
# ═══════════════════════════════════════════════════════════

_WIRE_VARINT = 0          # int32, int64, uint32, bool, enum
_WIRE_64BIT = 1           # fixed64, sfixed64, double
_WIRE_LENGTH = 2          # string, bytes, sub-message, packed
_WIRE_32BIT = 5           # fixed32, sfixed32, float


class _WireReader:
    """Protobuf wire-format reader，顺序读取 tag + value。"""

    def __init__(self, data: bytes):
        self._buf = data
        self._pos = 0

    def eof(self) -> bool:
        return self._pos >= len(self._buf)

    def _read_varint(self) -> int:
        """读取 varint，返回 (值, 消耗字节数)。"""
        result = 0
        shift = 0
        while self._pos < len(self._buf):
            b = self._buf[self._pos]
            self._pos += 1
            result |= (b & 0x7F) << shift
            if not (b & 0x80):
                return result
            shift += 7
        raise ValueError("varint truncated")

    def _read_fixed64(self) -> float:
        v = struct.unpack_from("<d", self._buf, self._pos)[0]
        self._pos += 8
        return v

    def _read_fixed32(self) -> float:
        v = struct.unpack_from("<f", self._buf, self._pos)[0]
        self._pos += 4
        return v

    def read_field(self) -> Optional[Tuple[int, int]]:
        """读取下一个 tag，返回 (field_number, wire_type)。EOF 返回 None。"""
        if self.eof():
            return None
        tag = self._read_varint()
        field_number = tag >> 3
        wire_type = tag & 0x07
        return field_number, wire_type

    def read_varint(self) -> int:
        return self._read_varint()

    def read_signed_varint(self) -> int:
        """读取 zigzag-encoded sint32/sint64。"""
        v = self._read_varint()
        return (v >> 1) ^ -(v & 1)

    def read_length_delimited(self) -> bytes:
        """读取 length-delimited 数据（string / bytes / sub-message）。"""
        length = self._read_varint()
        data = self._buf[self._pos:self._pos + length]
        self._pos += length
        return data

    def read_string(self) -> str:
        return self.read_length_delimited().decode("utf-8", errors="replace")

    def read_fixed64(self) -> float:
        return self._read_fixed64()

    def read_fixed32(self) -> float:
        return self._read_fixed32()

    def sub_reader(self, length: int) -> "_WireReader":
        """创建子读取器（用于解析嵌套 message）。"""
        data = self._buf[self._pos:self._pos + length]
        self._pos += length
        return _WireReader(data)


# ═══════════════════════════════════════════════════════════
#  弹幕消息解码
# ═══════════════════════════════════════════════════════════

def _parse_danmaku_elem(reader: _WireReader) -> Dict[str, Any]:
    """解码一个 DanmakuElem 消息。

    Field mapping:
        1: id (int64)
        2: progress (int32, ms)
        3: mode (int32)
        4: fontsize (int32)
        5: color (uint32)
        6: midHash (string)
        7: content (string)
        8: ctime (int64, UNIX timestamp)
        9: weight (int32)
        10: action (string)
        11: pool (int32, 0=普通 1=字幕 2=特殊)
        12: idStr (string)
        13: attr (int32)
        14: animation (string)
        15: dmFrom (int32)
        16: likeCount (int32)
    """
    elem = {
        "dmid": 0, "progress": 0, "mode": 1, "fontsize": 25,
        "color": 16777215, "mid_hash": "", "content": "",
        "ctime": 0, "weight": 1, "action": "", "pool": 0,
        "id_str": "", "attr": 0, "animation": "", "dm_from": 0,
        "like_count": 0,
    }

    while not reader.eof():
        field = reader.read_field()
        if field is None:
            break
        fn, wt = field

        if fn == 1 and wt in (_WIRE_VARINT, _WIRE_64BIT):
            elem["dmid"] = reader.read_varint()
            elem["id_str"] = str(elem["dmid"])
        elif fn == 2 and wt == _WIRE_VARINT:
            elem["progress"] = reader.read_varint()
        elif fn == 3 and wt == _WIRE_VARINT:
            elem["mode"] = reader.read_varint()
        elif fn == 4 and wt == _WIRE_VARINT:
            elem["fontsize"] = reader.read_varint()
        elif fn == 5 and wt == _WIRE_VARINT:
            elem["color"] = reader.read_varint()
        elif fn == 6 and wt == _WIRE_LENGTH:
            elem["mid_hash"] = reader.read_string()
        elif fn == 7 and wt == _WIRE_LENGTH:
            elem["content"] = reader.read_string()
        elif fn == 8 and wt == _WIRE_VARINT:
            elem["ctime"] = reader.read_varint()
        elif fn == 9 and wt == _WIRE_VARINT:
            elem["weight"] = reader.read_varint()
        elif fn == 10 and wt == _WIRE_LENGTH:
            elem["action"] = reader.read_string()
        elif fn == 11 and wt == _WIRE_VARINT:
            elem["pool"] = reader.read_varint()
        elif fn == 12 and wt == _WIRE_LENGTH:
            elem["id_str"] = reader.read_string()
        elif fn == 13 and wt == _WIRE_VARINT:
            elem["attr"] = reader.read_varint()
        elif fn == 14 and wt == _WIRE_LENGTH:
            elem["animation"] = reader.read_string()
        elif fn == 15 and wt == _WIRE_VARINT:
            elem["dm_from"] = reader.read_varint()
        elif fn == 16 and wt == _WIRE_VARINT:
            elem["like_count"] = reader.read_varint()
        else:
            _skip_field(reader, wt)

    return elem


def _parse_dm_seg_config(reader: _WireReader) -> Dict[str, int]:
    """解码 DmSegConfig (pageSize=1, total=2)。"""
    cfg = {"page_size": 60, "total": 0}
    while not reader.eof():
        field = reader.read_field()
        if field is None:
            break
        fn, wt = field
        if fn == 1 and wt == _WIRE_VARINT:
            cfg["page_size"] = reader.read_varint()
        elif fn == 2 and wt == _WIRE_VARINT:
            cfg["total"] = reader.read_varint()
        else:
            _skip_field(reader, wt)
    return cfg


def _parse_colorful(reader: _WireReader) -> str:
    """解码 DmColorful，返回 src URL。"""
    src = ""
    while not reader.eof():
        field = reader.read_field()
        if field is None:
            break
        fn, wt = field
        if fn == 1 and wt == _WIRE_LENGTH:
            src = reader.read_string()
        else:
            _skip_field(reader, wt)
    return src


def _skip_field(reader: _WireReader, wire_type: int):
    """跳过未知/不关心的字段。"""
    if wire_type == _WIRE_VARINT:
        reader.read_varint()
    elif wire_type == _WIRE_64BIT:
        reader.read_fixed64()
    elif wire_type == _WIRE_LENGTH:
        length = reader._read_varint()
        reader._pos += length
    elif wire_type == _WIRE_32BIT:
        reader.read_fixed32()


# ═══════════════════════════════════════════════════════════
#  公开 API
# ═══════════════════════════════════════════════════════════

def parse_danmaku_segment(data: bytes) -> List[Dict[str, Any]]:
    """解析 seg.so 返回的 Protobuf 二进制 (DmSegMobileReply)。

    Args:
        data: API 响应的原始 bytes

    Returns:
        弹幕字典列表。解析失败返回空列表。

    每个弹幕字典包含:
        dmid, progress, mode, fontsize, color, mid_hash, content,
        ctime, weight, action, pool, id_str, attr, animation, dm_from, like_count
    """
    if not data or len(data) < 2:
        return []

    try:
        reader = _WireReader(data)
        results = []

        while not reader.eof():
            field = reader.read_field()
            if field is None:
                break
            fn, wt = field

            if fn == 1 and wt == _WIRE_LENGTH:
                # repeated DanmakuElem elems
                sub_data = reader.read_length_delimited()
                sub = _WireReader(sub_data)
                results.append(_parse_danmaku_elem(sub))
            elif fn == 2 and wt == _WIRE_VARINT:
                reader.read_varint()  # state
            elif fn == 3 and wt == _WIRE_LENGTH:
                reader.read_length_delimited()  # aiFlag
            elif fn == 5 and wt == _WIRE_LENGTH:
                reader.read_length_delimited()  # colorfulSrc
            else:
                _skip_field(reader, wt)

        return results
    except Exception:
        return []


def parse_danmaku_view(data: bytes) -> Dict[str, Any]:
    """解析 dm/web/view 返回的 Protobuf (DmWebViewReply)。

    Args:
        data: API 响应的原始 bytes

    Returns:
        {
            "state": int, "total_segments": int, "page_size": int,
            "special_dm_urls": [str], "count": int,
        }
        解析失败返回空字典。
    """
    if not data or len(data) < 2:
        return {}

    try:
        reader = _WireReader(data)
        result = {
            "state": 0, "total_segments": 0, "page_size": 60,
            "special_dm_urls": [], "count": 0,
        }

        while not reader.eof():
            field = reader.read_field()
            if field is None:
                break
            fn, wt = field

            if fn == 1 and wt == _WIRE_VARINT:
                result["state"] = reader.read_varint()
            elif fn == 4 and wt == _WIRE_LENGTH:
                # dmSge (DmSegConfig)
                sub_data = reader.read_length_delimited()
                sub = _WireReader(sub_data)
                cfg = _parse_dm_seg_config(sub)
                result["total_segments"] = cfg["total"]
                result["page_size"] = cfg["page_size"]
            elif fn == 6 and wt == _WIRE_LENGTH:
                # specialDms (repeated DmColorful)
                sub_data = reader.read_length_delimited()
                sub = _WireReader(sub_data)
                url = _parse_colorful(sub)
                if url:
                    result["special_dm_urls"].append(url)
            elif fn == 8 and wt == _WIRE_VARINT:
                result["count"] = reader.read_varint()
            else:
                _skip_field(reader, wt)

        return result
    except Exception:
        return {}


def try_parse_danmaku(data: bytes) -> Tuple[Optional[List[Dict]], str]:
    """自动检测格式并解析弹幕数据。

    尝试顺序: Protobuf → XML → None

    Returns:
        (elems, format): elems 为弹幕列表，format 为 "proto" / "xml" / "none"
    """
    # 1) Try Protobuf
    elems = parse_danmaku_segment(data)
    if elems:
        return elems, "proto"

    # 2) Try XML (fallback for old API / old videos)
    #    XML starts with '<?xml' or '<i>'
    if data and data[0:1] == b'<':
        try:
            from defusedxml.ElementTree import fromstring as _xml_parse

            root = _xml_parse(data)
            danmaku = []
            for d in root.findall(".//d"):
                p = d.get("p", "")
                parts = p.split(",")
                danmaku.append({
                    "dmid": 0,
                    "progress": int(float(parts[0]) * 1000) if len(parts) > 0 else 0,
                    "mode": int(parts[1]) if len(parts) > 1 else 1,
                    "fontsize": int(parts[2]) if len(parts) > 2 else 25,
                    "color": int(parts[3]) if len(parts) > 3 else 16777215,
                    "mid_hash": parts[7] if len(parts) > 7 else "",
                    "content": (d.text or "").strip(),
                    "ctime": int(parts[4]) if len(parts) > 4 else 0,
                    "weight": int(parts[6]) if len(parts) > 6 else 1,
                    "pool": 0,
                })
            return danmaku, "xml"
        except Exception:
            pass

    return None, "none"
