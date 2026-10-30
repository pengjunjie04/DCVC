"""CPU check of the host image contract, without loading models or a CUDA context."""
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch

from demo.codec import Codec


class CodecLayoutTests(unittest.TestCase):
    def test_decoded_rgb_is_packed_for_opencv_without_channel_reordering(self):
        # A planar reconstruction exercises the layout returned by the model.
        reconstruction = torch.tensor([-.5, 0., .5]).reshape(1, 3, 1, 1).expand(1, 3, 64, 64).contiguous()
        codec = Codec.__new__(Codec)
        codec.torch = SimpleNamespace(
            inference_mode=torch.inference_mode,
            cuda=SimpleNamespace(set_stream=lambda _: None, synchronize=lambda: None))
        codec.stream = None
        codec.i = SimpleNamespace(decompress=lambda *args: {'x_hat': reconstruction})
        codec.p = SimpleNamespace(clear_dpb=lambda: None, add_ref_feature_from_frame=lambda *a, **kw: None)
        transforms = ModuleType('src.utils.transforms')
        transforms.ycbcr2rgb = lambda tensor: tensor
        metadata = dict(type='I', width=64, height=64, qp=32, ec=1, reset=0, count=1)
        with patch.dict(sys.modules, {'src.utils.transforms': transforms}):
            frames = codec.decode((metadata, b'1234'))
        self.assertEqual(frames[0].shape, (64, 64, 3))
        np.testing.assert_array_equal(frames[0][0, 0], [0, 128, 255])
        self.assertTrue(frames[0].flags.c_contiguous, 'OpenCV must receive packed RGB, not a planar strided view')


if __name__ == '__main__':
    unittest.main()
