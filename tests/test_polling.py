"""Blocking/erroring snapshot sources must not block or mutate the curses thread."""
import threading
import time
import unittest

from desktop.utils.polling import SnapshotPoller


class PollingTests(unittest.TestCase):
    def finish(self, poller, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            poller.poll(False)
            if poller.thread is None:
                return
            time.sleep(.005)
        self.fail('Snapshot did not complete')

    def test_slow_source_coalesces_requests_and_applies_on_main_thread(self):
        release, started = threading.Event(), threading.Event()
        owner = threading.get_ident()
        applications, calls = [], []

        def read():
            calls.append(threading.get_ident())
            started.set()
            self.assertTrue(release.wait(timeout=2))
            return ('stable snapshot',)

        poller = SnapshotPoller(read, lambda value: applications.append((threading.get_ident(), value)))
        try:
            before = time.monotonic()
            poller.poll(True)
            self.assertLess(time.monotonic() - before, .5)
            self.assertTrue(started.wait(timeout=1))
            for _ in range(3):
                poller.request()
                poller.poll(True)
            self.assertEqual(len(calls), 1)
            self.assertNotEqual(calls[0], owner)
            self.assertEqual(applications, [])
        finally:
            release.set()
        self.finish(poller)
        self.assertEqual(applications, [(owner, ('stable snapshot',))])
        self.assertTrue(poller.loaded)

    def test_failed_refresh_retains_snapshot_and_later_success_clears_error(self):
        responses = iter([('good',), OSError('source unavailable'), ('recovered',)])
        applications = []

        def read():
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        poller = SnapshotPoller(read, applications.append)
        poller.poll(True)
        self.finish(poller)
        poller.request()
        poller.poll(True)
        self.finish(poller)
        self.assertEqual(applications, [('good',)])
        self.assertIsInstance(poller.last_error, OSError)
        self.assertTrue(poller.loaded)
        poller.request()
        poller.poll(True)
        self.finish(poller)
        self.assertEqual(applications, [('good',), ('recovered',)])
        self.assertIsNone(poller.last_error)


if __name__ == '__main__':
    unittest.main()
