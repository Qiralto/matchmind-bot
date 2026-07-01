"""Gestion de la base de données PostgreSQL (Supabase) pour le bot de rencontre."""
import os
import json
import time
import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL")


async def get_conn():
    return await asyncpg.connect(DATABASE_URL)


async def init_db():
    conn = await get_conn()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                user_id BIGINT PRIMARY KEY,
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
                created_at BIGINT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                liker_id BIGINT,
                liked_id BIGINT,
                created_at BIGINT,
                PRIMARY KEY (liker_id, liked_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seen (
                user_id BIGINT,
                shown_user_id BIGINT,
                created_at BIGINT,
                PRIMARY KEY (user_id, shown_user_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                match_id SERIAL PRIMARY KEY,
                user1_id BIGINT,
                user2_id BIGINT,
                channel1_id BIGINT,
                channel2_id BIGINT,
                webhook1_url TEXT,
                webhook2_url TEXT,
                count1 INTEGER DEFAULT 0,
                count2 INTEGER DEFAULT 0,
                revealed INTEGER DEFAULT 0,
                reveal_agree1 INTEGER DEFAULT 0,
                reveal_agree2 INTEGER DEFAULT 0,
                created_at BIGINT
            )
        """)
    finally:
        await conn.close()


async def upsert_profile(user_id, **fields):
    fields["interests"] = json.dumps(fields.get("interests", []), ensure_ascii=False)
    fields["user_id"] = user_id
    fields["created_at"] = int(time.time())
    cols = ", ".join(fields.keys())
    placeholders = ", ".join(f"${i+1}" for i in range(len(fields)))
    updates = ", ".join(f"{k}=EXCLUDED.{k}" for k in fields if k != "user_id")
    conn = await get_conn()
    try:
        await conn.execute(
            f"INSERT INTO profiles ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(user_id) DO UPDATE SET {updates}",
            *fields.values(),
        )
    finally:
        await conn.close()


async def get_profile(user_id):
    conn = await get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM profiles WHERE user_id = $1", user_id)
        if row:
            d = dict(row)
            d["interests"] = json.loads(d["interests"] or "[]")
            return d
        return None
    finally:
        await conn.close()


async def get_all_active_profiles(exclude_user_id=None):
    conn = await get_conn()
    try:
        rows = await conn.fetch(
            "SELECT * FROM profiles WHERE active = 1 AND user_id != $1",
            exclude_user_id or 0,
        )
        results = []
        for row in rows:
            d = dict(row)
            d["interests"] = json.loads(d["interests"] or "[]")
            results.append(d)
        return results
    finally:
        await conn.close()


async def mark_seen(user_id, shown_user_id):
    conn = await get_conn()
    try:
        await conn.execute(
            "INSERT INTO seen (user_id, shown_user_id, created_at) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            user_id, shown_user_id, int(time.time()),
        )
    finally:
        await conn.close()


async def get_seen_ids(user_id):
    conn = await get_conn()
    try:
        rows = await conn.fetch("SELECT shown_user_id FROM seen WHERE user_id = $1", user_id)
        return {r["shown_user_id"] for r in rows}
    finally:
        await conn.close()


async def add_like(liker_id, liked_id):
    conn = await get_conn()
    try:
        await conn.execute(
            "INSERT INTO likes (liker_id, liked_id, created_at) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            liker_id, liked_id, int(time.time()),
        )
    finally:
        await conn.close()


async def has_liked(liker_id, liked_id):
    conn = await get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT 1 FROM likes WHERE liker_id = $1 AND liked_id = $2", liker_id, liked_id
        )
        return row is not None
    finally:
        await conn.close()


async def create_match(user1_id, user2_id):
    conn = await get_conn()
    try:
        row = await conn.fetchrow(
            "INSERT INTO matches (user1_id, user2_id, created_at) VALUES ($1, $2, $3) RETURNING match_id",
            user1_id, user2_id, int(time.time()),
        )
        return row["match_id"]
    finally:
        await conn.close()


async def set_match_channels(match_id, channel1_id, channel2_id, webhook1_url, webhook2_url):
    conn = await get_conn()
    try:
        await conn.execute(
            "UPDATE matches SET channel1_id=$1, channel2_id=$2, webhook1_url=$3, webhook2_url=$4 WHERE match_id=$5",
            channel1_id, channel2_id, webhook1_url, webhook2_url, match_id,
        )
    finally:
        await conn.close()


async def get_match_by_channel(channel_id):
    conn = await get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM matches WHERE channel1_id = $1 OR channel2_id = $1",
            channel_id,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def increment_message_count(match_id, side):
    col = "count1" if side == 1 else "count2"
    conn = await get_conn()
    try:
        await conn.execute(f"UPDATE matches SET {col} = {col} + 1 WHERE match_id = $1", match_id)
    finally:
        await conn.close()


async def set_reveal_agree(match_id, side):
    col = "reveal_agree1" if side == 1 else "reveal_agree2"
    conn = await get_conn()
    try:
        await conn.execute(f"UPDATE matches SET {col} = 1 WHERE match_id = $1", match_id)
    finally:
        await conn.close()


async def set_revealed(match_id):
    conn = await get_conn()
    try:
        await conn.execute("UPDATE matches SET revealed = 1 WHERE match_id = $1", match_id)
    finally:
        await conn.close()


async def get_existing_match(user1_id, user2_id):
    conn = await get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM matches WHERE (user1_id=$1 AND user2_id=$2) OR (user1_id=$2 AND user2_id=$1)",
            user1_id, user2_id,
        )
        return dict(row) if row else None
    finally:
        await conn.close()


async def has_been_liked_by_anyone_unseen(user_id):
    conn = await get_conn()
    try:
        row = await conn.fetchrow("SELECT COUNT(*) FROM likes WHERE liked_id = $1", user_id)
        return row[0] > 0
    finally:
        await conn.close()

async def delete_profile(user_id):
    conn = await get_conn()
    try:
        await conn.execute("DELETE FROM profiles WHERE user_id = $1", user_id)
        await conn.execute("DELETE FROM likes WHERE liker_id = $1 OR liked_id = $1", user_id)
        await conn.execute("DELETE FROM seen WHERE user_id = $1 OR shown_user_id = $1", user_id)
    finally:
        await conn.close()


async def add_warning(user_id: int, reason: str, moderator_id: int):
    conn = await get_conn()
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS warnings ("
            "id SERIAL PRIMARY KEY, "
            "user_id BIGINT, "
            "reason TEXT, "
            "moderator_id BIGINT, "
            "created_at BIGINT)"
        )
        await conn.execute(
            "INSERT INTO warnings (user_id, reason, moderator_id, created_at) VALUES ($1, $2, $3, $4)",
            user_id, reason, moderator_id, int(__import__('time').time())
        )
    finally:
        await conn.close()


async def get_warnings(user_id: int):
    conn = await get_conn()
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS warnings ("
            "id SERIAL PRIMARY KEY, "
            "user_id BIGINT, "
            "reason TEXT, "
            "moderator_id BIGINT, "
            "created_at BIGINT)"
        )
        rows = await conn.fetch("SELECT * FROM warnings WHERE user_id = $1 ORDER BY created_at DESC", user_id)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def remove_last_warning(user_id: int):
    conn = await get_conn()
    try:
        await conn.execute(
            "DELETE FROM warnings WHERE id = ("
            "SELECT id FROM warnings WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1)",
            user_id
        )
    finally:
        await conn.close()


async def count_warnings(user_id: int):
    conn = await get_conn()
    try:
        row = await conn.fetchrow("SELECT COUNT(*) FROM warnings WHERE user_id = $1", user_id)
        return row[0]
    finally:
        await conn.close()
