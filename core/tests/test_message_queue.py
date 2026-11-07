import asyncio
import sys

import pytest

from badshop.server.queues import MessageQueue


def test_count_and_bytes_bound_even_a_few_large_unicode_messages():
    async def scenario():
        message = "🦆" * 100
        queue = MessageQueue(maxsize=2, max_bytes=sys.getsizeof(message))
        await queue.put(message)
        with pytest.raises(asyncio.QueueFull):
            queue.put_nowait("a")
        assert await queue.get() == message
        assert queue.bytes == 0
        queue.put_nowait("a")
        queue.put_nowait("b")
        with pytest.raises(asyncio.QueueFull):
            queue.put_nowait("c")
        assert [queue.get_nowait(), queue.get_nowait()] == ["a", "b"]
        assert queue.bytes == 0
    asyncio.run(scenario())
