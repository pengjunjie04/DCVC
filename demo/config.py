from dataclasses import dataclass
import ipaddress


@dataclass(frozen=True)
class Settings:
    width: int = 640
    height: int = 360
    fps: int = 30
    qp: int = 32
    mode: str = 'local'
    source: str = 'synthetic'
    camera: str = '/dev/video0'
    peer: str = ''
    bind: str = ''
    port: int = 9860

    def validate(self):
        for name, low, high in [('width', 64, 3840), ('height', 64, 2160),
                                ('fps', 1, 120), ('qp', 0, 63), ('port', 1, 65535)]:
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} 必须是 {low}–{high} 之间的整数')
        if self.width % 2 or self.height % 2:
            raise ValueError('分辨率宽高必须为偶数')
        if self.mode not in ('local', 'send', 'capture'):
            raise ValueError('未知运行模式')
        if self.source not in ('synthetic', 'camera'):
            raise ValueError('未知视频源')
        if self.source == 'camera' and not self.camera.startswith('/dev/video'):
            raise ValueError('请选择 /dev/video 摄像头节点')
        if self.mode == 'send':
            for value in (self.bind, self.peer):
                try:
                    address = ipaddress.IPv4Address(value)
                except ipaddress.AddressValueError as exc:
                    raise ValueError('发送模式必须指定两端有线 IPv4 地址') from exc
                if address.is_unspecified or address.is_multicast or address.is_loopback:
                    raise ValueError('发送模式请使用有线网卡地址')
        return self
