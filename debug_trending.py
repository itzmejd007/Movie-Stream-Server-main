
import asyncio
import os
import sys
from datetime import datetime

# Add the project root to sys.path
sys.path.append(os.getcwd())

from Backend.helper.database import Database
from Backend.config import Telegram

async def test_trending():
    db = Database(Telegram.DATABASE, "projectS")
    await db.connect()
    try:
        print("Fetching trending media...")
        res = await db.get_trending_media(1, 10)
        print(f"Success! Found {len(res['results'])} results.")
        print(f"Total count: {res['total_count']}")
    except Exception as e:
        print(f"Caught error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await db.disconnect()

if __name__ == "__main__":
    asyncio.run(test_trending())
