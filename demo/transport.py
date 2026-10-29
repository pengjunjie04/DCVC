"""Bounded framing for DCVC bytes; no pickle or remote code execution."""
import json
import struct
from pathlib import Path
import subprocess
import math
from io import BytesIO

MAX_META = 16384
MAX_PAYLOAD = 32 * 1024 * 1024
HEADER = struct.Struct('!4sII')


def ethernet_route(local_ip, peer_ip):
    result = subprocess.run(['ip', '-j', 'route', 'get', peer_ip, 'from', local_ip],
                            capture_output=True, text=True, timeout=3)
    if result.returncode:
        raise ValueError('有线路由不可用，请先配置两端有线 IP 并插入网线')
    routes = json.loads(result.stdout)
    if not routes or not routes[0].get('dev'):
        raise ValueError('无法确定码流传输网卡')
    interface = routes[0]['dev']
    if interface == 'lo' or (Path('/sys/class/net') / interface / 'wireless').exists():
        raise ValueError('当前路由未使用有线网卡，请检查两端有线地址')
    return interface


def decode_preview(meta, payload, count, width, height):
    import cv2
    import numpy as np
    from PIL import Image
    if meta.get('type') != 'preview' or meta.get('count') != count:
        raise ValueError('解码端返回了无效帧数')
    elapsed = meta.get('decode_ms')
    if type(elapsed) not in (float, int) or not math.isfinite(elapsed) or not 0 <= elapsed <= 120000:
        raise ValueError('解码端返回了无效耗时')
    sizes = meta.get('sizes')
    if not isinstance(sizes, list) or len(sizes) != count or any(type(n) is not int or not 0 < n <= 2 * 1024 * 1024 for n in sizes) or sum(sizes) != len(payload):
        raise ValueError('解码预览长度不正确')
    output, offset = [], 0
    for size in sizes:
        data = payload[offset:offset+size]
        with Image.open(BytesIO(data)) as image:
            if image.format != 'JPEG' or image.size != (width, height):
                raise ValueError('解码预览尺寸不匹配')
        bgr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError('解码端预览损坏')
        output.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        offset += size
    return output, elapsed


def read_exact(sock, length):
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(min(length - len(data), 65536))
        if not chunk:
            raise EOFError('对端断开，码流不完整')
        data.extend(chunk)
    return bytes(data)


def send_packet(sock, metadata, payload):
    if not isinstance(metadata, dict) or not isinstance(payload, bytes):
        raise ValueError('码流元信息或载荷类型无效')
    meta = json.dumps(metadata, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if not 0 < len(meta) <= MAX_META or len(payload) > MAX_PAYLOAD:
        raise ValueError('码流数据过大')
    sock.sendall(HEADER.pack(b'DCV1', len(meta), len(payload)) + meta + payload)


def recv_packet(sock):
    magic, meta_size, size = HEADER.unpack(read_exact(sock, HEADER.size))
    if magic != b'DCV1' or not 0 < meta_size <= MAX_META or size > MAX_PAYLOAD:
        raise ValueError('无效的码流头或数据长度')
    try:
        metadata = json.loads(read_exact(sock, meta_size))
    except (RecursionError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('无法解析码流元信息') from exc
    if not isinstance(metadata, dict):
        raise ValueError('码流元信息必须是对象')
    return metadata, read_exact(sock, size)
