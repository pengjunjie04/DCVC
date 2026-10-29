from collections import deque
import threading
import time


class WindowStats:
    def __init__(self, seconds=2, clock=time.monotonic):
        self.seconds = seconds
        self.clock = clock
        self.started = clock()
        self.events = deque()
        self.frames = self.size = 0
        self.lock = threading.Lock()

    def add(self, frames=0, size=0):
        with self.lock:
            self.events.append((self.clock(), frames, size))
            self.frames += frames
            self.size += size

    def snapshot(self):
        with self.lock:
            now = self.clock()
            while self.events and self.events[0][0] <= now - self.seconds:
                self.events.popleft()
            elapsed = max(min(now - self.started, self.seconds), 1e-6)
            return {'fps': sum(x[1] for x in self.events) / elapsed,
                    'mbps': sum(x[2] for x in self.events) * 8 / elapsed / 1e6,
                    'frames': self.frames, 'bytes': self.size}
