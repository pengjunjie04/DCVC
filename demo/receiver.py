"""Independent receiver, bound explicitly to its Ethernet IPv4 address."""
import argparse
import ipaddress
import signal
import socket
import time

from .codec import Codec, validate_packet
from .transport import recv_packet, send_packet


def handle_connection(conn, codec):
    import cv2
    while True:
        packet = recv_packet(conn)
        validate_packet(*packet)
        started = time.monotonic()
        frames = codec.decode(packet)
        elapsed = (time.monotonic() - started) * 1000
        previews = []
        for rgb in frames:
            ok, jpeg = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise RuntimeError('无法生成解码预览')
            previews.append(jpeg.tobytes())
        send_packet(conn, {'type': 'preview', 'count': len(frames), 'sizes': list(map(len, previews)),
                           'decode_ms': elapsed}, b''.join(previews))
        print(f'decoded={len(frames)}, decode_ms={elapsed:.2f}, compressed_bytes={len(packet[1])}', flush=True)


def main():
    parser = argparse.ArgumentParser(description='在解码 Jetson 上运行；仅绑定指定有线网卡')
    parser.add_argument('--bind', required=True, help='解码端有线 IPv4 地址')
    parser.add_argument('--port', type=int, default=9860)
    args = parser.parse_args()
    address = ipaddress.IPv4Address(args.bind)
    if address.is_unspecified or address.is_multicast or not 1 <= args.port <= 65535:
        parser.error('请指定有效的有线 IPv4 地址和端口')
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.bind, args.port))
        server.listen(1)
        print(f'等待编码端 {args.bind}:{args.port}；Ctrl+C 结束', flush=True)
        while True:
            conn, peer = server.accept()
            print(f'编码端连接：{peer}', flush=True)
            with conn:
                conn.settimeout(30)
                try:
                    # Each session owns new reference state, including after pause/reconnect.
                    codec = Codec()
                    handle_connection(conn, codec)
                except (EOFError, OSError, ValueError, RuntimeError) as exc:
                    print(f'会话结束：{exc}', flush=True)


if __name__ == '__main__':
    main()
