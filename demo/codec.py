"""Thin adapter around Microsoft's real HT-S entropy-coded bitstream API."""
from pathlib import Path
import sys
import struct
import gc

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'vendor' / 'DCVC'
CHECKPOINTS = ROOT / 'checkpoints'


def release_workspace():
    gc.collect()
    native = sys.modules.get('inference_extensions_cuda')
    if native is not None:
        native.clear_tensor_pool()
        sys.modules['torch'].cuda.empty_cache()


def readiness():
    import importlib.util
    issues = []
    for name in ('torch', 'MLCodec_extensions_cpp', 'inference_extensions_cuda'):
        if importlib.util.find_spec(name) is None:
            issues.append(f'缺少 {name}，请运行 tools/build_codec.sh')
    for name in ('cvpr2026_image.pth.tar', 'cvpr2026_video_hts.pth.tar'):
        path = CHECKPOINTS / name
        if not path.is_file() or path.stat().st_size < 1024:
            issues.append(f'缺少或无效的模型权重 checkpoints/{name}')
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
    streams = meta['ec']
    offsets_count = max(0, streams // 2 - 1 + streams % 2) if streams >= 3 else 0
    header = offsets_count * 4
    if len(payload) < header + 4:
        raise ValueError('rANS 码流缺少状态或偏移头')
    offsets = list(struct.unpack_from('<' + 'i' * offsets_count, payload)) if offsets_count else []
    boundaries = [0, *offsets, len(payload) - header]
    if any(end - start < 4 for start, end in zip(boundaries, boundaries[1:])):
        raise ValueError('rANS 子码流偏移越界或过短')


class Codec:
    def close(self):
        self.torch.cuda.synchronize()
        self.i = self.p = self.stream = None
        self.torch.cuda.empty_cache()

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
        self.runtime = {'torch':str(torch.__version__), 'cuda':torch.version.cuda,
                        'cudnn':torch.backends.cudnn.version(),
                        'gpu':list(torch.cuda.get_device_capability())}
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
        self.decode_dimensions = None
        self.groups = 0

    def encode(self, frames, qp):
        torch = self.torch
        from src.utils.transforms import rgb2ycbcr
        torch.cuda.set_stream(self.stream)
        with torch.inference_mode():
            if len(frames) != (1 if self.first else 8):
                raise ValueError('HT-S 首帧需 1 帧，其后每组需 8 帧')
            height, width = frames[0].shape[:2]
            # Copy all frames to one contiguous CPU batch, then transfer once. This
            # avoids a CUDA stream submission for every frame in the group.
            import numpy as np
            batch_rgb = np.stack(frames, axis=0)
            # The model is FP16. Keeping the color transform in FP16 avoids a
            # float32 intermediate and cuts GPU memory traffic for every group.
            x = torch.from_numpy(batch_rgb).permute(0, 3, 1, 2).cuda().half()
            x = rgb2ycbcr(x.div_(255)).sub_(.5)
            x = x.reshape(1, len(frames) * 3, height, width).contiguous(
                memory_format=torch.channels_last)
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
            if self.first:
                meta['runtime'] = dict(self.runtime)
            self.first = False
            self.groups += 1
            return meta, result['bit_stream']

    def decode(self, packet):
        meta, payload = packet
        validate_packet(meta, payload)
        if meta['type'] == 'I':
            from .runtime import validate_runtime
            validate_runtime(meta.get('runtime'), self.runtime)
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
                self.decode_dimensions = (meta['width'], meta['height'])
            else:
                if not self.decoded_first:
                    raise ValueError('P 帧前必须收到 I 帧')
                if (meta['width'], meta['height']) != self.decode_dimensions:
                    raise ValueError('分辨率修改后必须重启流并发送 I 帧')
                result = self.p.decompress(payload, sps, meta['qp'], meta['ec'], meta['reset'])
            frames = result['x_hat']
            if not isinstance(frames, list):
                frames = [frames]
            # Convert and pack the whole group on the GPU before one host copy.
            # Per-frame .cpu() calls serialize the stream eight times.
            cropped_frames = [frame[:, :, :meta['height'], :meta['width']] for frame in frames]
            cropped = cropped_frames[0] if len(cropped_frames) == 1 else torch.cat(cropped_frames, dim=0)
            if cropped.dtype == getattr(torch, 'float16', None):
                # Upstream's helper promotes to float32. The same BT.709 inverse
                # in FP16 saves about 6 ms per eight-frame group with <=1 LSB change.
                y, cb, cr = (cropped + .5).chunk(3, -3)
                r = y + 1.5748 * (cr - .5)
                b = y + 1.8556 * (cb - .5)
                g = (y - .2126 * r - .0722 * b) / .7152
                rgb = torch.cat((r, g, b), -3).clamp_(0., 1.)
            else:
                rgb = ycbcr2rgb(cropped + .5)
            packed = rgb.mul(255).round().clamp(0, 255).byte().permute(0, 2, 3, 1).contiguous().cpu().numpy()
            torch.cuda.synchronize()
            return [frame for frame in packed]
