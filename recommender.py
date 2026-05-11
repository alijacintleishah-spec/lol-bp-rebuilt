"""
LoL BP Assistant — Iteration 4: Data Source Integration
Replaced hardcoded CHAMPIONS with ChampionData (Data Dragon + OP.GG).
"""

import logging

from champion_data import get_champion_data
from lane_detector import get_lane_rates

logger = logging.getLogger(__name__)
cd = get_champion_data()

TIER_BONUS = {"T0": 42, "S": 30, "A": 18, "B": 6, "C": -5}


def _get_effective_tier(ckey, meta):
    """Determine actual tier including T0 heuristic.
    T0 = S-tier + winrate >= 52% + (pickrate >= 8% or banrate >= 8%).
    """
    tier = meta.get("tier", "B")
    if tier != "S":
        return tier
    wr = meta.get("wr", 50.0)
    pr = meta.get("pr", 3.0)
    br = meta.get("br", 2.0)
    if wr >= 52.0 and (pr >= 8.0 or br >= 8.0):
        return "T0"
    return "S"

# Rank tier → meta weight multiplier (higher elo = meta matters more)
RANK_META_WEIGHT = {
    "CHALLENGER": 1.3, "GRANDMASTER": 1.25, "MASTER": 1.2,
    "DIAMOND": 1.15, "EMERALD": 1.1, "PLATINUM": 1.05,
    "GOLD": 1.0, "SILVER": 0.95, "BRONZE": 0.9, "IRON": 0.85,
}

# Difficulty penalty for low elo (champions with difficulty >=7 get a score penalty)
HIGH_DIFFICULTY = {238, 64, 157, 84, 28, 141, 92, 147, 164, 245, 240, 223, 234}

POSITION_MAP = {"top":"top","jungle":"jungle","mid":"mid","bottom":"bot","bot":"bot","utility":"support","support":"support"}

# ── Global stats (loaded from merged file if present) ──
_global_stats: dict | None = None


def _load_global_stats():
    """Load global_stats.json if available."""
    global _global_stats
    if _global_stats is not None:
        return
    try:
        import os, sys, json
        if getattr(sys, 'frozen', False):
            data_dir = os.path.join(sys._MEIPASS, "data")
        else:
            data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        path = os.path.join(data_dir, "global_stats.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                _global_stats = json.load(f)
    except Exception:
        _global_stats = {}


def _get_personal_counter(champion_id: int, enemy_id: int,
                           mapped_role: str, my_position: str) -> dict | None:
    """Get personal/global counter stats for a champion matchup.

    Priority: global stats (>=10 games) > personal stats (>=5 games)
    """
    # 1. Try global stats (multi-user aggregate)
    if _global_stats:
        try:
            cid_str = str(champion_id)
            eid_str = str(enemy_id)
            entry = (_global_stats.get("stats", {})
                     .get("counter_matchups", {})
                     .get(cid_str, {})
                     .get(mapped_role, {})
                     .get(eid_str))
            if entry and entry.get("g", 0) >= 10:
                g = entry["g"]
                w = entry["w"]
                wr = round(w / g * 100, 1)
                from stats_engine import _classify_game_counter, _classify_lane_counter
                gd10 = entry.get("gd10", 0)
                cd10 = entry.get("cd10", 0)
                xd10 = entry.get("xd10", 0)
                return {
                    "games": g, "wins": w, "win_rate": wr,
                    "game_counter": _classify_game_counter(wr),
                    "avg_gold_diff_10": gd10,
                    "avg_cs_diff_10": cd10,
                    "avg_xp_diff_10": xd10,
                    "lane_counter": _classify_lane_counter(gd10, cd10, xd10),
                }
        except Exception:
            pass

    # 2. Try personal local stats
    try:
        from stats_engine import get_counter_matchup_stats
        return get_counter_matchup_stats(champion_id, enemy_id, mapped_role, min_games=5)
    except Exception:
        pass

    return None


def _get_rank_modifier(rank_tier: str) -> dict:
    """Return rank-based scoring modifiers."""
    tier = rank_tier.upper() if rank_tier else ""
    meta_mult = RANK_META_WEIGHT.get(tier, 1.0)
    return {
        "meta_mult": meta_mult,
        "apply_diff_penalty": tier in ("IRON", "BRONZE", "SILVER"),
    }


def _pick_id(pick) -> int:
    if isinstance(pick, dict):
        return pick["champion_id"]
    return pick


def _build_opgg_counter_map(enemy_ids: list[int]) -> dict[int, dict[int, float]]:
    """Pre-load OP.GG counter data for enemy champions.
    Returns {enemy_id: {candidate_id: advantage_float}} where advantage > 0 means
    candidate counters enemy, advantage < 0 means candidate is countered.
    """
    result = {}
    if not enemy_ids:
        return result
    try:
        from meta_fetcher import _load_counters_cache, _fetch_opgg_champion_analysis, _save_counters_cache, COUNTERS_CACHE_HOURS
        import time
        cd_local = get_champion_data()
        for eid in enemy_ids:
            cached = _load_counters_cache(eid)
            if cached is None:
                ename = cd_local.champions.get(eid, {}).get("dd_id", "")
                erole = cd_local.get_role(eid)
                raw = _fetch_opgg_champion_analysis(ename, erole) if ename else None
                if raw:
                    _save_counters_cache(eid, raw, ename, erole)
                    cached = _load_counters_cache(eid)
            if not cached:
                continue
            entry = {}
            # weak_counters: enemy beats these — candidate is countered (negative advantage)
            for c in cached.get("weak_counters", []):
                entry[c["champion_id"]] = 50.0 - c.get("win_rate", 50)
            # strong_counters: enemy loses to these — candidate counters enemy (positive advantage)
            for c in cached.get("strong_counters", []):
                entry[c["champion_id"]] = c.get("win_rate", 50) - 50.0
            if entry:
                result[eid] = entry
    except Exception:
        pass
    return result


def recommend(my_position: str, enemy_ids: list[int] | None = None,
              banned_ids: list[int] | None = None,
              teammate_ids: list[int] | None = None, top_n: int = 12,
              rank_tier: str = "",
              teammate_positions: dict[int, str] | None = None) -> list[dict]:
    """7-dimension recommendation engine with optional rank-based adjustment."""
    if enemy_ids is None: enemy_ids = []
    if banned_ids is None: banned_ids = []
    if teammate_ids is None: teammate_ids = []
    if teammate_positions is None: teammate_positions = {}

    # Rank-based weight modifiers
    # High elo: meta matters more; Low elo: simple champions preferred
    rank_mod = _get_rank_modifier(rank_tier)

    used = set(banned_ids) | set(enemy_ids) | set(teammate_ids)
    scored = []

    opgg_counter_map = _build_opgg_counter_map(enemy_ids)

    for ckey in cd.all_champions():
        if ckey in used:
            continue

        # Hard filter: when position is specified, only consider champions
        # whose primary lane (highest play rate) matches the requested lane
        lane_rate = 0.0
        mapped = ""
        if my_position:
            mapped = POSITION_MAP.get(my_position.lower(), "")
            if mapped:
                lane_rates = dict(get_lane_rates(ckey))
                lane_rate = lane_rates.get(mapped, 0)
                primary_lane = max(lane_rates, key=lane_rates.get) if lane_rates else ""
                if primary_lane != mapped:
                    continue

        score = 0.0
        reasons = []
        meta = cd.get_meta(ckey)
        role = cd.get_role(ckey)

        # 1. Meta strength (rank-adjusted, with T0 detection)
        tier = meta.get("tier", "B")
        effective_tier = _get_effective_tier(ckey, meta)
        wr = meta.get("wr", 50.0)
        meta_score = TIER_BONUS.get(effective_tier, 6) + round((wr - 50) * 3.5, 1)
        meta_score *= rank_mod["meta_mult"]
        score += meta_score
        if effective_tier == "T0":
            reasons.append("T0级")
        elif tier == "S":
            reasons.append("版本强势")

        # Low-elo difficulty penalty
        if rank_mod["apply_diff_penalty"] and ckey in HIGH_DIFFICULTY:
            score -= 8

        # 2. Position match — only primary-lane heroes reach here
        position_match = False
        if my_position and mapped:
            if lane_rate >= 15.0:
                score += 45
                position_match = True
            elif lane_rate >= 5.0:
                score += 20
                position_match = True

        # 3. Counter / countered
        counter_score = 0; countered_score = 0
        c_ekeys = []; cd_ekeys = []

        for ek in enemy_ids:
            ek_role = cd.get_role(ek)
            lane_w = cd.get_lane_weight(my_position, ek_role) if my_position else 1.0

            c_s, c_ns = cd.get_counter_score(ckey, [ek])
            cd_s, cd_ns = cd.get_countered_score(ckey, [ek])

            c_s = int(c_s * lane_w)
            cd_s = int(cd_s * lane_w)

            if c_s >= 12:
                counter_score += c_s
                c_ekeys.append(ek)
            if cd_s >= 12:
                countered_score += cd_s
                cd_ekeys.append(ek)

        # Resolve conflicts
        conflict = set(c_ekeys) & set(cd_ekeys)
        for ek in conflict:
            ek_role = cd.get_role(ek)
            lane_w = cd.get_lane_weight(my_position, ek_role) if my_position else 1.0
            c_s, _ = cd.get_counter_score(ckey, [ek])
            cd_s, _ = cd.get_countered_score(ckey, [ek])
            c_s = int(c_s * lane_w); cd_s = int(cd_s * lane_w)
            if c_s >= cd_s:
                cd_ekeys.remove(ek); countered_score -= cd_s
            else:
                c_ekeys.remove(ek); counter_score -= c_s

        counter_names = [cd.get_name(ek) for ek in c_ekeys]
        countered_names = [cd.get_name(ek) for ek in cd_ekeys]

        if counter_names:
            reasons.insert(0, f"克制{'/'.join(counter_names)}")
        score += counter_score * 1.0

        if countered_names:
            reasons.append(f"被{'/'.join(countered_names)}克制")
        score -= countered_score * 0.8

        # 3b. Personal counter stats (game + lane counter, independent dimensions)
        for ek in enemy_ids:
            if my_position:
                pers_stats = _get_personal_counter(ckey, ek, mapped, my_position)
                if pers_stats:
                    game_counter = pers_stats["game_counter"]
                    if "克制" in game_counter and "被" not in game_counter:
                        bonus = 18 if "强" in game_counter else 10
                        counter_score += bonus
                        reasons.insert(0,
                            f"对局克制{cd.get_name(ek)}({pers_stats['win_rate']:.0f}%)")
                    elif "被克制" in game_counter:
                        penalty = 18 if "强" in game_counter else 10
                        countered_score += penalty
                        reasons.append(
                            f"对局被{cd.get_name(ek)}克制({pers_stats['win_rate']:.0f}%)")

                    lane_counter = pers_stats["lane_counter"]
                    gd10 = pers_stats.get("avg_gold_diff_10", 0)
                    if "克制" in lane_counter and "被" not in lane_counter:
                        reasons.append(f"对线压{cd.get_name(ek)}(+{gd10:.0f}g)")
                    elif "被克制" in lane_counter:
                        reasons.append(f"对线劣{cd.get_name(ek)}({gd10:.0f}g)")

            # 3c. OP.GG counter stats (win-rate based matchup data)
            if opgg_counter_map:
                for ek in enemy_ids:
                    ek_data = opgg_counter_map.get(ek, {})
                    if ckey in ek_data:
                        advantage = ek_data[ckey]
                        if abs(advantage) >= 2.0:
                            ek_name = cd.get_name(ek)
                            if advantage > 0:
                                bonus = round(min(advantage * 0.8, 15))
                                counter_score += bonus
                                reasons.insert(0, f"克制{ek_name}(OP.GG {50+advantage:.0f}%)")
                            else:
                                penalty = round(min(-advantage * 0.8, 15))
                                countered_score += penalty
                                reasons.append(f"被{ek_name}克制(OP.GG {50+advantage:.0f}%)")

        # 4. Synergy
        syn_score, syn_names = cd.get_synergy_score(ckey, teammate_ids)
        if syn_names:
            reasons.append(f"协同{'/'.join(syn_names)}")
        score += syn_score * 0.7

        # 5. Ban rate bonus
        br = meta.get("br", 2)
        if br > 8: score += 8
        elif br > 5: score += 4

        # 6. Position fill bonus (missing role gets priority)
        if teammate_positions:
            team_roles = set(teammate_positions.values())
        else:
            team_roles = {cd.get_role(p) for p in teammate_ids}
        if role not in team_roles and my_position:
            score += 15

        # 7. Bot lane synergy & 2v2 counter (only for bot/support positions)
        if my_position in ("bot", "support"):
            counterpart_pos = "support" if my_position == "bot" else "bot"
            # 7a. Synergy with existing counterpart teammate
            for tk in teammate_ids:
                if cd.get_role(tk) == counterpart_pos:
                    syn, _ = cd.get_synergy_score(ckey, [tk])
                    score += syn * 0.5
                    if syn >= 15:
                        reasons.append(f"组合{cd.get_name(tk)}")
                    break
            # 7b. 2v2: check both enemy bot + enemy support together
            enemy_bot = [e for e in enemy_ids if cd.get_role(e) == "bot"]
            enemy_supp = [e for e in enemy_ids if cd.get_role(e) == "support"]
            enemy_duo = enemy_bot + enemy_supp
            if len(enemy_duo) >= 1:
                # How well we counter the enemy duo
                duo_counter = 0
                for ek in enemy_duo:
                    cs, _ = cd.get_counter_score(ckey, [ek])
                    if cs >= 12:
                        duo_counter += cs
                    cds, _ = cd.get_countered_score(ckey, [ek])
                    if cds >= 12:
                        duo_counter -= cds * 0.8
                if duo_counter >= 20:
                    score += 15
                    reasons.append("克制敌方下路")
                elif duo_counter <= -15:
                    score -= 12
                    reasons.append("被敌方下路克制")
                elif duo_counter >= 10:
                    score += 6
            # 7c. (ADC only) Team composition fit
            if my_position == "bot" and (len(teammate_ids) >= 2 or len(enemy_ids) >= 2):
                from engine import analyze_composition
                my_comp = analyze_composition(tuple(teammate_ids + [ckey]))
                enemy_comp = analyze_composition(tuple(enemy_ids))
                comp_score = my_comp.get("score", 0)
                # Prefer ADC that fits our composition or counters enemy comp
                if comp_score >= 12:
                    score += 10
                    reasons.append(f"契合阵容({my_comp.get('name','')})")
                elif comp_score >= 8:
                    score += 4

        scored.append({
            "champion_id": ckey,
            "name": cd.get_name(ckey),
            "image_url": cd.get_image(ckey),
            "role": mapped if (my_position and position_match) else role,
            "tier": effective_tier,
            "winrate": wr,
            "score": round(score, 1),
            "position_match": position_match,
            "reasons": reasons if reasons else ["稳定选择"],
        })

    scored.sort(key=lambda x: (-x["score"], -x["winrate"]))

    # Position coverage: when filtering by a specific lane, only ensure that
    # lane has at least one pick (don't inject off-lane champions).
    # When showing all positions, ensure all 5 roles are covered.
    POSITIONS = ["top", "jungle", "mid", "bot", "support"]
    result = scored[:top_n]
    covered = {r["role"] for r in result}

    if my_position:
        mapped = POSITION_MAP.get(my_position.lower(), "")
        missing = [mapped] if mapped and mapped not in covered else []
    else:
        missing = [p for p in POSITIONS if p not in covered]

    # Pre-cache role filters to avoid repeated calls
    role_champs = {pos: cd.filter_by_role(pos) for pos in missing}
    result_champ_ids = {r["champion_id"] for r in result}

    for pos in missing:
        best = None
        for ckey in role_champs[pos]:
            if ckey in used or ckey in result_champ_ids:
                continue
            m = cd.get_meta(ckey)
            wr_val = m.get("wr", 50)
            if best is None or wr_val > best["wr"]:
                best = {"champion_id": ckey, "wr": wr_val, "meta": m}
        if best:
            m = best["meta"]
            result.append({
                "champion_id": best["champion_id"],
                "name": cd.get_name(best["champion_id"]),
                "image_url": cd.get_image(best["champion_id"]),
                "role": pos,
                "tier": m.get("tier","B"),
                "winrate": m.get("wr",50.0),
                "score": max(0, round((m.get("wr",50)-48)*2.5,1)),
                "position_match": my_position and pos==my_position,
                "reasons": ["对线优势"],
            })

    result.sort(key=lambda x: (-x["score"], -x["winrate"]))
    return result[:top_n]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"Loaded {len(cd.champions)} champions (version {cd.version})")
    recs = recommend("mid", [157, 64, 89], [])
    print(f"\nTop 5 mid picks vs Yasuo, Lee Sin, Leona:")
    for i, r in enumerate(recs[:5]):
        reason_str = ", ".join(r["reasons"]) if r["reasons"] else "-"
        print(f"  #{i+1}  {r['name']:12s}  {r['tier']}  WR {r['winrate']:.1f}%  +{r['score']:.0f}  [{reason_str}]")
