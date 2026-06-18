# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN SQLite ledger. Append-only. This is the forex track record."""
import sqlite3
from datetime import datetime
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, pair TEXT NOT NULL, direction TEXT NOT NULL,
    entry REAL, sl REAL, tp REAL, lots REAL, rr REAL,
    tf_1h TEXT, tf_4h TEXT,
    selfcheck_passed INTEGER NOT NULL, selfcheck_report TEXT,
    dispatched INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL REFERENCES signals(id),
    closed_ts TEXT NOT NULL, result TEXT NOT NULL,
    pnl_usd REAL NOT NULL, equity_after REAL
);
CREATE TABLE IF NOT EXISTS faults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, reason TEXT NOT NULL, dispatched INTEGER NOT NULL
);
"""


def connect(path=None):
    conn = sqlite3.connect(str(path or config.LEDGER_PATH))
    conn.executescript(SCHEMA)
    return conn


def log_signal(conn, sig, lots, report, dispatched) -> int:
    risk = abs(sig.entry - sig.sl)
    reward = abs(sig.tp - sig.entry)
    rr = round(reward / risk, 2) if risk > 0 else 0
    cur = conn.execute(
        "INSERT INTO signals (ts,pair,direction,entry,sl,tp,lots,rr,"
        "tf_1h,tf_4h,selfcheck_passed,selfcheck_report,dispatched) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sig.ts.isoformat(), sig.pair, sig.direction, sig.entry, sig.sl,
         sig.tp, lots, rr, sig.tf_1h, sig.tf_4h,
         int(report.passed), report.text(), int(dispatched)))
    conn.commit()
    return cur.lastrowid


def log_fault(conn, reason, dispatched, ts=None):
    conn.execute("INSERT INTO faults (ts,reason,dispatched) VALUES (?,?,?)",
                 ((ts or datetime.now(config.NZT)).isoformat(),
                  reason, int(dispatched)))
    conn.commit()


def weekly_summary(conn) -> str:
    rows = conn.execute(
        "SELECT o.result, o.pnl_usd, s.pair "
        "FROM outcomes o JOIN signals s ON s.id=o.signal_id "
        "ORDER BY o.id").fetchall()
    if not rows:
        return "VELDRIN WEEKLY SUMMARY\nNo closed trades yet."

    wins = [p for r, p, _ in rows if r == "WIN"]
    losses = [p for r, p, _ in rows if r == "LOSS"]
    total = len(rows)
    win_rate = len(wins) / total * 100 if total else 0
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")

    equity, peak, max_dd = 0.0, 0.0, 0.0
    for _, p, _ in rows:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    pair_counts = {}
    for _, _, pair in rows:
        pair_counts[pair] = pair_counts.get(pair, 0) + 1

    return ("VELDRIN WEEKLY SUMMARY (forex majors, append-only ledger)\n"
            "Closed trades: %d | Win rate: %.1f%%\n"
            "Profit factor: %s | Net P/L: %.2f USD\n"
            "Max drawdown: %.2f USD\n"
            "Pairs traded: %s\n"
            "Risk per trade: 1%% fixed. Daily cap: 2%%. "
            "Max 2 positions. No martingale."
            % (total, win_rate,
               ("%.2f" % pf) if pf != float("inf") else "inf",
               gross_win - gross_loss, max_dd,
               ", ".join("%s(%d)" % (p, c) for p, c in pair_counts.items())))
