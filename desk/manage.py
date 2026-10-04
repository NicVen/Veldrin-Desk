# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN trade management — the core VIP value.

Tracks every dispatched signal and watches price each cycle, emitting
VIP-only alerts as the trade develops:
  TP1 -> close 50%, move SL to breakeven (trade is now risk-free)
  TP2 -> move SL to TP1 (+1R locked on the rest)
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
    for col in ("opened TEXT", "banked REAL DEFAULT 0"):
        try:
            c.execute("ALTER TABLE open_trades ADD COLUMN " + col)
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
              "(pair,direction,entry,sl,tp1,tp2,tp3,hit1,hit2,opened,banked) VALUES(?,?,?,?,?,?,?,0,0,?,0)",
              (sig.pair, sig.direction, sig.entry, sig.sl, sig.tp1, sig.tp2, sig.tp3,
               datetime.now(timezone.utc).isoformat()))
    c.commit(); c.close()


def _alert(pair, direction, body) -> str:
    return "VELDRIN MANAGE — %s %s\n%s" % (pair, direction, body)


def _pips(pair, entry, level, longd) -> float:
    pip = 0.01 if pair.endswith("JPY") else 0.0001
    return round(((level - entry) if longd else (entry - level)) / pip, 1)


def _result(p: float) -> str:
    return "WIN" if p > 0 else ("LOSS" if p < 0 else "BREAKEVEN")


def check(price_by_pair: dict) -> list[str]:
    """Compare live price to each open trade's levels; return VIP alerts.

    The record follows exactly what the alerts tell subscribers to do:
      TP1 -> close 50% (+1R banked), SL to breakeven
      TP2 -> SL to TP1 (locks +1R on the rest)
      TP3 / SL / time exit -> close the rest
    A trade's pips = 50% at TP1 (if hit) + the rest at its exit.
    """
    c = _conn()
    alerts = []
    rows = c.execute("SELECT pair,direction,entry,sl,tp1,tp2,tp3,hit1,hit2,opened,banked "
                     "FROM open_trades").fetchall()
    now = datetime.now(timezone.utc)
    for pair, direction, entry, sl, tp1, tp2, tp3, hit1, hit2, opened, banked in rows:
        px = price_by_pair.get(pair)
        if px is None:
            continue
        longd = direction in ("LONG", "BUY")
        reached = (lambda lvl: px >= lvl) if longd else (lambda lvl: px <= lvl)
        sl_hit = (px <= sl) if longd else (px >= sl)
        part = 0.5 if hit1 else 1.0          # share of the position still open
        banked = banked or 0.0

        def close(exit_, body):
            total = round(banked + part * _pips(pair, entry, exit_, longd), 1)
            _log_close(c, pair, direction, entry, exit_, _result(total), total)
            alerts.append(_alert(pair, direction, body + " Trade total: %+.1f pips." % total))
            c.execute("DELETE FROM open_trades WHERE pair=?", (pair,))

        try:
            age_h = (now - datetime.fromisoformat(opened)).total_seconds() / 3600 if opened else 1e9
        except Exception:
            age_h = 1e9
        if age_h > MAX_HOLD_HOURS:
            close(px, "Time exit — %dh without the final target, close what's left at market."
                  % int(MAX_HOLD_HOURS))
            continue
        if sl_hit:
            if hit2:
                close(sl, "Price came back to TP1 — the rest closes at the locked TP1.")
            elif hit1:
                close(sl, "Back to entry — the rest closes at breakeven.")
            else:
                close(sl, "SL hit — trade closed. Capital protected, on to the next.")
            continue
        if reached(tp3):
            close(tp3, "TP3 hit 🎯 — close the rest. Trade DONE.")
            continue
        if not hit1 and reached(tp1):
            banked = round(0.5 * _pips(pair, entry, tp1, longd), 1)
            alerts.append(_alert(pair, direction,
                "TP1 hit ✅ — close 50%% (+%.1f pips banked) and move SL to BREAKEVEN (%s)."
                % (banked, entry)))
            c.execute("UPDATE open_trades SET hit1=1, sl=?, banked=? WHERE pair=?",
                      (entry, banked, pair))
            hit1, sl = 1, entry
        if hit1 and not hit2 and reached(tp2):
            alerts.append(_alert(pair, direction,
                "TP2 hit ✅ — move SL to TP1 (%s). +1R locked on the rest; let it run to TP3." % tp1))
            c.execute("UPDATE open_trades SET hit2=1, sl=? WHERE pair=?", (tp1, pair))
    c.commit(); c.close()
    return alerts
