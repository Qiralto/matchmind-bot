"""Gestion de la base de données SQLite pour le bot de rencontre."""
import aiosqlite
import json
import time

DB_PATH = "dating_bot.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                prenom TEXT,
                age INTEGER,
                sexe TEXT,
                orientation TEXT,
                localisation TEXT,
                relation_type TEXT,
                interests TEXT,
                description TEXT,
                icebreaker TEXT,
                active INTEGER DEFAULT 1,
                created_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                liker_id INTEGER,
                liked_id INTEGER,
                created_at INTEGER,
                PRIMARY KEY (liker_id, liked_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen (
                user_id INTEGER,
                shown_user_id INTEGER,
                created_at INTEGER,
                PRIMARY KEY (user_id, shown_user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                match_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user1_id INTEGER,
                user2_id INTEGER,
                channel1_id INTEGER,
                channel2_id INTEGER,
                webhook1_url TEXT,
                webhook2_url TEXT,
                count1 INTEGER DEFAULT 0,
                count2 INTEGER DEFAULT 0,
                revealed INTEGER DEFAULT 0,
                reveal_agree1 INTEGER DEFAULT 0,
                reveal_agree2 INTEGER DEFAULT 0,
                created_at INTEGER
            )
        """)
        await db.commit()


async def upsert_profile(user_id, **fields):
    fields["interests"] = json.dumps(fields.get("interests", []), ensure_ascii=False)
    fields["user_id"] = user_id
    fields["created_at"] = int(time.time())
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields if k != "user_id")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"INSERT INTO profiles ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(user_id) DO UPDATE SET {updates}",
            list(fields.values()),
        )
        await db.commit()


async def get_profile(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if row:
            d = dict(row)
            d["interests"] = json.loads(d["interests"] or "[]")
            return d
        return None


async def get_all_active_profiles(exclude_user_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM profiles WHERE active = 1 AND user_id != ?",
            (exclude_user_id or 0,),
        )
        rows = await cur.fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d["interests"] = json.loads(d["interests"] or "[]")
            results.append(d)
        return results


async def mark_seen(user_id, shown_user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen (user_id, shown_user_id, created_at) VALUES (?, ?, ?)",
            (user_id, shown_user_id, int(time.time())),
        )
        await db.commit()


async def get_seen_ids(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT shown_user_id FROM seen WHERE user_id = ?", (user_id,))
        rows = await cur.fetchall()
        return {r[0] for r in rows}


async def add_like(liker_id, liked_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO likes (liker_id, liked_id, created_at) VALUES (?, ?, ?)",
            (liker_id, liked_id, int(time.time())),
        )
        await db.commit()


async def has_liked(liker_id, liked_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM likes WHERE liker_id = ? AND liked_id = ?", (liker_id, liked_id)
        )
        return await cur.fetchone() is not None


async def has_been_liked_by_anyone_unseen(user_id):
    """Retourne True s'il existe un like reçu pour lequel on n'a pas encore notifié."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM likes WHERE liked_id = ?", (user_id,)
        )
        row = await cur.fetchone()
        return row[0] > 0


async def create_match(user1_id, user2_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO matches (user1_id, user2_id, created_at) VALUES (?, ?, ?)",
            (user1_id, user2_id, int(time.time())),
        )
        await db.commit()
        return cur.lastrowid


async def set_match_channels(match_id, channel1_id, channel2_id, webhook1_url, webhook2_url):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE matches SET channel1_id=?, channel2_id=?, webhook1_url=?, webhook2_url=? "
            "WHERE match_id=?",
            (channel1_id, channel2_id, webhook1_url, webhook2_url, match_id),
        )
        await db.commit()


async def get_match_by_channel(channel_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM matches WHERE channel1_id = ? OR channel2_id = ?",
            (channel_id, channel_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def increment_message_count(match_id, side):
    col = "count1" if side == 1 else "count2"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE matches SET {col} = {col} + 1 WHERE match_id = ?", (match_id,))
        await db.commit()


async def set_reveal_agree(match_id, side):
    col = "reveal_agree1" if side == 1 else "reveal_agree2"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE matches SET {col} = 1 WHERE match_id = ?", (match_id,))
        await db.commit()


async def set_revealed(match_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE matches SET revealed = 1 WHERE match_id = ?", (match_id,))
        await db.commit()


async def get_existing_match(user1_id, user2_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM matches WHERE (user1_id=? AND user2_id=?) OR (user1_id=? AND user2_id=?)",
            (user1_id, user2_id, user2_id, user1_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
