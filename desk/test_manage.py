"""The record follows the alerts. Run: python -m unittest desk.test_manage"""
import os
import tempfile
import unittest
from types import SimpleNamespace

from . import config, manage

# EURUSD long: entry 1.1000, SL 20 pips, TP1/2/3 = 1R/2R/3R
SIG = SimpleNamespace(pair="EURUSD", direction="LONG", entry=1.1000, sl=1.0980,
                      tp1=1.1020, tp2=1.1040, tp3=1.1060)


class Scoring(unittest.TestCase):
    def setUp(self):
        config.LEDGER_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
        manage.open_trade(SIG)

    def run_prices(self, *prices):
        out = []
        for p in prices:
            out += manage.check({"EURUSD": p})
        c = manage._conn()
        rows = c.execute("SELECT result, pips FROM closed_trades").fetchall()
        c.close()
        return rows, out

    def test_straight_stop_is_full_loss(self):
        rows, _ = self.run_prices(1.0979)
        self.assertEqual(rows, [("LOSS", -20.0)])

    def test_tp1_then_back_to_entry_is_half_r(self):
        rows, out = self.run_prices(1.1021, 1.0999)
        self.assertEqual(rows, [("WIN", 10.0)])         # 50% x 20 pips, rest at 0
        self.assertIn("BREAKEVEN", out[0])

    def test_tp2_then_back_to_tp1_locks_one_r(self):
        rows, _ = self.run_prices(1.1021, 1.1041, 1.1019)
        self.assertEqual(rows, [("WIN", 20.0)])         # 10 banked + 50% x 20

    def test_tp3_is_two_r(self):
        rows, _ = self.run_prices(1.1021, 1.1041, 1.1061)
        self.assertEqual(rows, [("WIN", 40.0)])         # 10 banked + 50% x 60

    def test_one_close_per_trade(self):
        rows, _ = self.run_prices(1.1021, 1.0999, 1.0970)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
