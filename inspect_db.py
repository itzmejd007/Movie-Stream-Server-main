
import asyncio
import os
import sys
from datetime import datetime
import motor.motor_asyncio

# Add the project root to sys.path
sys.path.append(os.getcwd())

from Backend.config import Telegram

async def inspect_db():
    uri = Telegram.DATABASE
    if isinstance(uri, list):
        uri = uri[0]
    
    print(f"Connecting to: {uri}")
    client = motor.motor_asyncio.AsyncIOMotorClient(uri)
    db = client["projectS"]
    
    for coll_name in ["movie", "tv"]:
        print(f"\nInspecting collection: {coll_name}")
        coll = db[coll_name]
        count = await coll.count_documents({})
        print(f"Total documents: {count}")
        
        # Check types of updated_on
        pipeline = [
            {"$project": {"type": {"$type": "$updated_on"}}},
            {"$group": {"_id": "$type", "count": {"$sum": 1}}}
        ]
        types = await coll.aggregate(pipeline).to_list(None)
        print("updated_on types:")
        for t in types:
            print(f"  - {t['_id']}: {t['count']}")
            
        # Sample some documents
        samples = await coll.find({}, {"title": 1, "updated_on": 1}).limit(5).to_list(None)
        print("Sample documents:")
        for s in samples:
            print(f"  - {s.get('title')}: {s.get('updated_on')} ({type(s.get('updated_on'))})")

    client.close()

if __name__ == "__main__":
    asyncio.run(inspect_db())
