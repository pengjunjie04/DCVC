"""Thin adapter around Microsoft's real HT-S entropy-coded bitstream API."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'vendor' / 'DCVC'
CHECKPOINTS = ROOT / 'checkpoints'


def readiness():
    import importlib.util
    issues = []
    for name in ('torch', 'MLCodec_extensions_cpp', 'inference_extensions_cuda'):
        if importlib.util.find_spec(name) is None:
            issues.append(f'缺少 {name}，请运行 tools/build_codec.sh')
    for name in ('cvpr2026_image.pth.tar', 'cvpr2026_video_hts.pth.tar'):
        if not (CHECKPOINTS / name).is_file():
            issues.append(f'缺少模型权重 checkpoints/{name}')
    return issues


def validate_packet(meta, payload):
    from .config import Settings
    if meta.get('type') not in ('I', 'P'):
        raise ValueError('未知帧类型')
    Settings(width=meta.get('width'), height=meta.get('height'), qp=meta.get('qp')).validate()
    if type(meta.get('ec')) is not int or not 1 <= meta['ec'] <= 8 or meta.get('reset') not in (0, 1):
        raise ValueError('无效熵编码标记')
    count = 1 if meta['type'] == 'I' else 8
    if meta.get('count') != count or not payload:
        raise ValueError('帧数或载荷无效')


class Codec:
    def __init__(self):
        issues = readiness()
        if issues:
            raise RuntimeError('；'.join(issues))
        sys.path.insert(0, str(UPSTREAM))
        import torch
        from src.models.image_model import DMCI
        from src.models.video_model_ht import DMC
        from src.utils.common import get_state_dict, ModelStructure
        if not torch.cuda.is_available():
            raise RuntimeError('PyTorch 无法使用 CUDA')
        self.torch = torch
        torch.set_num_threads(2)
        self.stream = torch.cuda.Stream()
        torch.cuda.set_stream(self.stream)
        self.i = DMCI().eval()
        self.p = DMC(model_structure=ModelStructure.HTS).eval()
        for net, name in ((self.i, 'cvpr2026_image.pth.tar'), (self.p, 'cvpr2026_video_hts.pth.tar')):
            net.load_state_dict(get_state_dict(str(CHECKPOINTS / name)))
            net.update(.15)
            net.half().cuda().to(memory_format=torch.channels_last)
        # Upstream decompress assumes a proxy already exists; a receiver never compresses.
        from inference_extensions_cuda import DMCIProxy
        self.i.proxy = DMCIProxy()
        self.i.proxy.set_param(self.i.add_cdf_to_state_dict(self.i.state_dict()), .15)
        self.first = True
        self.decoded_first = False
        self.groups = 0

    def encode(self, frames, qp):
        torch = self.torch
        from src.utils.transforms import rgb2ycbcr
        torch.cuda.set_stream(self.stream)
        with torch.inference_mode():
            if len(frames) != (1 if self.first else 8):
                raise ValueError('HT-S 首帧需 1 帧，其后每组需 8 帧')
            height, width = frames[0].shape[:2]
            tensors = []
            for rgb in frames:
                tensor = torch.from_numpy(rgb.copy()).permute(2, 0, 1).unsqueeze(0).cuda()
                tensors.append(rgb2ycbcr(tensor.float() / 255).half() - .5)
            x = torch.cat(tensors, 1).to(memory_format=torch.channels_last)
            right, bottom = self.i.get_padding_size(height, width, 16)
            reset = int(not self.first and self.groups % 16 == 0)
            if self.first:
                result = self.i.compress(x, qp, bottom, right)
                self.p.clear_dpb()
                self.p.add_ref_feature_from_frame(result['x_hat'])
            else:
                result = self.p.compress(x, qp, reset, bottom, right)
            torch.cuda.synchronize()
            meta = {'type': 'I' if self.first else 'P', 'width': width, 'height': height,
                    'qp': qp, 'ec': int(result['ec_parallel']), 'reset': reset, 'count': len(frames)}
            self.first = False
            self.groups += 1
            return meta, result['bit_stream']

    def decode(self, packet):
        meta, payload = packet
        validate_packet(meta, payload)
        torch = self.torch
        from src.utils.transforms import ycbcr2rgb
        torch.cuda.set_stream(self.stream)
        with torch.inference_mode():
            sps = {'height': meta['height'], 'width': meta['width']}
            if meta['type'] == 'I':
                result = self.i.decompress(payload, sps, meta['qp'], meta['ec'])
                self.p.clear_dpb()
                self.p.add_ref_feature_from_frame(result['x_hat'], apply_feature_adaptor=False)
                self.decoded_first = True
            else:
                if not self.decoded_first:
                    raise ValueError('P 帧前必须收到 I 帧')
                result = self.p.decompress(payload, sps, meta['qp'], meta['ec'], meta['reset'])
            frames = result['x_hat']
            if not isinstance(frames, list):
                frames = [frames]
            output = []
            for frame in frames:
                rgb = ycbcr2rgb(frame[:, :, :meta['height'], :meta['width']] + .5)
                output.append(rgb.mul(255).round().clamp(0, 255).byte().squeeze(0).permute(1, 2, 0).cpu().numpy())
            torch.cuda.synchronize()
            return output
