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
from datetime import datetime, timezone
from . import config

MAX_HOLD_HOURS = 18   # FX runner can breathe longer than a gold scalp, but a
                      # trade that hasn't resolved by now exits at market so one
                      # stuck trade can never freeze a pair.


def _conn():
    c = sqlite3.connect(str(config.LEDGER_PATH))
    c.execute("""CREATE TABLE IF NOT EXISTS open_trades(
        pair TEXT PRIMARY KEY, direction TEXT, entry REAL, sl REAL,
        tp1 REAL, tp2 REAL, tp3 REAL, hit1 INT DEFAULT 0, hit2 INT DEFAULT 0, opened TEXT)""")
    try:
        c.execute("ALTER TABLE open_trades ADD COLUMN opened TEXT")
    except sqlite3.OperationalError:
        pass
    c.execute("""CREATE TABLE IF NOT EXISTS closed_trades(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
        pair TEXT, direction TEXT, entry REAL, exit REAL,
        result TEXT, pips REAL)""")
    return c


def _log_close(c, pair, direction, entry, exit_, result, pips):
    from datetime import datetime
    c.execute("INSERT INTO closed_trades(ts,pair,direction,entry,exit,result,pips) "
              "VALUES(?,?,?,?,?,?,?)",
              (datetime.utcnow().isoformat(), pair, direction, entry, exit_, result, pips))


def open_trade(sig) -> None:
    c = _conn()
    c.execute("INSERT OR REPLACE INTO open_trades"
              "(pair,direction,entry,sl,tp1,tp2,tp3,hit1,hit2,opened) VALUES(?,?,?,?,?,?,?,0,0,?)",
              (sig.pair, sig.direction, sig.entry, sig.sl, sig.tp1, sig.tp2, sig.tp3,
               datetime.now(timezone.utc).isoformat()))
    c.commit(); c.close()


def _alert(pair, direction, body) -> str:
    return "VELDRIN MANAGE — %s %s\n%s" % (pair, direction, body)


def check(price_by_pair: dict) -> list[str]:
    """Compare live price to each open trade's levels; return VIP alerts."""
    c = _conn()
    alerts = []
    rows = c.execute("SELECT pair,direction,entry,sl,tp1,tp2,tp3,hit1,hit2,opened "
                     "FROM open_trades").fetchall()
    now = datetime.now(timezone.utc)
    for pair, direction, entry, sl, tp1, tp2, tp3, hit1, hit2, opened in rows:
        px = price_by_pair.get(pair)
        if px is None:
            continue
        longd = direction in ("LONG", "BUY")
        reached = (lambda lvl: px >= lvl) if longd else (lambda lvl: px <= lvl)
        sl_hit = (px <= sl) if longd else (px >= sl)
        pip = 0.01 if pair.endswith("JPY") else 0.0001
        pips = lambda lvl: round(abs(lvl - entry) / pip, 1)

        # TIME STOP: legacy stuck row (no opened) or held too long -> exit at market.
        try:
            age_h = (now - datetime.fromisoformat(opened)).total_seconds() / 3600 if opened else 1e9
        except Exception:
            age_h = 1e9
        if age_h > MAX_HOLD_HOURS:
            sign = 1 if longd else -1
            p = round((px - entry) / pip * sign, 1)
            res = "WIN" if p > 0 else ("LOSS" if p < 0 else "BREAKEVEN")
            _log_close(c, pair, direction, entry, px, res, p)
            alerts.append(_alert(pair, direction,
                "Time exit — %dh with no target, closed at market (%+.1f pips)." % (int(MAX_HOLD_HOURS), p)))
            c.execute("DELETE FROM open_trades WHERE pair=?", (pair,))
            continue

        if sl_hit:
            _log_close(c, pair, direction, entry, sl, "LOSS", -pips(sl))
            alerts.append(_alert(pair, direction,
                "SL hit — trade closed (-%.1f pips). Capital protected, on to the next."
                % pips(sl)))
            c.execute("DELETE FROM open_trades WHERE pair=?", (pair,))
            continue
        if reached(tp3):
            _log_close(c, pair, direction, entry, tp3, "WIN", pips(tp3))
            alerts.append(_alert(pair, direction,
                "TP3 hit 🎯 — close the runner (+%.1f pips). Trade DONE. Full 1:3+ banked."
                % pips(tp3)))
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
