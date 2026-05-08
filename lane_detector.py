"""
LoL BP Assistant — Iteration 8: Enemy Lane Detection
Greedy algorithm to predict which lane each enemy champion goes to.
Each lane can only have one champion. Conflicts resolved by lane pick rate.
"""

import json
import os
import sys
import logging
import functools

logger = logging.getLogger(__name__)

from champion_data import get_champion_data

cd = get_champion_data()

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(sys._MEIPASS, "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

LANE_DIST_CACHE = os.path.join(DATA_DIR, "lane_distribution.json")

LANES = ["top", "jungle", "mid", "bot", "support"]


def build_lane_distribution() -> dict[str, dict[str, float]]:
    """
    Build per-champion lane distribution from OP.GG meta cache.
    Returns {champion_name_lower: {lane: pick_rate_percent}}.
    """
    meta_cache = os.path.join(DATA_DIR, "champion_meta_live.json")
    dist = {}

    if not os.path.exists(meta_cache):
        return dist

    try:
        with open(meta_cache, "r", encoding="utf-8") as f:
            cached = json.load(f)
        meta = cached.get("meta", {})
    except Exception:
        return dist

    # Collect per-champion lane pick rates from OP.GG data
    # OP.GG returns per-lane meta: each champion entry has a role and pickrate
    # We need to aggregate: for each champion, collect pickrate in each lane
    champ_lanes: dict[str, dict[str, float]] = {}
    for ckey_str, m in meta.items():
        ckey = int(ckey_str)
        name = cd.get_name(ckey).lower()
        role = m.get("role", cd.get_role(ckey))
        pr = m.get("pr", 0)
        if name not in champ_lanes:
            champ_lanes[name] = {}
        champ_lanes[name][role] = pr

    # Normalize to percentages
    for name, lanes in champ_lanes.items():
        total = sum(lanes.values()) or 1
        dist[name] = {lane: round(rate / total * 100, 1) for lane, rate in lanes.items()}

    # Cache
    with open(LANE_DIST_CACHE, "w", encoding="utf-8") as f:
        json.dump(dist, f, ensure_ascii=False)

    return dist


def _load_distribution() -> dict[str, dict[str, float]]:
    if os.path.exists(LANE_DIST_CACHE):
        try:
            with open(LANE_DIST_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return build_lane_distribution()


# ── Tag-based lane distribution weights ──────────────────────────────────────
# Relative weights for each tag across 5 lanes (will be normalized to %)
TAG_LANE_PROBS = {
    "Fighter":  {"top": 50, "jungle": 30, "mid": 15, "bot": 3, "support": 2},
    "Tank":     {"top": 45, "jungle": 25, "support": 20, "mid": 8, "bot": 2},
    "Assassin": {"mid": 55, "jungle": 30, "top": 12, "bot": 2, "support": 1},
    "Mage":     {"mid": 60, "support": 22, "top": 8, "bot": 8, "jungle": 2},
    "Marksman": {"bot": 85, "mid": 8, "top": 5, "jungle": 1, "support": 1},
    "Support":  {"support": 80, "mid": 12, "top": 5, "bot": 2, "jungle": 1},
}

# Known flex picks: champions regularly played in multiple roles
# {champion_id: {alternative_role: weight_modifier}}
FLEX_PICKS = {
    # Top/JG flex
    24:  {"jungle": 25},   # 武器大师 top→jg
    122: {"jungle": 15},   # 诺手 top→jg (rare)
    # Mid/Top flex
    157: {"top": 35},      # 疾风剑豪 mid→top
    238: {"top": 15},      # 影流之主 mid→top (rare)
    55:  {"top": 10},      # 不祥之刃 mid→top
    # JG/Mid flex
    245: {"mid": 25},      # 时间刺客 jg→mid
    28:  {"mid": 20},      # 寡妇制造者 jg→mid
    # Mid/Sup flex
    63:  {"mid": 30},      # 复仇焰魂 sup→mid
    50:  {"mid": 25},      # 诺克萨斯统领 sup→mid
    99:  {"mid": 25},      # 深海泰坦 sup→mid (rare)
    # Bot/Mid flex
    115: {"mid": 20},      # 爆破鬼才 bot→mid
    22:  {"support": 5},   # 寒冰射手 bot→sup (rare)
    81:  {"mid": 8},       # 探险家 bot→mid
    # Top/Mid flex
    91:  {"mid": 40},      # 刀锋舞者 top→mid
    266: {"mid": 25},      # 暗裔剑魔 top→mid
    41:  {"mid": 15},      # 海洋之灾 top→mid
}

@functools.lru_cache(maxsize=256)
def get_lane_rates(champion_key: int) -> list[tuple[str, float]]:
    """Return lane distribution for a champion, sorted by rate descending.

    Uses multi-source data: OP.GG meta → Data Dragon tags → MANUAL_ROLE → flex picks.
    Cached for performance (called frequently in recommendation loops).
    """
    name = cd.get_name(champion_key).lower()
    dist = _load_distribution()

    # Start from OP.GG meta lane distribution if available, otherwise from tags
    if name in dist and len(dist[name]) > 0:
        # OP.GG distribution exists — use it as base
        opgg_rates = dict(dist[name])
    else:
        opgg_rates = {}

    # Build tag-based rates
    tags = cd.get_tags(champion_key)
    tag_rates = {lane: 0.0 for lane in LANES}
    if tags:
        for tag in tags:
            probs = TAG_LANE_PROBS.get(tag, {})
            for lane in LANES:
                tag_rates[lane] += probs.get(lane, 0)
        # Normalize tag rates to 100%
        total = sum(tag_rates.values()) or 1.0
        tag_rates = {lane: v / total * 100 for lane, v in tag_rates.items()}
    else:
        # No tags — fallback to MANUAL_ROLE
        default_role = cd.get_role(champion_key)
        tag_rates = {lane: (85.0 if lane == default_role else 3.0) for lane in LANES}

    # Blend: OP.GG data is more accurate for primary role, tags for secondary
    if opgg_rates:
        # OP.GG gives us the primary role distribution → use 70% OP.GG + 30% tags
        rates = {}
        for lane in LANES:
            rates[lane] = opgg_rates.get(lane, 0) * 0.7 + tag_rates.get(lane, 0) * 0.3
    else:
        rates = dict(tag_rates)

    # Apply flex pick modifiers
    flex = FLEX_PICKS.get(champion_key, {})
    for lane, bonus in flex.items():
        primary_role = cd.get_role(champion_key)
        if lane != primary_role:
            rates[lane] = rates.get(lane, 0) + bonus
            # Reduce primary role by the bonus amount
            if primary_role in rates:
                rates[primary_role] = max(5, rates[primary_role] - bonus * 0.5)

    # Ensure minimum rate for backfill and normalize
    for lane in LANES:
        if rates.get(lane, 0) < 3.0:
            rates[lane] = 3.0

    # Normalize to 100%
    total = sum(rates.values()) or 1.0
    rates = {lane: round(v / total * 100, 1) for lane, v in rates.items()}

    result = [(lane, rates[lane]) for lane in LANES]
    result.sort(key=lambda x: -x[1])
    return result


def predict_enemy_lanes(enemy_pick_ids: list[int]) -> dict[str, int]:
    """
    Predict lane assignments for enemy picks.
    Returns {lane: champion_id}. Unassigned lanes are not present.

    Algorithm:
    1. For each champion, get lane rates sorted by popularity.
    2. Collect all (hero, lane, rate) triples, sort by rate descending.
    3. Greedy assign: highest rate hero gets their preferred lane first.
    """
    triples = []
    for ckey in enemy_pick_ids:
        for lane, rate in get_lane_rates(ckey):
            if rate > 0:
                triples.append((ckey, lane, rate))

    # Sort by rate descending
    triples.sort(key=lambda x: -x[2])

    assigned_lanes: dict[str, int] = {}
    assigned_heroes: set[int] = set()

    for ckey, lane, rate in triples:
        if ckey not in assigned_heroes and lane not in assigned_lanes:
            assigned_lanes[lane] = ckey
            assigned_heroes.add(ckey)

    # Assign remaining to empty lanes
    unassigned = [ckey for ckey in enemy_pick_ids if ckey not in assigned_heroes]
    empty = [lane for lane in LANES if lane not in assigned_lanes]
    for ckey, lane in zip(unassigned, empty):
        assigned_lanes[lane] = ckey

    return assigned_lanes


# ── CLI test ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Test with a classic ambiguous comp
    # Yasuo(157, mid primary), Zed(238, mid primary), Lee Sin(64, jungle)
    # Jinx(115, bot), Leona(89, support)
    # Zed should go top (secondary) since Yasuo has higher mid rate
    test_picks = [157, 238, 64, 115, 89]

    print("Enemy picks:")
    for pk in test_picks:
        rates = get_lane_rates(pk)
        rate_str = " | ".join(f"{l}:{r:.0f}%" for l, r in rates if r > 0)
        print(f"  {cd.get_name(pk):10s}  {rate_str}")

    lanes = predict_enemy_lanes(test_picks)
    print("\nPredicted lanes:")
    for lane in LANES:
        if lane in lanes:
            print(f"  {lane:8s} → {cd.get_name(lanes[lane])}")
