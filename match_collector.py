"""
Personal match statistics collector.
Stores ranked game data (all 10 players) in SQLite for statistical analysis.
"""

import sqlite3
import logging
import os
import sys
import time

logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(sys._MEIPASS, "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

DB_PATH = os.path.join(DATA_DIR, "personal_stats.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS matches (
    game_id        INTEGER PRIMARY KEY,
    queue_id       INTEGER NOT NULL,
    game_duration  INTEGER NOT NULL DEFAULT 0,
    game_version   TEXT    NOT NULL DEFAULT '',
    game_creation  INTEGER NOT NULL DEFAULT 0,
    rank_tier      TEXT    NOT NULL DEFAULT 'UNRANKED',
    collected_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS participants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id         INTEGER NOT NULL REFERENCES matches(game_id),
    team_id         INTEGER NOT NULL,
    champion_id     INTEGER NOT NULL,
    team_position   TEXT    NOT NULL DEFAULT '',
    normalized_role TEXT    NOT NULL DEFAULT '',
    win             INTEGER NOT NULL DEFAULT 0,
    kills           INTEGER NOT NULL DEFAULT 0,
    deaths          INTEGER NOT NULL DEFAULT 0,
    assists         INTEGER NOT NULL DEFAULT 0,
    gold_earned     INTEGER NOT NULL DEFAULT 0,
    total_cs        INTEGER NOT NULL DEFAULT 0,
    damage_dealt    INTEGER NOT NULL DEFAULT 0,
    vision_score    INTEGER NOT NULL DEFAULT 0,
    champ_level     INTEGER NOT NULL DEFAULT 0,
    summoner1_id    INTEGER NOT NULL DEFAULT 0,
    summoner2_id    INTEGER NOT NULL DEFAULT 0,
    perk0           INTEGER NOT NULL DEFAULT 0,
    perk1           INTEGER NOT NULL DEFAULT 0,
    perk2           INTEGER NOT NULL DEFAULT 0,
    perk3           INTEGER NOT NULL DEFAULT 0,
    perk4           INTEGER NOT NULL DEFAULT 0,
    perk5           INTEGER NOT NULL DEFAULT 0,
    perk_primary_style  INTEGER NOT NULL DEFAULT 0,
    perk_sub_style      INTEGER NOT NULL DEFAULT 0,
    stat_perk0      INTEGER NOT NULL DEFAULT 0,
    stat_perk1      INTEGER NOT NULL DEFAULT 0,
    stat_perk2      INTEGER NOT NULL DEFAULT 0,
    item0           INTEGER NOT NULL DEFAULT 0,
    item1           INTEGER NOT NULL DEFAULT 0,
    item2           INTEGER NOT NULL DEFAULT 0,
    item3           INTEGER NOT NULL DEFAULT 0,
    item4           INTEGER NOT NULL DEFAULT 0,
    item5           INTEGER NOT NULL DEFAULT 0,
    item6           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS timeline_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id             INTEGER NOT NULL REFERENCES matches(game_id),
    participant_id      INTEGER NOT NULL REFERENCES participants(id),
    total_gold          REAL    NOT NULL DEFAULT 0,
    minions_killed      INTEGER NOT NULL DEFAULT 0,
    jungle_minions_killed INTEGER NOT NULL DEFAULT 0,
    xp                  INTEGER NOT NULL DEFAULT 0,
    level               INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS collected_games (
    game_id       INTEGER PRIMARY KEY,
    has_timeline  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS current_account (
    puuid         TEXT PRIMARY KEY,
    first_seen    TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen     TEXT NOT NULL DEFAULT (datetime('now')),
    total_games   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_participants_game
    ON participants(game_id);
CREATE INDEX IF NOT EXISTS idx_participants_champion_role
    ON participants(champion_id, normalized_role);
CREATE INDEX IF NOT EXISTS idx_participants_win
    ON participants(champion_id, normalized_role, win);
CREATE INDEX IF NOT EXISTS idx_timeline_game
    ON timeline_snapshots(game_id);
"""


def _normalize_role(lcu_position: str) -> str:
    """Convert LCU position string to internal normalized role."""
    if not lcu_position:
        return "unknown"
    pos = lcu_position.lower()
    if pos == "bottom":
        return "bot"
    if pos == "middle":
        return "mid"
    if pos == "utility":
        return "support"
    return pos


def get_db() -> sqlite3.Connection:
    """Get a thread-safe database connection with WAL mode."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables and indexes if they don't exist."""
    conn = get_db()
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    logger.debug("Database initialized at %s", DB_PATH)


def get_db_stats() -> dict:
    """Return summary statistics about the personal database."""
    if not os.path.exists(DB_PATH):
        return {"total_games": 0, "total_participants": 0,
                "games_with_timeline": 0, "unique_champions": 0, "db_size_mb": 0}
    conn = get_db()
    try:
        return {
            "total_games": conn.execute(
                "SELECT COUNT(*) FROM matches").fetchone()[0],
            "total_participants": conn.execute(
                "SELECT COUNT(*) FROM participants").fetchone()[0],
            "games_with_timeline": conn.execute(
                "SELECT COUNT(*) FROM collected_games WHERE has_timeline=1"
            ).fetchone()[0],
            "unique_champions": conn.execute(
                "SELECT COUNT(DISTINCT champion_id) FROM participants"
            ).fetchone()[0],
            "db_size_mb": round(os.path.getsize(DB_PATH) / (1024 * 1024), 2),
        }
    finally:
        conn.close()


def collect_match_history(headers: dict, base_url: str,
                          rank_tier: str, puuid: str) -> int:
    """Fetch match history from LCU and record new ranked games.

    Returns number of new games recorded.
    """
    from lcu import fetch_match_list

    match_list = fetch_match_list(headers, base_url, puuid)
    if not match_list:
        return 0

    conn = get_db()
    try:
        existing_ids = set()
        for row in conn.execute(
            "SELECT game_id FROM collected_games"
        ).fetchall():
            existing_ids.add(row[0])

        new_matches = [m for m in match_list
                       if m.get("gameId") not in existing_ids]
        if not new_matches:
            logger.debug("No new matches to collect (%d already in DB)",
                         len(match_list))
            return 0

        logger.info("Collecting %d new matches out of %d from history",
                    len(new_matches), len(match_list))

        from lcu import fetch_match_detail

        count = 0
        for match in new_matches:
            try:
                game_id = match.get("gameId", 0)
                queue_id = match.get("queueId", 0)
                if queue_id not in (420, 440):
                    continue

                # Fetch full match detail (match list only has 1 participant)
                detail = fetch_match_detail(headers, base_url, game_id)
                if detail:
                    _insert_match_full(conn, detail, rank_tier)
                else:
                    # Fallback: use match list data (only 1 participant)
                    _insert_match(conn, match, rank_tier)

                count += 1
            except Exception:
                logger.exception("Failed to insert match %s",
                                 match.get("gameId"))
                continue

        conn.commit()

        # Update account tracking
        conn.execute(
            "INSERT INTO current_account (puuid, first_seen, last_seen, total_games) "
            "VALUES (?, datetime('now'), datetime('now'), ?) "
            "ON CONFLICT(puuid) DO UPDATE SET "
            "last_seen = datetime('now'), total_games = total_games + ?",
            (puuid, count, count)
        )

        logger.info("Recorded %d new matches", count)
        return count
    finally:
        conn.close()


def collect_match_timeline(headers: dict, base_url: str) -> int:
    """Fetch timeline data for matches that have no timeline snapshots yet.

    Returns number of timelines collected.
    """
    from lcu import fetch_match_timeline, extract_10min_stats

    if not os.path.exists(DB_PATH):
        return 0

    conn = get_db()
    try:
        pending = [row[0] for row in conn.execute(
            "SELECT game_id FROM collected_games WHERE has_timeline = 0"
        ).fetchall()]

        count = 0
        for game_id in pending:
            try:
                timeline = fetch_match_timeline(headers, base_url, game_id)
                if not timeline:
                    continue

                snapshots = extract_10min_stats(timeline)
                if snapshots:
                    _insert_timeline_snapshots(conn, game_id, snapshots)

                conn.execute(
                    "UPDATE collected_games SET has_timeline = 1 "
                    "WHERE game_id = ?", (game_id,)
                )
                conn.commit()
                count += 1
            except Exception:
                logger.exception("Failed to fetch timeline for game %s",
                                 game_id)
                continue

        if count:
            logger.info("Collected timeline data for %d games", count)
        return count
    finally:
        conn.close()


def _insert_match(conn: sqlite3.Connection, match: dict, rank_tier: str):
    """Insert one match and all 10 participants into the database."""
    game_id = match.get("gameId", 0)
    queue_id = match.get("queueId", 0)

    if queue_id not in (420, 440):
        logger.debug("Skipping non-ranked queue %d for game %s",
                     queue_id, game_id)
        return

    conn.execute(
        "INSERT OR IGNORE INTO matches "
        "(game_id, queue_id, game_duration, game_version, game_creation, "
        " rank_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (game_id, queue_id,
         match.get("gameDuration", 0),
         match.get("gameVersion", ""),
         match.get("gameCreation", 0),
         rank_tier)
    )

    participants = match.get("participants", [])
    for p in participants:
        stats = p.get("stats", {})
        if not stats:
            stats = {}
        lcu_pos = p.get("teamPosition", "")
        role = _normalize_role(lcu_pos)

        total_cs = (stats.get("totalMinionsKilled", 0)
                    + stats.get("neutralMinionsKilled", 0))

        conn.execute(
            "INSERT INTO participants "
            "(game_id, team_id, champion_id, team_position, normalized_role, "
            " win, kills, deaths, assists, gold_earned, total_cs, "
            " damage_dealt, vision_score, champ_level, "
            " summoner1_id, summoner2_id, "
            " perk0, perk1, perk2, perk3, perk4, perk5, "
            " perk_primary_style, perk_sub_style, "
            " stat_perk0, stat_perk1, stat_perk2, "
            " item0, item1, item2, item3, item4, item5, item6) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "        ?, ?, ?, ?, ?, ?, ?)",
            (game_id,
             p.get("teamId", 0),
             p.get("championId", 0),
             lcu_pos, role,
             1 if stats.get("win", False) else 0,
             stats.get("kills", 0),
             stats.get("deaths", 0),
             stats.get("assists", 0),
             stats.get("goldEarned", 0),
             total_cs,
             stats.get("totalDamageDealtToChampions", 0),
             stats.get("visionScore", 0),
             stats.get("champLevel", 0),
             stats.get("summoner1Id", p.get("spell1Id", 0)),
             stats.get("summoner2Id", p.get("spell2Id", 0)),
             stats.get("perk0", 0), stats.get("perk1", 0),
             stats.get("perk2", 0), stats.get("perk3", 0),
             stats.get("perk4", 0), stats.get("perk5", 0),
             stats.get("perkPrimaryStyle", 0),
             stats.get("perkSubStyle", 0),
             stats.get("statPerk0", 0),
             stats.get("statPerk1", 0),
             stats.get("statPerk2", 0),
             stats.get("item0", 0), stats.get("item1", 0),
             stats.get("item2", 0), stats.get("item3", 0),
             stats.get("item4", 0), stats.get("item5", 0),
             stats.get("item6", 0))
        )

    conn.execute(
        "INSERT OR IGNORE INTO collected_games (game_id, has_timeline) "
        "VALUES (?, 0)", (game_id,)
    )


def _insert_match_full(conn: sqlite3.Connection, detail: dict, rank_tier: str):
    """Insert a match and all 10 participants from the full match detail endpoint."""
    game_id = detail.get("gameId", 0)
    queue_id = detail.get("queueId", 0)

    conn.execute(
        "INSERT OR IGNORE INTO matches "
        "(game_id, queue_id, game_duration, game_version, game_creation, "
        " rank_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (game_id, queue_id,
         detail.get("gameDuration", 0),
         detail.get("gameVersion", ""),
         detail.get("gameCreation", 0),
         rank_tier)
    )

    participants = detail.get("participants", [])
    for p in participants:
        stats = p.get("stats", {})
        if not stats:
            stats = {}
        lcu_pos = p.get("teamPosition", "")
        role = _normalize_role(lcu_pos)

        total_cs = (stats.get("totalMinionsKilled", 0)
                    + stats.get("neutralMinionsKilled", 0))

        conn.execute(
            "INSERT INTO participants "
            "(game_id, team_id, champion_id, team_position, normalized_role, "
            " win, kills, deaths, assists, gold_earned, total_cs, "
            " damage_dealt, vision_score, champ_level, "
            " summoner1_id, summoner2_id, "
            " perk0, perk1, perk2, perk3, perk4, perk5, "
            " perk_primary_style, perk_sub_style, "
            " stat_perk0, stat_perk1, stat_perk2, "
            " item0, item1, item2, item3, item4, item5, item6) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "        ?, ?, ?, ?, ?, ?, ?)",
            (game_id,
             p.get("teamId", 0),
             p.get("championId", 0),
             lcu_pos, role,
             1 if stats.get("win", False) else 0,
             stats.get("kills", 0),
             stats.get("deaths", 0),
             stats.get("assists", 0),
             stats.get("goldEarned", 0),
             total_cs,
             stats.get("totalDamageDealtToChampions", 0),
             stats.get("visionScore", 0),
             stats.get("champLevel", 0),
             stats.get("summoner1Id", p.get("spell1Id", 0)),
             stats.get("summoner2Id", p.get("spell2Id", 0)),
             stats.get("perk0", 0), stats.get("perk1", 0),
             stats.get("perk2", 0), stats.get("perk3", 0),
             stats.get("perk4", 0), stats.get("perk5", 0),
             stats.get("perkPrimaryStyle", 0),
             stats.get("perkSubStyle", 0),
             stats.get("statPerk0", 0),
             stats.get("statPerk1", 0),
             stats.get("statPerk2", 0),
             stats.get("item0", 0), stats.get("item1", 0),
             stats.get("item2", 0), stats.get("item3", 0),
             stats.get("item4", 0), stats.get("item5", 0),
             stats.get("item6", 0))
        )

    conn.execute(
        "INSERT OR IGNORE INTO collected_games (game_id, has_timeline) "
        "VALUES (?, 0)", (game_id,)
    )


def _insert_timeline_snapshots(conn: sqlite3.Connection, game_id: int,
                                snapshots: dict[int, dict]):
    """Insert 10-minute timeline snapshots for participants."""
    for participant_id, snap in snapshots.items():
        conn.execute(
            "INSERT INTO timeline_snapshots "
            "(game_id, participant_id, total_gold, minions_killed, "
            " jungle_minions_killed, xp, level) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (game_id, participant_id,
             snap.get("total_gold", 0),
             snap.get("minions_killed", 0),
             snap.get("jungle_minions_killed", 0),
             snap.get("xp", 0),
             snap.get("level", 0))
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    init_db()
    stats = get_db_stats()
    print(f"Database: {stats}")
    print("match_collector.py ready — needs LCU connection to collect data.")
