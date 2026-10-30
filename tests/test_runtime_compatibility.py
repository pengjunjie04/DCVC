import unittest
from demo.codec import Codec
from demo.runtime import validate_runtime

RUNTIME={'torch':'2.5-test','cuda':'12.6','cudnn':92000,'gpu':[8,7]}

class RuntimeCompatibilityTests(unittest.TestCase):
    def test_identical_runtime_is_accepted(self):
        validate_runtime(dict(RUNTIME),RUNTIME)

    def test_different_or_missing_runtime_is_rejected(self):
        for sender in (None,{}, {**RUNTIME,'cudnn':90600}, {**RUNTIME,'torch':'other'}, {**RUNTIME,'cuda':'12.5'}, {**RUNTIME,'gpu':[8,9]}):
            with self.subTest(sender=sender), self.assertRaisesRegex(ValueError,'推理环境'):
                validate_runtime(sender,RUNTIME)

    def test_runtime_is_checked_before_native_decode(self):
        codec=Codec.__new__(Codec)
        codec.runtime=RUNTIME
        meta=dict(type='I',width=64,height=64,qp=32,ec=1,reset=0,count=1,runtime={**RUNTIME,'cudnn':90600})
        # No torch/model exists: rejection must happen before accessing either.
        with self.assertRaisesRegex(ValueError,'cudnn'):
            codec.decode((meta,b'1234'))
