"""Read-only track-record HTTP endpoint.

Serves the desk's verified ledger as /track_record.json so STAALWAG HQ can pull
it into the firm-wide single pane. Runs in a DAEMON THREAD alongside the signal
loop -- read-only, never writes, and if it ever fails it cannot stop trading.

Shape matches HQ's remote source: {product, signals, outcomes:[{result,pnl_usd,equity_after}]}.

Also serves /latest_signal.json for the local MT5 signal copier. That path
exposes the live actionable signal (entry/SL/TP) = paid VIP content, so it is
gated behind a shared secret (COPIER_TOKEN env). No token set -> 403, so the
VIP signal is never leaked publicly by accident.
"""
import json
import os
import sqlite3
import threading
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config


def _payload() -> dict:
    conn = sqlite3.connect("file:%s?mode=ro" % config.LEDGER_PATH, uri=True)
    rows = []
    try:
        try:
            n = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        except Exception:
            n = 0
        try:
            for r in conn.execute("SELECT result, pips, ts FROM closed_trades ORDER BY ts ASC"):
                rows.append({"result": r[0], "pnl_usd": r[1],
                             "pips": r[1], "ts": r[2], "equity_after": None})
        except Exception:
            pass
    finally:
        conn.close()
    return {"product": "VELDRIN FX", "pair": getattr(config, "PAIR", "FX"),
            "unit": "pips", "signals": n, "outcomes": rows}


def _latest_signal() -> dict:
    """Most recent DISPATCHED signal (the one the copier should trade), or {}."""
    conn = sqlite3.connect("file:%s?mode=ro" % config.LEDGER_PATH, uri=True)
    try:
        r = conn.execute(
            "SELECT id, ts, pair, direction, entry, sl, tp, lots "
            "FROM signals WHERE dispatched=1 ORDER BY id DESC LIMIT 1").fetchone()
    except Exception:
        r = None
    finally:
        conn.close()
    if not r:
        return {}
    return {"id": r[0], "ts": r[1], "pair": r[2], "direction": r[3],
            "entry": r[4], "sl": r[5], "tp": r[6], "lots": r[7],
            "product": "VELDRIN FX"}


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/track_record.json":
            try:
                body = json.dumps(_payload()).encode()
            except Exception as e:  # noqa: BLE001
                body = json.dumps({"error": str(e)}).encode()
            self._send(200, body)
        elif parsed.path == "/latest_signal.json":
            token = os.getenv("COPIER_TOKEN", "")
            given = (parse_qs(parsed.query).get("key") or [""])[0]
            if not token or given != token:
                self._send(403, b'{"error":"forbidden"}')
                return
            try:
                body = json.dumps(_latest_signal()).encode()
            except Exception as e:  # noqa: BLE001
                body = json.dumps({"error": str(e)}).encode()
            self._send(200, body)
        else:
            self._send(200, b"VELDRIN desk OK", "text/plain")


def serve_in_thread():
    port = int(os.getenv("PORT", "8080"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("[track] serving /track_record.json + /latest_signal.json on :%d" % port)
