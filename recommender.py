"""
LoL BP Assistant — Iteration 4: Data Source Integration
Replaced hardcoded CHAMPIONS with ChampionData (Data Dragon + OP.GG).
"""

import logging

from champion_data import get_champion_data

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


def recommend(my_position: str, enemy_ids: list[int] | None = None,
              banned_ids: list[int] | None = None,
              teammate_ids: list[int] | None = None, top_n: int = 12,
              rank_tier: str = "") -> list[dict]:
    """7-dimension recommendation engine with optional rank-based adjustment."""
    if enemy_ids is None: enemy_ids = []
    if banned_ids is None: banned_ids = []
    if teammate_ids is None: teammate_ids = []

    # Rank-based weight modifiers
    # High elo: meta matters more; Low elo: simple champions preferred
    rank_mod = _get_rank_modifier(rank_tier)

    used = set(banned_ids) | set(enemy_ids) | set(teammate_ids)
    scored = []

    for ckey in cd.all_champions():
        if ckey in used:
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

        # 2. Position match (heavily weighted to prefer on-role picks)
        position_match = False
        if my_position:
            mapped = POSITION_MAP.get(my_position.lower(), "")
            if mapped and role == mapped:
                score += 45
                position_match = True
            elif mapped:
                # Off-role penalty: only overcome by strong counter/synergy
                score -= 12

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
            "role": role,
            "tier": effective_tier,
            "winrate": wr,
            "score": round(score, 1),
            "position_match": position_match,
            "reasons": reasons if reasons else ["稳定选择"],
        })

    scored.sort(key=lambda x: (-x["score"], -x["winrate"]))

    # Position coverage: ensure all 5 roles have at least 1 recommendation
    POSITIONS = ["top", "jungle", "mid", "bot", "support"]
    result = scored[:top_n]
    covered = {r["role"] for r in result}
    missing = [p for p in POSITIONS if p not in covered]
    if my_position and my_position in missing:
        missing.remove(my_position); missing.insert(0, my_position)

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
