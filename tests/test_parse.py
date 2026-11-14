import datetime as dt
import unittest

from huchai.client import USER_AGENT
from huchai.parse import is_challenge, parse_observation


TODAY = dt.date(2026, 11, 14)


class ParseTests(unittest.TestCase):
    def test_user_agent_identifies_the_bot(self):
        self.assertIn("huchai-feed", USER_AGENT)
        self.assertNotIn("Mozilla", USER_AGENT)

    def test_yesterday_when_payload_has_no_date(self):
        observed = parse_observation({"sellcount": "1,071", "sellarea": "84122.73"}, today=TODAY)
        self.assertEqual(observed.date, "2026-11-13")
        self.assertEqual(observed.deals, 1071)
        self.assertEqual(observed.area, 84122.73)

    def test_wrapped_payload_and_explicit_date(self):
        observed = parse_observation(
            {"data": {"sellCount": 800, "date": "2026/11/12", "sellmoney": 12}},
            today=TODAY,
        )
        self.assertEqual(observed.date, "2026-11-12")
        self.assertEqual(observed.deals, 800)
        self.assertIsNone(observed.amount_yuan)

    def test_plausible_amount_is_kept(self):
        observed = parse_observation(
            {"sellcount": 1000, "sellarea": 80000, "sellmoney": 4_000_000_000, "date": "20261112"},
            today=TODAY,
        )
        self.assertEqual(observed.amount_yuan, 4_000_000_000)

    def test_rejects_empty_and_absurd_counts(self):
        for payload in ({"sellcount": 0}, {"sellcount": None}, {"sellcount": 50000}, [], {"note": "x"}):
            with self.assertRaises(ValueError):
                parse_observation(payload, today=TODAY)

    def test_rejects_a_future_date(self):
        with self.assertRaises(ValueError):
            parse_observation({"sellcount": 10, "date": "2026-11-15"}, today=TODAY)

    def test_challenge_detection_does_not_treat_5xx_as_a_wall(self):
        self.assertTrue(is_challenge(412, "nope"))
        self.assertTrue(is_challenge(403, "denied"))
        self.assertTrue(is_challenge(200, "<html><script>$_ts={}</script></html>"))
        self.assertFalse(is_challenge(503, "busy"))
        self.assertFalse(is_challenge(200, '{"sellcount": 800}'))


if __name__ == "__main__":
    unittest.main()
