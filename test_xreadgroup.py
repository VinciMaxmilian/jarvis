import redis.asyncio as redis
import asyncio

async def test():
    r = redis.from_url('redis://redis:6379/0', decode_responses=True)
    STREAM_NAME = "jarvis:events"
    GROUP_NAME = "jarvis_workers"
    
    try:
        await r.xgroup_create(STREAM_NAME, GROUP_NAME, mkstream=True, id="0")
    except redis.exceptions.ResponseError:
        pass

    try:
        response = await r.xreadgroup(
            GROUP_NAME, 
            "test_consumer", 
            {STREAM_NAME: ">"}, 
            count=10, 
            block=1000
        )
        print("Response:", response)
    except Exception as e:
        print("Error:", type(e), str(e))

asyncio.run(test())
