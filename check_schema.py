import aiosqlite
import asyncio

async def check():
    db = await aiosqlite.connect('data/memory.db')
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = await cursor.fetchall()
    print('Tables in memory.db:', [t[0] for t in tables])
    
    # Show schema for each table
    for table in tables:
        table_name = table[0]
        cursor = await db.execute(f"PRAGMA table_info({table_name})")
        columns = await cursor.fetchall()
        print(f"\n{table_name} columns:")
        for col in columns:
            print(f"  {col[1]} ({col[2]})")
    
    await db.close()

asyncio.run(check())
