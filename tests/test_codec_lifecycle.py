import unittest
from demo.codec import Codec


class CodecLifecycleTests(unittest.TestCase):
    def test_close_releases_model_and_stream_before_emptying_cache(self):
        events = []
        class Cuda:
            def synchronize(self):
                events.append('sync')
            def empty_cache(self):
                self_outer.assertIsNone(codec.i)
                self_outer.assertIsNone(codec.p)
                self_outer.assertIsNone(codec.stream)
                events.append('free')
        class Torch:
            cuda = Cuda()
        self_outer = self
        codec = Codec.__new__(Codec)
        codec.torch = Torch()
        codec.i = codec.p = codec.stream = object()
        codec.close()
        self.assertEqual(events, ['sync', 'free'])


if __name__ == '__main__':
    unittest.main()
