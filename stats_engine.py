"""
Personal statistics engine.
Queries SQLite match database for counter matchups, rune/spell/item win rates,
and synergy win rates. All functions have min_games threshold.
"""

import json
import logging
import os
import sys
from datetime import datetime

from match_collector import get_db, DB_PATH, DATA_DIR

logger = logging.getLogger(__name__)

# ── Counter classification helpers ──────────────────────────────────────────


def _classify_game_counter(win_rate: float) -> str:
    """Classify game-level counter based on win rate. Conservative thresholds."""
    if win_rate >= 58:
        return "强对局克制"
    if win_rate >= 56:
        return "对局克制"
    if win_rate >= 54:
        return "对局小优"
    if win_rate > 46:
        return "均势"
    if win_rate > 44:
        return "对局小劣"
    if win_rate > 42:
        return "对局被克制"
    return "强对局被克制"


def _classify_lane_counter(avg_gold_diff: float, avg_cs_diff: float,
                            avg_xp_diff: float) -> str:
    """Classify laning-phase counter. Uses the WORST of 3 indicators."""
    def _gold_classify(d):
        if d >= 500: return "强对线克制"
        if d >= 300: return "对线克制"
        if d > -300: return "对线均势"
        if d > -500: return "对线被克制"
        return "强对线被克制"

    def _cs_classify(d):
        if d >= 15: return "强对线克制"
        if d >= 10: return "对线克制"
        if d > -10: return "对线均势"
        if d > -15: return "对线被克制"
        return "强对线被克制"

    def _xp_classify(d):
        # 1 level ≈ 280 XP in early game
        if d >= 280: return "强对线克制"
        if d >= 140: return "对线克制"
        if d > -140: return "对线均势"
        if d > -280: return "对线被克制"
        return "强对线被克制"

    results = [_gold_classify(avg_gold_diff),
               _cs_classify(avg_cs_diff),
               _xp_classify(avg_xp_diff)]
    priority = {"强对线被克制": 0, "对线被克制": 1, "对线均势": 2,
                "对线克制": 3, "强对线克制": 4}
    return min(results, key=lambda x: priority.get(x, 2))


# ── Stats query functions ────────────────────────────────────────────────────


def get_counter_matchup_stats(champion_id: int, enemy_champion_id: int,
                               role: str, min_games: int = 5,
                               rank_tier: str = "") -> dict | None:
    """Compute personal counter matchup stats for champion vs enemy in role.

    Returns two independent counter classifications:
      - game_counter: based on final win rate
      - lane_counter: based on 10min gold/CS/XP diff (worst of 3)
    Returns None if fewer than min_games recorded.
    """
    if not os.path.exists(DB_PATH):
        return None

    conn = get_db()
    try:
        tier_filter = "AND m.rank_tier = ?" if rank_tier else ""
        params = [champion_id, enemy_champion_id, role]
        if rank_tier:
            params.append(rank_tier)

        row = conn.execute(f"""
            SELECT
                COUNT(*) as games,
                SUM(p1.win) as wins,
                AVG(t1.total_gold - COALESCE(t2.total_gold, t1.total_gold))
                    as avg_gold_diff_10,
                AVG((t1.minions_killed + t1.jungle_minions_killed)
                    - COALESCE(t2.minions_killed + t2.jungle_minions_killed,
                               t1.minions_killed + t1.jungle_minions_killed))
                    as avg_cs_diff_10,
                AVG(t1.xp - COALESCE(t2.xp, t1.xp)) as avg_xp_diff_10
            FROM participants p1
            JOIN participants p2
                ON p1.game_id = p2.game_id
                AND p1.team_id != p2.team_id
                AND p1.normalized_role = p2.normalized_role
            JOIN matches m ON p1.game_id = m.game_id
            LEFT JOIN timeline_snapshots t1
                ON t1.game_id = p1.game_id AND t1.participant_id = p1.id
            LEFT JOIN timeline_snapshots t2
                ON t2.game_id = p2.game_id AND t2.participant_id = p2.id
            WHERE p1.champion_id = ?
              AND p2.champion_id = ?
              AND p1.normalized_role = ?
              {tier_filter}
        """, params).fetchone()

        if not row or row["games"] < min_games:
            return None

        win_rate = round(row["wins"] / row["games"] * 100, 1)
        gd10 = round(row["avg_gold_diff_10"] or 0, 1)
        cd10 = round(row["avg_cs_diff_10"] or 0, 1)
        xd10 = round(row["avg_xp_diff_10"] or 0, 1)

        return {
            "games": row["games"],
            "wins": row["wins"],
            "win_rate": win_rate,
            "game_counter": _classify_game_counter(win_rate),
            "avg_gold_diff_10": gd10,
            "avg_cs_diff_10": cd10,
            "avg_xp_diff_10": xd10,
            "lane_counter": _classify_lane_counter(gd10, cd10, xd10),
        }
    finally:
        conn.close()


def get_rune_win_rates(champion_id: int, role: str,
                        min_games: int = 5) -> list[dict]:
    """Compute win rates for each rune setup (perk0 + primary + sub style)."""
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT
                perk0, perk_primary_style, perk_sub_style,
                COUNT(*) as games,
                SUM(win) as wins,
                ROUND(SUM(win) * 100.0 / COUNT(*), 1) as win_rate
            FROM participants
            WHERE champion_id = ? AND normalized_role = ?
            GROUP BY perk0, perk_primary_style, perk_sub_style
            HAVING COUNT(*) >= ?
            ORDER BY games DESC
        """, (champion_id, role, min_games)).fetchall()

        return [
            {
                "keystone_id": r["perk0"],
                "primary_style": r["perk_primary_style"],
                "sub_style": r["perk_sub_style"],
                "games": r["games"],
                "wins": r["wins"],
                "win_rate": r["win_rate"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_spell_win_rates(champion_id: int, role: str,
                         min_games: int = 5) -> list[dict]:
    """Compute win rates for each summoner spell combination."""
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT
                summoner1_id, summoner2_id,
                COUNT(*) as games,
                SUM(win) as wins,
                ROUND(SUM(win) * 100.0 / COUNT(*), 1) as win_rate
            FROM participants
            WHERE champion_id = ? AND normalized_role = ?
            GROUP BY summoner1_id, summoner2_id
            HAVING COUNT(*) >= ?
            ORDER BY games DESC
        """, (champion_id, role, min_games)).fetchall()

        return [
            {
                "spell_ids": sorted([r["summoner1_id"], r["summoner2_id"]]),
                "games": r["games"],
                "wins": r["wins"],
                "win_rate": r["win_rate"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_item_win_rates(champion_id: int, role: str,
                        min_games: int = 5) -> list[dict]:
    """Compute win rates for final item builds (game_duration >= 15min)."""
    if not os.path.exists(DB_PATH):
        return []

    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT
                item0, item1, item2, item3, item4, item5,
                COUNT(*) as games,
                SUM(p.win) as wins,
                ROUND(SUM(p.win) * 100.0 / COUNT(*), 1) as win_rate
            FROM participants p
            JOIN matches m ON p.game_id = m.game_id
            WHERE p.champion_id = ?
              AND p.normalized_role = ?
              AND m.game_duration >= 900
            GROUP BY item0, item1, item2, item3, item4, item5
            HAVING COUNT(*) >= ?
            ORDER BY games DESC
            LIMIT 50
        """, (champion_id, role, min_games)).fetchall()

        return [
            {
                "items": [r["item0"], r["item1"], r["item2"],
                          r["item3"], r["item4"], r["item5"]],
                "games": r["games"],
                "wins": r["wins"],
                "win_rate": r["win_rate"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_synergy_win_rate(champion_id: int, teammate_champion_id: int,
                          role: str | None = None,
                          min_games: int = 5) -> dict | None:
    """Compute win rate when two champions are on the same team."""
    if not os.path.exists(DB_PATH):
        return None

    conn = get_db()
    try:
        role_filter = "AND p1.normalized_role = ?" if role else ""
        params = [champion_id, teammate_champion_id]
        if role:
            params.append(role)

        row = conn.execute(f"""
            SELECT
                COUNT(*) as games,
                SUM(p1.win) as wins,
                ROUND(SUM(p1.win) * 100.0 / COUNT(*), 1) as win_rate
            FROM participants p1
            JOIN participants p2
                ON p1.game_id = p2.game_id AND p1.team_id = p2.team_id
            WHERE p1.champion_id = ?
              AND p2.champion_id = ?
              AND p1.id != p2.id
              {role_filter}
        """, params).fetchone()

        if not row or row["games"] < min_games:
            return None

        return {
            "games": row["games"],
            "wins": row["wins"],
            "win_rate": row["win_rate"],
        }
    finally:
        conn.close()


def get_all_counter_stats_for_enemies(my_champion_id: int, my_role: str,
                                       enemy_champion_ids: list[int],
                                       rank_tier: str = "",
                                       min_games: int = 5) -> dict[int, dict]:
    """Batch query: for each enemy champion, get personal counter stats."""
    result = {}
    for enemy_id in enemy_champion_ids:
        stats = get_counter_matchup_stats(
            my_champion_id, enemy_id, my_role, min_games, rank_tier
        )
        if stats:
            result[enemy_id] = stats
    return result


# ── Export ───────────────────────────────────────────────────────────────────


def get_rank_distribution() -> dict[str, int]:
    """Get distribution of rank tiers in the database."""
    if not os.path.exists(DB_PATH):
        return {}

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT rank_tier, COUNT(*) as cnt FROM matches GROUP BY rank_tier"
        ).fetchall()
        return {r["rank_tier"]: r["cnt"] for r in rows}
    finally:
        conn.close()


def export_stats(output_path: str | None = None,
                  min_games: int = 3) -> dict:
    """Export all aggregated statistics as an anonymous JSON file.

    The output is intentionally anonymous: no summoner names, PUUIDs,
    or game_ids. Only aggregated champion/game data.
    """
    if not os.path.exists(DB_PATH):
        return {"version": 1, "total_games": 0, "stats": {}}

    conn = get_db()
    try:
        from champion_data import get_champion_data
        cd = get_champion_data()

        total_games = conn.execute(
            "SELECT COUNT(*) FROM matches"
        ).fetchone()[0]

        # Get all (champion, role) combos with enough games
        combos = conn.execute("""
            SELECT champion_id, normalized_role, COUNT(*) as cnt
            FROM participants
            WHERE normalized_role != 'unknown'
            GROUP BY champion_id, normalized_role
            HAVING COUNT(*) >= ?
        """, (min_games,)).fetchall()

        counter = {}
        rune_rates = {}
        spell_rates = {}
        item_rates = {}
        synergy_rates = {}

        for combo in combos:
            cid = combo["champion_id"]
            role = combo["normalized_role"]
            cid_str = str(cid)

            # ── Counter matchups ──
            enemy_rows = conn.execute("""
                SELECT p2.champion_id,
                       COUNT(*) as g, SUM(p1.win) as w,
                       AVG(t1.total_gold - COALESCE(t2.total_gold, t1.total_gold)) as gd10,
                       AVG((t1.minions_killed + t1.jungle_minions_killed)
                           - COALESCE(t2.minions_killed + t2.jungle_minions_killed,
                                      t1.minions_killed + t1.jungle_minions_killed)) as cd10,
                       AVG(t1.xp - COALESCE(t2.xp, t1.xp)) as xd10
                FROM participants p1
                JOIN participants p2
                    ON p1.game_id = p2.game_id AND p1.team_id != p2.team_id
                    AND p1.normalized_role = p2.normalized_role
                LEFT JOIN timeline_snapshots t1
                    ON t1.game_id = p1.game_id AND t1.participant_id = p1.id
                LEFT JOIN timeline_snapshots t2
                    ON t2.game_id = p2.game_id AND t2.participant_id = p2.id
                WHERE p1.champion_id = ? AND p1.normalized_role = ?
                GROUP BY p2.champion_id
                HAVING COUNT(*) >= ?
            """, (cid, role, min_games)).fetchall()

            for er in enemy_rows:
                eid = str(er["champion_id"])
                counter.setdefault(cid_str, {}).setdefault(role, {})[eid] = {
                    "g": er["g"], "w": er["w"],
                    "gd10": round(er["gd10"] or 0, 1),
                    "cd10": round(er["cd10"] or 0, 1),
                    "xd10": round(er["xd10"] or 0, 1),
                }

            # ── Rune rates ──
            rune_rows = conn.execute("""
                SELECT perk0, perk_primary_style, perk_sub_style,
                       COUNT(*) as g, SUM(win) as w
                FROM participants
                WHERE champion_id = ? AND normalized_role = ?
                GROUP BY perk0, perk_primary_style, perk_sub_style
                HAVING COUNT(*) >= ?
                ORDER BY g DESC LIMIT 10
            """, (cid, role, min_games)).fetchall()
            rune_rates.setdefault(cid_str, {})[role] = [
                {"k": r["perk0"], "p": r["perk_primary_style"],
                 "s": r["perk_sub_style"], "g": r["g"], "w": r["w"]}
                for r in rune_rows
            ]

            # ── Spell rates ──
            spell_rows = conn.execute("""
                SELECT summoner1_id, summoner2_id,
                       COUNT(*) as g, SUM(win) as w
                FROM participants
                WHERE champion_id = ? AND normalized_role = ?
                GROUP BY summoner1_id, summoner2_id
                HAVING COUNT(*) >= ?
                ORDER BY g DESC LIMIT 10
            """, (cid, role, min_games)).fetchall()
            spell_rates.setdefault(cid_str, {})[role] = [
                {"s": sorted([r["summoner1_id"], r["summoner2_id"]]),
                 "g": r["g"], "w": r["w"]}
                for r in spell_rows
            ]

            # ── Item rates (>= 15min games) ──
            item_rows = conn.execute("""
                SELECT p.item0, p.item1, p.item2, p.item3, p.item4, p.item5,
                       COUNT(*) as g, SUM(p.win) as w
                FROM participants p
                JOIN matches m ON p.game_id = m.game_id
                WHERE p.champion_id = ? AND p.normalized_role = ?
                  AND m.game_duration >= 900
                GROUP BY p.item0, p.item1, p.item2, p.item3, p.item4, p.item5
                HAVING COUNT(*) >= ?
                ORDER BY g DESC LIMIT 10
            """, (cid, role, min_games)).fetchall()
            item_rates.setdefault(cid_str, {})[role] = [
                {"i": [r["item0"], r["item1"], r["item2"],
                       r["item3"], r["item4"], r["item5"]],
                 "g": r["g"], "w": r["w"]}
                for r in item_rows
            ]

            # ── Synergy rates ──
            syn_rows = conn.execute("""
                SELECT p2.champion_id,
                       COUNT(*) as g, SUM(p1.win) as w
                FROM participants p1
                JOIN participants p2
                    ON p1.game_id = p2.game_id AND p1.team_id = p2.team_id
                WHERE p1.champion_id = ? AND p1.normalized_role = ?
                  AND p1.id != p2.id
                GROUP BY p2.champion_id
                HAVING COUNT(*) >= ?
                ORDER BY g DESC LIMIT 15
            """, (cid, role, min_games)).fetchall()
            synergy_rates.setdefault(cid_str, {})[
                role] = {}  # synergy doesn't need role dict nesting
            for sr in syn_rows:
                synergy_rates.setdefault(cid_str, {}).setdefault(
                    str(sr["champion_id"]), {})[str(sr["champion_id"])] = None
                # Fixed: synergy is champ-to-champ, not per-role
                sid = str(sr["champion_id"])
                if sid not in synergy_rates.get(cid_str, {}):
                    synergy_rates.setdefault(cid_str, {})[sid] = {
                        "g": sr["g"], "w": sr["w"]
                    }

        # Clean up synergy: use flat champ→champ structure
        syn_clean = {}
        for cid_str, teammates in synergy_rates.items():
            syn_clean[cid_str] = teammates

        result = {
            "version": 1,
            "exported_at": datetime.now().isoformat(),
            "total_games": total_games,
            "rank_distribution": get_rank_distribution(),
            "stats": {
                "counter_matchups": counter,
                "rune_rates": rune_rates,
                "spell_rates": spell_rates,
                "item_rates": item_rates,
                "synergy_rates": syn_clean,
            },
        }

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
            logger.info("Exported stats to %s (%d games)",
                        output_path, total_games)

        return result
    finally:
        conn.close()
