import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from Backend.config import Telegram
from Backend.logger import LOGGER

async def fix_indexes():
    """
    Drops the unique index on tmdb_id if it exists and creates 
    a compound index on {tmdb_id: 1, title: 1} instead.
    """
    uri = Telegram.DATABASE
    if not uri:
        print("DATABASE environment variable not set.")
        return

    print(f"Connecting to database...")
    client = AsyncIOMotorClient(uri)
    db = client["projectS"] 
    
    for coll_name in ["movie", "tv"]:
        collection = db[coll_name]
        print(f"\n--- Checking collection: {coll_name} ---")
        
        # 1. List existing indexes
        indexes = await collection.list_indexes().to_list(None)
        print(f"Existing indexes: {[idx['name'] for idx in indexes]}")
        
        # 2. Identify the tmdb_id index
        tmdb_id_idx = None
        for idx in indexes:
            if "tmdb_id" in idx["key"] and len(idx["key"]) == 1:
                tmdb_id_idx = idx
                break
        
        if tmdb_id_idx:
            print(f"Found unique index on tmdb_id: {tmdb_id_idx['name']}")
            # Drop the index
            try:
                await collection.drop_index(tmdb_id_idx['name'])
                print(f"Successfully dropped index: {tmdb_id_idx['name']}")
            except Exception as e:
                print(f"Failed to drop index: {e}")
        else:
            print("No simple unique index on tmdb_id found.")

        # 3. Create compound unique index (optional but recommended for health)
        print("Creating compound unique index on {tmdb_id: 1, title: 1}...")
        try:
            await collection.create_index(
                [("tmdb_id", 1), ("title", 1)],
                unique=True,
                name="tmdb_id_title_unique"
            )
            print("Compound index created successfully.")
        except Exception as e:
            print(f"Failed to create compound index (maybe duplicates already exist?): {e}")

    client.close()
    print("\nIndex fix complete!")

if __name__ == "__main__":
    asyncio.run(fix_indexes())
