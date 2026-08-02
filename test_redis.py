import redis.asyncio as redis
import asyncio

async def test():
    r = redis.from_url('redis://127.0.0.1:6379/0')
    print(type(r.xreadgroup))
    # Test if it returns a coroutine
    coro = r.xreadgroup('a','b',{'c':'>'})
    print(type(coro))

asyncio.run(test())
