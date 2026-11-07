"""Bound pending wire data by both message count and retained string size."""
import asyncio
import sys


class MessageQueue(asyncio.Queue[str]):
    def __init__(self, maxsize=256, max_bytes=64 * 2**20, on_overflow=None):
        super().__init__(maxsize=maxsize)
        self.max_bytes = max_bytes
        self.bytes = 0
        self.on_overflow = on_overflow

    def put_nowait(self, item: str) -> None:
        size = sys.getsizeof(item)
        if self.bytes + size > self.max_bytes:
            raise asyncio.QueueFull
        super().put_nowait(item)
        self.bytes += size

    def get_nowait(self) -> str:
        item = super().get_nowait()
        self.bytes -= sys.getsizeof(item)
        return item
