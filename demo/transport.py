"""Bounded framing for DCVC bytes; no pickle or remote code execution."""
import json
import struct

MAX_META = 16384
MAX_PAYLOAD = 32 * 1024 * 1024
HEADER = struct.Struct('!4sII')


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
    metadata = json.loads(read_exact(sock, meta_size))
    if not isinstance(metadata, dict):
        raise ValueError('码流元信息必须是对象')
    return metadata, read_exact(sock, size)
