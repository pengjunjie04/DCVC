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
            now = self.clock()
            while self.events and self.events[0][0] <= now - self.seconds:
                self.events.popleft()
            self.events.append((now, frames, size))
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


class ProcessingStats:
    """Frames / accumulated codec time in a recent wall-time window."""
    def __init__(self, seconds=2, clock=time.monotonic):
        self.seconds, self.clock = seconds, clock
        self.events = deque()
        self.frames = 0
        self.lock = threading.Lock()

    def add(self, frames, milliseconds):
        import math
        if type(milliseconds) not in (int, float) or not math.isfinite(milliseconds) or not 0 < milliseconds <= 120000:
            return
        with self.lock:
            now = self.clock()
            while self.events and self.events[0][0] <= now - self.seconds:
                self.events.popleft()
            self.events.append((now, frames, milliseconds))
            self.frames += frames

    def snapshot(self):
        with self.lock:
            now = self.clock()
            while self.events and self.events[0][0] <= now - self.seconds:
                self.events.popleft()
            duration = sum(item[2] for item in self.events)
            frames = sum(item[1] for item in self.events)
            return {'fps': frames * 1000 / duration if duration else 0.,
                    'group_ms': self.events[-1][2] if self.events else None,
                    'frames': self.frames}
