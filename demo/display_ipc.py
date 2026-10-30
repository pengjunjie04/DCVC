"""Bounded latest-preview mailbox. A dead child cannot strand a pipe reader."""
import json
import struct

from .transport import MAX_PAYLOAD


class PreviewMailbox:
    def __init__(self, context, capacity=MAX_PAYLOAD):
        self.capacity = capacity
        self.data = context.RawArray('B', capacity)
        self.length = context.RawValue('I', 0)
        self.sequence = context.RawValue('Q', 0)
        self.lock = context.Lock()

    def publish(self, info, frames):
        meta = json.dumps({**info, 'sizes':list(map(len,frames))}, allow_nan=False).encode()
        data = struct.pack('!I', len(meta)) + meta + b''.join(frames)
        if len(data) > self.capacity or not self.lock.acquire(False):
            return False
        try:
            memoryview(self.data).cast('B')[:len(data)] = data
            self.length.value = len(data)
            self.sequence.value += 1
            return True
        finally:
            self.lock.release()

    def read(self, after):
        # The process can die holding the lock: never wait indefinitely.
        if not self.lock.acquire(timeout=.01):
            return None
        try:
            seq = self.sequence.value
            if seq == after:
                return None
            data = bytes(memoryview(self.data).cast('B')[:self.length.value])
        finally:
            self.lock.release()
        meta_size = struct.unpack_from('!I', data)[0]
        info = json.loads(data[4:4+meta_size])
        offset = 4 + meta_size
        frames = []
        for size in info.pop('sizes'):
            frames.append(data[offset:offset+size])
            offset += size
        return seq, info, frames
