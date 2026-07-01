# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN trade management — the core VIP value.

Tracks every dispatched signal and watches price each cycle, emitting
VIP-only alerts as the trade develops:
  TP1 -> close 50%, move SL to breakeven (trade is now risk-free)
  TP2 -> take more / trail tight, let the runner go
  TP3 -> close remainder, trade done
  SL  -> stopped out, protect capital

State lives in SQLite (same DB as the ledger) so alerts survive Railway
restarts. One open trade per pair.
"""
import sqlite3
from . import config


def _conn():
    c = sqlite3.connect(str(config.LEDGER_PATH))
    c.execute("""CREATE TABLE IF NOT EXISTS open_trades(
        pair TEXT PRIMARY KEY, direction TEXT, entry REAL, sl REAL,
        tp1 REAL, tp2 REAL, tp3 REAL, hit1 INT DEFAULT 0, hit2 INT DEFAULT 0)""")
    return c


def open_trade(sig) -> None:
    c = _conn()
    c.execute("INSERT OR REPLACE INTO open_trades"
              "(pair,direction,entry,sl,tp1,tp2,tp3,hit1,hit2) VALUES(?,?,?,?,?,?,?,0,0)",
              (sig.pair, sig.direction, sig.entry, sig.sl, sig.tp1, sig.tp2, sig.tp3))
    c.commit(); c.close()


def _alert(pair, direction, body) -> str:
    return "VELDRIN MANAGE — %s %s\n%s" % (pair, direction, body)


def check(price_by_pair: dict) -> list[str]:
    """Compare live price to each open trade's levels; return VIP alerts."""
    c = _conn()
    alerts = []
    rows = c.execute("SELECT pair,direction,entry,sl,tp1,tp2,tp3,hit1,hit2 "
                     "FROM open_trades").fetchall()
    for pair, direction, entry, sl, tp1, tp2, tp3, hit1, hit2 in rows:
        px = price_by_pair.get(pair)
        if px is None:
            continue
        longd = direction in ("LONG", "BUY")
        reached = (lambda lvl: px >= lvl) if longd else (lambda lvl: px <= lvl)
        sl_hit = (px <= sl) if longd else (px >= sl)

        if sl_hit:
            alerts.append(_alert(pair, direction,
                "SL hit — trade closed. Capital protected, on to the next."))
            c.execute("DELETE FROM open_trades WHERE pair=?", (pair,))
            continue
        if reached(tp3):
            alerts.append(_alert(pair, direction,
                "TP3 hit 🎯 — close the runner. Trade DONE. Full 1:3+ banked."))
            c.execute("DELETE FROM open_trades WHERE pair=?", (pair,))
            continue
        if not hit2 and reached(tp2):
            alerts.append(_alert(pair, direction,
                "TP2 hit ✅ — take more off / trail tight. Let the rest run for TP3."))
            c.execute("UPDATE open_trades SET hit2=1 WHERE pair=?", (pair,))
        if not hit1 and reached(tp1):
            alerts.append(_alert(pair, direction,
                "TP1 hit ✅ — close 50% and move SL to BREAKEVEN. Trade is risk-free now."))
            c.execute("UPDATE open_trades SET hit1=1 WHERE pair=?", (pair,))
    c.commit(); c.close()
    return alerts
