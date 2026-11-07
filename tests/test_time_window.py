import unittest
from scripts import common


class TimeWindowTests(unittest.TestCase):
    def window(self, value):
        self.assertTrue(hasattr(common, 'TimeWindow'), 'TimeWindow is not implemented')
        return common.TimeWindow.from_config({'time_range': value})

    def test_half_open_offset_equivalence(self):
        window = self.window({'start': '2024-01-02T00:00:00+08:00', 'end': '2024-01-02T01:00:00+08:00'})
        self.assertTrue(window.contains(1704124800))
        self.assertTrue(window.contains(1704128399))
        self.assertFalse(window.contains(1704128400))
        self.assertFalse(window.contains(1704124799))
        utc = self.window({'start': '2024-01-01T16:00:00Z', 'end': '2024-01-01T17:00:00Z'})
        self.assertEqual(window.sql(), utc.sql())

    def test_unbounded_and_one_sided(self):
        self.assertTrue(self.window(None).contains(-1))
        self.assertTrue(self.window({'start': '2024-01-01T00:00:00Z'}).contains(1704067200))
        self.assertFalse(self.window({'end': '2024-01-01T00:00:00Z'}).contains(1704067200))

    def test_invalid_range_rejected(self):
        for value in [
            {'start': '2024-01-01'},
            {'start': '2024-01-01T00:00:00'},
            {'start': 'bad'},
            {'start': '2024-01-01T00:00:00Z', 'end': '2024-01-01T00:00:00Z'},
            {'start': '2024-01-02T00:00:00Z', 'end': '2024-01-01T00:00:00Z'},
            {'strat': '2024-01-01T00:00:00Z'},
            {'start': '2024-01-01T00:00:00.1Z'},
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.window(value)


if __name__ == '__main__':
    unittest.main()
