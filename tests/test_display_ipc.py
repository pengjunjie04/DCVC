import multiprocessing
import unittest
from demo.display_ipc import PreviewMailbox


class PreviewMailboxTests(unittest.TestCase):
    def test_latest_group_is_atomic_bounded_and_read_does_not_wait_on_dead_owner(self):
        box = PreviewMailbox(multiprocessing.get_context('spawn'), capacity=1024)
        self.assertTrue(box.publish({'total_frames':8}, [b'a',b'bc']))
        seq, info, frames = box.read(0)
        self.assertEqual(frames, [b'a',b'bc'])
        self.assertIsNone(box.read(seq))
        self.assertFalse(box.publish({}, [b'x'*2048]))
        box.lock.acquire()
        try:
            self.assertIsNone(box.read(0))
            self.assertFalse(box.publish({}, [b'never block']))
        finally:
            box.lock.release()
        self.assertTrue(box.publish({'total_frames':16}, [b'latest']))
        self.assertEqual(box.read(seq)[2], [b'latest'])
