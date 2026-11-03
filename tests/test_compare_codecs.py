import math
import unittest

from tools.compare_codecs import hardware_quality_points, interpolate_log_bitrate, psnr_from_mse


class CodecComparisonTests(unittest.TestCase):
    def test_psnr_from_mse_uses_255_peak(self):
        self.assertAlmostEqual(psnr_from_mse(1.), 20 * math.log10(255))
        self.assertAlmostEqual(psnr_from_mse(255 ** 2), 0.)

    def test_log_bitrate_interpolation_crosses_target_psnr(self):
        points = [
            {'bitrate_kbps':256., 'psnr_db':31.66},
            {'bitrate_kbps':512., 'psnr_db':34.89},
        ]
        matched = interpolate_log_bitrate(points, 33.)
        expected = math.exp(math.log(256.) + (33. - 31.66) / (34.89 - 31.66) * math.log(2.))
        self.assertAlmostEqual(matched['bitrate_kbps'], expected)
        self.assertAlmostEqual(matched['lower_psnr_db'], 31.66)
        self.assertAlmostEqual(matched['upper_psnr_db'], 34.89)

    def test_hardware_quality_points_use_measured_bitrate(self):
        rows = [
            {'codec':'H264', 'actual_kbps':121.0, 'psnr_db':28.7},
            {'codec':'H265', 'actual_kbps':120.0, 'psnr_db':29.1},
        ]
        self.assertEqual(hardware_quality_points(rows, 'H264'),
                         [{'bitrate_kbps':121.0, 'psnr_db':28.7}])


if __name__ == '__main__':
    unittest.main()
