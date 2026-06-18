# Copyright (c) 2026. All rights reserved. Proprietary - no license granted.
"""VELDRIN orchestrated loop.

One process owns the schedule. Every cycle scans all 6 major pairs:
  intake (all pairs) -> for each pair: signal -> self-check -> gates -> dispatch
Anti-flood, session filter, correlation block and dual-TF confirmation all
fire before any signal reaches Telegram.
"""
import time
from datetime import datetime, timezone

from . import config, dispatch, gates, ledger, selfcheck
from . import signal as signal_mod
from .intake import VeldrinFeed


def _market_closed(now: datetime) -> bool:
    wd = now.astimezone(timezone.utc).weekday()
    return wd == 5 or (wd == 6 and now.astimezone(timezone.utc).hour < 22)


def main():
    print("VELDRIN desk starting. Pairs: %s. Cycle: %ds. All times NZT."
          % (", ".join(config.PAIRS), config.CYCLE_SECONDS))

    feed = VeldrinFeed()
    conn = ledger.connect()

    state = {
        "equity": 10000.0,
        "day_start_equity": 10000.0,
        "open_positions": {},    # pair -> direction
        "recent_keys": {},       # signal.key() -> datetime
        "pair_day_count": {},    # pair -> int
        "total_day_count": 0,
        "day": datetime.now(config.NZT).date(),
        "market_closed_notified": False,
    }

    while True:
        started = time.monotonic()
        now = datetime.now(config.NZT)

        # Weekend / market closed handling
        if _market_closed(now):
            if not state["market_closed_notified"]:
                dispatch.send("VELDRIN [RAILWAY]\nMarket closed (weekend). "
                              "Desk monitoring. Next open: Sun ~22:00 UTC.")
                state["market_closed_notified"] = True
            time.sleep(1800)
            continue
        else:
            if state["market_closed_notified"]:
                dispatch.send("VELDRIN [RAILWAY]\nMarket open. "
                              "Scanning %d pairs." % len(config.PAIRS))
            state["market_closed_notified"] = False

        # NZT day rollover
        if state["day"] != now.date():
            state["day"] = now.date()
            state["day_start_equity"] = state["equity"]
            state["pair_day_count"] = {}
            state["total_day_count"] = 0

        heartbeats = {"intake": False, "signal": False,
                      "gates": False, "ledger": False}

        try:
            quotes = feed.refresh()
            heartbeats["intake"] = True
        except Exception as e:
            reason = "Intake failed: %r" % e
            ok = dispatch.send_fault(reason)
            ledger.log_fault(conn, reason, ok, now)
            time.sleep(max(0.0, config.CYCLE_SECONDS - (time.monotonic() - started)))
            continue

        for pair, quote in quotes.items():
            try:
                sig = signal_mod.generate(quote)
                heartbeats["signal"] = True
                heartbeats["gates"] = True
                heartbeats["ledger"] = True
            except Exception as e:
                ledger.log_fault(conn, "%s signal error: %r" % (pair, e), False, now)
                continue

            if sig is None:
                continue

            report = selfcheck.run(
                sig, quote,
                state["recent_keys"],
                state["pair_day_count"],
                state["total_day_count"],
                heartbeats, now)

            if report.fault:
                ok = dispatch.send_fault(report.fault)
                ledger.log_fault(conn, report.fault, ok, now)
                continue

            if not report.passed:
                ledger.log_signal(conn, sig, 0.0, report, dispatched=False)
                continue

            decision = gates.check(
                state["equity"], state["day_start_equity"],
                state["open_positions"],
                sig.pair, sig.direction,
                sig.entry, sig.sl, now)

            if not decision.allowed:
                ledger.log_signal(conn, sig, 0.0, report, dispatched=False)
                if "CIRCUIT BREAKER" in decision.reason:
                    ok = dispatch.send_fault(decision.reason)
                    ledger.log_fault(conn, decision.reason, ok, now)
                continue

            msg = sig.message(decision.lots, quote.age_seconds(now))
            sent = dispatch.send(msg + "\n\n" + report.text())
            ledger.log_signal(conn, sig, decision.lots, report, dispatched=sent)

            if sent:
                state["recent_keys"][sig.key()] = now
                state["open_positions"][pair] = sig.direction
                state["pair_day_count"][pair] = \
                    state["pair_day_count"].get(pair, 0) + 1
                state["total_day_count"] += 1

        time.sleep(max(0.0, config.CYCLE_SECONDS - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
