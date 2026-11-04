"""Independent receiver, bound explicitly to its Ethernet IPv4 address."""
import argparse
import ipaddress
import queue
import signal
import socket
import time
import multiprocessing
import math
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor

from .codec import Codec, validate_packet
from .display_ipc import PreviewMailbox
from .hardware_compare import HardwareDecoder
from .transport import recv_packet, send_packet


_PREVIEW_ENCODERS = ThreadPoolExecutor(max_workers=8, thread_name_prefix='preview-jpeg')


def _capture_ages(meta, count):
    """Per-frame age measured on the encoder's monotonic clock at send time."""
    values = meta.get('capture_ages_ns')
    if values is None:
        return [None] * count
    if (not isinstance(values, list) or len(values) != count or
            any(type(value) is not int or value < 0 for value in values)):
        raise ValueError('无效的采集年龄')
    return values


def _encode_preview(rgb):
    import cv2
    ok, jpeg = cv2.imencode('.jpg', cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
                            [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise RuntimeError('无法生成解码预览')
    return jpeg.tobytes()


def handle_connection(conn, codec_factory, progress=None, preview_queue=None):
    totals = {'total_frames':0, 'total_bytes':0, 'encode_ms':0., 'decode_ms':0.}
    display_dropped = 0
    codec = None
    # Read the socket on its own thread so a packet that arrives during a group
    # decode is timestamped on arrival, not after the decode finishes. Frame age
    # therefore stays a duration on one clock and never depends on wall-clock
    # agreement between the two Jetsons.
    inbox = queue.Queue(maxsize=2)
    def reader():
        try:
            while True:
                packet = recv_packet(conn)
                inbox.put((time.monotonic(), packet))
        except Exception as exc:  # surfaced in the decoder loop
            inbox.put((time.monotonic(), exc))
    threading.Thread(target=reader, daemon=True).start()
    while True:
        received_mono, packet = inbox.get()
        if isinstance(packet, BaseException):
            raise packet
        if packet[0].get('type') == 'clock_sync':
            sent = packet[0].get('t0')
            if packet[1] or type(sent) is not int or sent <= 0:
                raise ValueError('无效的时钟校准请求')
            received = time.time_ns()
            send_packet(conn, {'type': 'clock_sync', 't0': sent,
                               't1': received, 't2': time.time_ns()}, b'')
            continue
        if codec is None:
            # Load the model only once real video arrives.
            codec = codec_factory()
            if progress is not None:
                progress.send(None)
        validate_packet(*packet)
        started = time.monotonic()
        frames = codec.decode(packet)
        capture_ages_ns = _capture_ages(packet[0], len(frames))
        if progress is not None:
            progress.send(None)
        elapsed = (time.monotonic() - started) * 1000
        previews = list(_PREVIEW_ENCODERS.map(_encode_preview, frames))
        # Publish locally before the reply write so the decoder's own display never
        # waits on the encoder's TCP read.
        if preview_queue is not None:
            meta = packet[0]
            totals['total_frames'] += len(frames)
            totals['total_bytes'] += len(packet[1])
            totals['decode_ms'] += elapsed
            encode_ms = meta.get('encode_ms')
            if type(encode_ms) in (int, float) and math.isfinite(encode_ms) and 0 < encode_ms <= 120000:
                totals['encode_ms'] += encode_ms
            fps = meta.get('fps', 30)
            fps = fps if type(fps) is int and 1 <= fps <= 120 else 30
            encode_fps = meta.get('encode_fps', 0.)
            if type(encode_fps) not in (int, float) or not math.isfinite(encode_fps) or not 0 <= encode_fps <= 10000:
                encode_fps = 0.
            # Age now = age at send + everything that happened locally since arrival.
            aged = time.monotonic() - received_mono
            capture_ages_ns = [None if age is None else age + int(aged * 1e9)
                               for age in capture_ages_ns]
            info = {**totals, 'width':meta['width'], 'height':meta['height'], 'qp':meta['qp'],
                    'fps':fps, 'encode_fps':encode_fps, 'ipc_dropped':display_dropped,
                    'capture_ages_ns':capture_ages_ns}
            if not preview_queue.publish(info, previews):
                display_dropped += len(frames)
        send_packet(conn, {'type': 'preview', 'count': len(frames), 'sizes': list(map(len, previews)),
                           'decode_ms': elapsed}, b''.join(previews))
        print(f'decoded={len(frames)}, decode_ms={elapsed:.2f}, compressed_bytes={len(packet[1])}', flush=True)


def run_session(conn, progress=None, preview_queue=None):
    # Native rANS cannot safely reject every corrupt entropy symbol; isolate its address space.
    with conn:
        conn.settimeout(120)
        try:
            handle_connection(conn, Codec, progress, preview_queue)
        except (EOFError, ConnectionResetError, BrokenPipeError) as exc:
            print(f'会话结束：{type(exc).__name__}: {exc}', flush=True)
        except Exception as exc:
            print(f'解码失败：{type(exc).__name__}: {exc}', flush=True)
            raise


def serve_session(conn, context=None, silence_timeout=180, monitor=None):
    context = context or multiprocessing.get_context('spawn')
    receive_progress, send_progress = context.Pipe(duplex=False)
    previews = PreviewMailbox(context) if monitor is not None else None
    bridge_stop = threading.Event()
    def bridge():
        sequence = 0
        while True:
            item = previews.read(sequence)
            if item is not None:
                sequence, info, images = item
                monitor.accept(info, images)
            if bridge_stop.wait(.002):
                # The child has exited: consume its final atomic publication once.
                item = previews.read(sequence)
                if item is not None:
                    _, info, images = item
                    monitor.accept(info, images)
                return
    bridge_thread = None
    if monitor is not None:
        monitor.begin_session()
        bridge_thread = threading.Thread(target=bridge, daemon=True)
        bridge_thread.start()
    process = context.Process(target=run_session, args=(conn, send_progress, previews))
    process.start()
    send_progress.close()
    conn.close()
    last_progress = time.monotonic()
    try:
        while process.is_alive():
            if monitor is not None and monitor.exit_requested.is_set():
                break
            process.join(timeout=min(.5, silence_timeout))
            try:
                while receive_progress.poll():
                    receive_progress.recv()
                    last_progress = time.monotonic()
            except EOFError:
                pass
            if process.is_alive() and time.monotonic() - last_progress > silence_timeout:
                print('解码会话长时间无进展，正在释放进程', flush=True)
                process.terminate()
                break
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        receive_progress.close()
        bridge_stop.set()
        if bridge_thread is not None:
            bridge_thread.join(timeout=2)
            monitor.end_session(process.exitcode)
    return process.exitcode


def main():
    parser = argparse.ArgumentParser(description='在解码 Jetson 上运行；仅绑定指定有线网卡')
    parser.add_argument('--bind', required=True, help='解码端有线 IPv4 地址')
    parser.add_argument('--port', type=int, default=9860)
    parser.add_argument('--headless', action='store_true', help='只接收解码，不启动本机展示页')
    parser.add_argument('--web-host', default='127.0.0.1')
    parser.add_argument('--web-port', type=int, default=7861)
    parser.add_argument('--h264-port', type=int, default=9861)
    parser.add_argument('--h265-port', type=int, default=9862)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    address = ipaddress.IPv4Address(args.bind)
    if address.is_unspecified or address.is_multicast or not 1 <= args.port <= 65535:
        parser.error('请指定有效的有线 IPv4 地址和端口')
    monitor = web_server = hardware = None
    if not args.headless:
        import uvicorn
        from .decoder_ui import DecoderMonitor, create_decoder_app
        monitor = DecoderMonitor()
        web_server = uvicorn.Server(uvicorn.Config(create_decoder_app(monitor), host=args.web_host,
                                                   port=args.web_port, log_level='info', access_log=False))
        web_thread = threading.Thread(target=web_server.run, daemon=True)
        web_thread.start()
        deadline = time.monotonic() + 30
        while not web_server.started and web_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        if not web_server.started:
            monitor.close()
            raise RuntimeError('解码端展示服务未能启动，请检查网页端口')
        hardware = HardwareDecoder(args.bind, args.h264_port, args.h265_port)
        hardware.start()
        monitor.attach_hardware(hardware)
        print(f'硬件对比接收端口：{args.bind}:{args.h264_port}/{args.h265_port}', flush=True)
        if not args.no_browser:
            host = '127.0.0.1' if args.web_host == '0.0.0.0' else args.web_host
            webbrowser.open(f'http://{host}:{args.web_port}')
    try:
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((args.bind, args.port))
            server.listen(1)
            server.settimeout(.5)
            print(f'等待编码端 {args.bind}:{args.port}；Ctrl+C 结束', flush=True)
            while monitor is None or not monitor.exit_requested.is_set():
                try:
                    conn, peer = server.accept()
                except socket.timeout:
                    continue
                print(f'编码端连接：{peer}', flush=True)
                code = serve_session(conn, monitor=monitor)
                print(f'会话进程退出（{code}）；继续等待下一次连接', flush=True)
    finally:
        if hardware is not None:
            hardware.stop()
        if monitor is not None:
            monitor.close()
            web_server.should_exit = True
            web_thread.join(timeout=3)


if __name__ == '__main__':
    main()
