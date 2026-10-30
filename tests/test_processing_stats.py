import unittest
from demo.metrics import ProcessingStats


class ProcessingStatsTests(unittest.TestCase):
    def test_compute_speed_uses_processing_time_and_expires_while_idle(self):
        now = [0.0]
        stats = ProcessingStats(clock=lambda: now[0])
        stats.add(8, 40)
        now[0] = 1
        stats.add(8, 120)
        self.assertEqual(stats.snapshot()['fps'], 100)
        self.assertEqual(stats.snapshot()['frames'], 16)
        now[0] = 4
        self.assertEqual(stats.snapshot()['fps'], 0)
        self.assertEqual(stats.snapshot()['frames'], 16)

    def test_bad_timings_do_not_poison_rates(self):
        stats = ProcessingStats()
        for value in (None, float('nan'), float('inf'), -1, 0, 'oops', True):
            stats.add(8, value)
        self.assertEqual(stats.snapshot()['fps'], 0)
        stats.add(8, 80)
        self.assertAlmostEqual(stats.snapshot()['fps'], 100)
