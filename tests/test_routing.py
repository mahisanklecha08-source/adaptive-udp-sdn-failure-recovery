import unittest

from routing import choose_path, forwarding_ports


class RoutingTests(unittest.TestCase):
    def test_primary_and_backup(self):
        self.assertEqual(choose_path(), (1, 2, 4))
        self.assertEqual(choose_path({(2, 4)}), (1, 3, 4))
        self.assertEqual(choose_path({(1, 2)}), (1, 3, 4))
        self.assertIsNone(choose_path({(2, 4), (3, 4)}))
        self.assertEqual(choose_path(active_switches={1, 3, 4}), (1, 3, 4))

    def test_forward_and_ack_ports(self):
        forward, reverse = forwarding_ports((1, 3, 4), 4)
        self.assertEqual(forward, {1: 3, 3: 2, 4: 3})
        self.assertEqual(reverse, {1: 4, 3: 1, 4: 2})


if __name__ == "__main__":
    unittest.main()
