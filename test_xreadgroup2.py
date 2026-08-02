import redis.asyncio as redis
import asyncio

async def test():
    r = redis.from_url('redis://redis:6379/0', decode_responses=True)
    try:
        ret = r.xreadgroup(
            "jarvis_workers", 
            "test_consumer", 
            {"jarvis:events": ">"}, 
            count=10, 
            block=1000
        )
        print("xreadgroup returned type:", type(ret))
        if type(ret) is list:
            print("It's a list!", ret)
        else:
            await ret
            print("Awaited successfully")
    except Exception as e:
        print("Error:", e)

asyncio.run(test())
