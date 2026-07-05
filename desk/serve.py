"""Web entrypoint: signal loop + read-only track-record endpoint.

Starts the /track_record.json server in a daemon thread, then runs the normal
signal loop as the main thread. The endpoint lets STAALWAG HQ pull this desk's
verified record; it cannot block or crash the loop.
"""
from . import track_endpoint, loop

if __name__ == "__main__":
    track_endpoint.serve_in_thread()
    loop.main()
