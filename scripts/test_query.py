import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine('postgresql+asyncpg://jarvis:troque-esta-senha@127.0.0.1:5433/jarvis')
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT role, content, tool_calls, tool_call_id, created_at FROM chat_messages ORDER BY created_at DESC LIMIT 5"))
        rows = result.fetchall()
        for row in reversed(rows):
            print(f"[{row.role}] content={row.content}, tool_calls={row.tool_calls}, tool_call_id={row.tool_call_id}")

if __name__ == "__main__":
    asyncio.run(main())
