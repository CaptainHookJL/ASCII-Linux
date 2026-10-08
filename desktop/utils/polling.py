"""Periodic read-only snapshots without running Linux tool calls on the UI thread."""
import threading
import time


class SnapshotPoller:
    def __init__(self, read, apply, interval=2.0):
        self.read = read
        self.apply = apply
        self.interval = interval
        self.next_due = 0.0
        self.thread = None
        self.lock = threading.Lock()
        self.result = None
        self.error = None
        self.last_error = None
        self.finished = False
        self.loaded = False

    def request(self):
        self.next_due = 0.0

    def _read(self):
        try:
            result = self.read()
            with self.lock:
                self.result = result
                self.error = None
        except Exception as error:
            with self.lock:
                self.result = None
                self.error = error
        finally:
            with self.lock:
                self.finished = True

    def poll(self, enabled):
        now = time.monotonic()
        with self.lock:
            finished, result, error = self.finished, self.result, self.error
        if self.thread is not None and finished:
            self.thread.join()
            self.thread = None
            self.last_error = error
            if error is None:
                self.apply(result)
                self.loaded = True
            self.next_due = now + self.interval
        if enabled and self.thread is None and now >= self.next_due:
            with self.lock:
                self.finished = False
            # Snapshots are read-only; they need not delay logout or write files.
            self.thread = threading.Thread(target=self._read, daemon=True)
            self.thread.start()
