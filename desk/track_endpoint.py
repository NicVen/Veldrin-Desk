"""Read-only track-record HTTP endpoint.

Serves the desk's verified ledger as /track_record.json so STAALWAG HQ can pull
it into the firm-wide single pane. Runs in a DAEMON THREAD alongside the signal
loop -- read-only, never writes, and if it ever fails it cannot stop trading.

Shape matches HQ's remote source: {product, signals, outcomes:[{result,pnl_usd,equity_after}]}.
"""
import json
import os
import sqlite3
import threading
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
            for r in conn.execute("SELECT result, pips FROM closed_trades ORDER BY ts ASC"):
                rows.append({"result": r[0], "pnl_usd": r[1],
                             "pips": r[1], "equity_after": None})
        except Exception:
            pass
    finally:
        conn.close()
    return {"product": "VELDRIN FX", "pair": getattr(config, "PAIR", "FX"),
            "unit": "pips", "signals": n, "outcomes": rows}


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/track_record.json"):
            try:
                body = json.dumps(_payload()).encode()
            except Exception as e:  # noqa: BLE001
                body = json.dumps({"error": str(e)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            body = b"STAALWAG desk OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_in_thread():
    port = int(os.getenv("PORT", "8080"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("[track] serving /track_record.json on :%d" % port)
