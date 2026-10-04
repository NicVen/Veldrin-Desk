"""Pause switch. Run: python -m unittest desk.test_pause"""
import sqlite3
import unittest

from . import config, dispatch, loop


class Pause(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self._send, dispatch.send_vip = dispatch.send_vip, lambda t: self.sent.append(t) or True
        self._paused = config.PAUSED
        self.conn = sqlite3.connect(":memory:")

    def tearDown(self):
        dispatch.send_vip, config.PAUSED = self._send, self._paused

    def test_note_sent_once(self):
        config.PAUSED = True
        loop._announce_pause(self.conn)
        loop._announce_pause(self.conn)          # restart: no second note
        self.assertEqual(self.sent, [config.PAUSE_NOTE])

    def test_resume_forgets_so_next_pause_tells_again(self):
        config.PAUSED = True
        loop._announce_pause(self.conn)
        config.PAUSED = False
        loop._announce_pause(self.conn)
        config.PAUSED = True
        loop._announce_pause(self.conn)
        self.assertEqual(len(self.sent), 2)


if __name__ == "__main__":
    unittest.main()
