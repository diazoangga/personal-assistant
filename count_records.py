import aiosqlite
import asyncio

async def count():
    db = await aiosqlite.connect('data/memory.db')
    cur = await db.execute('SELECT COUNT(*) FROM interest_nodes')
    print('interest_nodes count:', await cur.fetchone())
    
    cur = await db.execute('SELECT COUNT(*) FROM profile')
    print('profile count:', await cur.fetchone())
    
    cur = await db.execute('SELECT COUNT(*) FROM opportunities')
    print('opportunities count:', await cur.fetchone())
    
    await db.close()
    
    db = await aiosqlite.connect('data/concepts.db')
    cur = await db.execute('SELECT COUNT(*) FROM concept_nodes')
    print('concept_nodes count:', await cur.fetchone())
    
    cur = await db.execute('SELECT COUNT(*) FROM relation_edges')
    print('relation_edges count:', await cur.fetchone())
    
    await db.close()
    
    db = await aiosqlite.connect('data/citations.db')
    cur = await db.execute('SELECT COUNT(*) FROM citation_nodes')
    print('citation_nodes count:', await cur.fetchone())
    
    await db.close()

asyncio.run(count())
