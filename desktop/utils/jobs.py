"""Run filesystem work off the curses thread with a bounded progress snapshot."""
import threading


class FileJob:
    def __init__(self, label, operation):
        self.label = label
        self.lock = threading.Lock()
        self.done_bytes = 0
        self.total_bytes = 0
        self.finished = False
        self.result = None
        self.error = None
        # Finish writes before Python exits; UI prevents leaving while work runs.
        self.thread = threading.Thread(target=self._run, args=(operation,), daemon=False)
        self.thread.start()

    def report(self, done, total):
        with self.lock:
            self.done_bytes, self.total_bytes = done, total

    def _run(self, operation):
        try:
            result = operation(progress=self.report)
            with self.lock:
                self.result = result
        except Exception as error:
            with self.lock:
                self.error = error
        finally:
            with self.lock:
                self.finished = True

    def snapshot(self):
        with self.lock:
            return self.finished, self.done_bytes, self.total_bytes, self.result, self.error
