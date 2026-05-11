"""
LoL BP Assistant — Iteration 7: Ban Recommendations + Composition Analysis.
Pick recommendation is in recommender.py; this adds ban and composition.
"""

import functools
from champion_data import get_champion_data

cd = get_champion_data()


# ── Ban Recommendation (4 dimensions, based on prepicks) ─────────────────────

def _get_matchup_from_stats(champion_id: int, enemy_id: int,
                             lane: str) -> dict | None:
    """Get matchup stats from personal/global data. Returns None if insufficient."""
    try:
        from stats_engine import get_counter_matchup_stats
        return get_counter_matchup_stats(champion_id, enemy_id, lane, min_games=5)
    except Exception:
        return None


def build_ban_recommendations(used_ids, my_prepicks, enemy_prepicks, my_position,
                              teammate_pool=None, per_role=5):
    """返回五个分路的 Ban 推荐，每个分路 top N。"""
    if teammate_pool is None:
        teammate_pool = {}

    # 按分路分组评分
    role_buckets = {"top": [], "jungle": [], "mid": [], "bot": [], "support": []}

    for ckey in cd.all_champions():
        if ckey in used_ids:
            continue

        score = 0.0
        reasons = []
        meta = cd.get_meta(ckey)
        c_role = cd.get_role(ckey)

        # 1. Meta threat (with T0 detection)
        tier = meta.get("tier", "B")
        wr_m = meta.get("wr", 50)
        pr_m = meta.get("pr", 3)
        br_m = meta.get("br", 2)
        is_t0 = (tier == "S" and wr_m >= 52.0 and (pr_m >= 8.0 or br_m >= 8.0))
        if is_t0:
            score += 35
            reasons.append("T0级威胁")
        elif tier == "S":
            score += 25
            reasons.append("S级威胁")
        elif tier == "A":
            score += 15
            reasons.append("版本强势")

        wr = meta.get("wr", 50)
        if wr > 52:
            score += round((wr - 52) * 1.5, 1)

        br = meta.get("br", 2)
        if br > 8:
            score += 8

        # 2. Enemy prepick synergy — ban heroes that synergize with enemy prepicks
        champ_arches = set(cd.get_archetypes(ckey))
        for ek in enemy_prepicks:
            ek_arches = set(cd.get_archetypes(ek))
            best_syn = 0
            for a1 in champ_arches:
                for a2 in ek_arches:
                    pair = "+".join(sorted([a1, a2]))
                    best_syn = max(best_syn, cd.synergy_rules.get(pair, 0))
            if best_syn > 0.4:
                score += 22
                reasons.append(f"配合敌方{cd.get_name(ek)}")

        # 3. Counters my prepicks
        for mk in my_prepicks:
            cd_s, _ = cd.get_countered_score(mk, [ckey])
            if cd_s >= 12:
                score += 20
                reasons.append(f"克制我方{cd.get_name(mk)}")

        # 4. Teammate proficiency penalty — don't ban what teammates are good at
        if ckey in teammate_pool:
            score -= 15
            reasons.append("队友擅长")

        if not reasons:
            reasons.append("综合威胁")

        entry = {
            "champion_id": ckey,
            "name": cd.get_name(ckey),
            "image_url": cd.get_image(ckey),
            "role": c_role,
            "tier": "T0" if is_t0 else tier,
            "winrate": meta.get("wr", 50.0),
            "score": round(score, 1),
            "reasons": reasons,
        }

        if c_role in role_buckets:
            role_buckets[c_role].append(entry)

    # 每个分路按分数排序取 top N
    result = {}
    for role in ["top", "jungle", "mid", "bot", "support"]:
        role_buckets[role].sort(key=lambda x: -x["score"])
        result[role] = role_buckets[role][:per_role]

    return result


# ── Composition Analysis (7 types) ────────────────────────────────────────────

COMPOSITION_PATTERNS = {
    "dive": {
        "name": "冲阵强开", "icon": "🏃",
        "tags": {"engage": 3, "dive": 3, "burst": 2, "teamfight-aoe": 2,
                 "mobility": 1, "assassin": 1, "tank": 1},
        "anti": {"poke": -2, "disengage": -2},
    },
    "poke": {
        "name": "拉扯消耗", "icon": "🏹",
        "tags": {"poke": 3, "siege": 3, "disengage": 2, "zone-control": 1, "utility-adc": 1},
        "anti": {"engage": -2, "dive": -2},
    },
    "protect": {
        "name": "保排输出", "icon": "🛡️",
        "tags": {"peel": 3, "hypercarry-enabler": 3, "utility": 2,
                 "hypercarry": 2, "tank": 1, "dps": 1},
        "anti": {"split-push": -1},
    },
    "split": {
        "name": "分带牵制", "icon": "⚔️",
        "tags": {"split-push": 3, "duel": 2, "mobility": 2, "sustain": 1, "bruiser": 1},
        "anti": {"teamfight-aoe": -2, "engage": -2},
    },
    "pick": {
        "name": "抓单击杀", "icon": "🔪",
        "tags": {"pick": 3, "burst": 2, "assassin": 2, "mobility": 1, "control-mage": 1},
        "anti": {"peel": -2, "tank": -1},
    },
    "wombo": {
        "name": "团战连控", "icon": "💥",
        "tags": {"teamfight-aoe": 3, "engage": 3, "zone-control": 2, "burst": 1, "tank": 1},
        "anti": {"split-push": -2, "disengage": -2},
    },
}


@functools.lru_cache(maxsize=256)
def analyze_composition(pick_ids: tuple):
    """Analyze team composition. pick_ids should be a tuple for caching.

    Cached for performance (called multiple times during ADC recommendation).
    """
    if len(pick_ids) < 2:
        return {"type": "unformed", "name": "阵容未成形", "icon": "", "archetypes": [], "score": 0}

    tag_counts = {}
    all_arches = []
    for pk in pick_ids:
        arches = cd.get_archetypes(pk)
        all_arches.extend(arches)
        for a in arches:
            tag_counts[a] = tag_counts.get(a, 0) + 1

    results = []
    for comp_type, pattern in COMPOSITION_PATTERNS.items():
        score = 0
        for tag, weight in pattern["tags"].items():
            score += tag_counts.get(tag, 0) * weight
        for anti_tag, penalty in pattern["anti"].items():
            score += tag_counts.get(anti_tag, 0) * penalty
        results.append((comp_type, score))

    results.sort(key=lambda x: -x[1])
    best_type, best_score = results[0]

    if best_score < 5:
        return {"type": "balanced", "name": "均衡阵容", "icon": "⚖️",
                "archetypes": sorted(set(all_arches)), "score": best_score}

    pattern = COMPOSITION_PATTERNS[best_type]
    return {"type": best_type, "name": pattern["name"], "icon": pattern["icon"],
            "archetypes": sorted(set(all_arches)), "score": best_score}


# ── Manual build helper ───────────────────────────────────────────────────────

def manual_build(manual_state):
    """Build recommendations from manual state dict."""
    from recommender import recommend

    my_picks_raw = manual_state.get("my_picks", [])
    enemy_picks_raw = manual_state.get("enemy_picks", [])

    def _pick_id(p):
        return p["champion_id"] if isinstance(p, dict) else p

    my_picks = [_pick_id(p) for p in my_picks_raw]
    enemy_picks = [_pick_id(p) for p in enemy_picks_raw]
    all_banned = set(manual_state.get("my_bans", []) + manual_state.get("enemy_bans", []))
    all_picked = set(my_picks + enemy_picks)
    used = all_banned | all_picked

    recs = recommend(manual_state.get("my_position", ""), enemy_picks,
                     list(all_banned), my_picks)
    return recs


# ── Iteration 10: Rune & Summoner Spell Recommendations ─────────────────────

def recommend_runes_spells(our_team: dict[str, int],
                           enemy_team: dict[str, int]) -> dict[str, dict]:
    """
    Recommend runes and summoner spells for all 10 players.
    our_team/enemy_team: {lane: champion_id}
    Returns: {f"{side}_{lane}": {"runes": [...], "spells": [...]}}
    """
    from tencent_fetcher import get_runes, get_spells

    result = {}

    for side, team in [("我方", our_team), ("敌方", enemy_team)]:
        for lane, ckey in team.items():
            runes = get_runes(ckey, lane)
            spells = get_spells(ckey, lane)
            result[f"{side}_{lane}"] = {
                "champion_id": ckey,
                "champion_name": cd.get_name(ckey),
                "lane": lane,
                "runes": runes,
                "spells": spells,
            }

    return result


# ── Iteration 11: Lane Matchup Win Rate Prediction ──────────────────────────

# Lane influence weights for 4 lanes (bot+support merged into "bottom")
LANE_INFLUENCE = {"mid": 0.28, "bottom": 0.27, "jungle": 0.25, "top": 0.20}


def predict_matchups(our_team: dict[str, int],
                     enemy_team: dict[str, int]) -> dict:
    """
    Predict lane win rates (4 lanes: top/jungle/mid/bottom) and game win rate.
    Bottom lane merges bot+support into a 2v2 prediction.
    Returns:
      lane_winrate: per-lane matchup predictions
      game_winrate: overall team composition win rate
    """
    FOUR_LANES = ["top", "jungle", "mid", "bottom"]
    lane_predictions = {}
    lane_weighted_sum = 0.0
    lane_total_weight = 0.0

    for lane in FOUR_LANES:
        if lane == "bottom":
            # ── 2v2 bottom lane: merge bot + support ──
            our_adc = our_team.get("bot")
            our_supp = our_team.get("support")
            enemy_adc = enemy_team.get("bot")
            enemy_supp = enemy_team.get("support")

            if not our_adc and not our_supp and not enemy_adc and not enemy_supp:
                lane_predictions[lane] = {"our_wr": 50.0, "verdict": "暂无数据",
                                           "our_heroes": [], "enemy_heroes": []}
                continue

            # Compute 4 individual matchup scores for the 2v2
            scores = []
            pairs = [
                (our_adc, enemy_adc, "bot"), (our_adc, enemy_supp, "bot"),
                (our_supp, enemy_adc, "support"), (our_supp, enemy_supp, "support"),
            ]
            for our, enemy, pos in pairs:
                if our and enemy:
                    from meta_fetcher import get_opgg_matchup
                    opgg = get_opgg_matchup(our, enemy, pos)
                    if opgg and opgg.get("games", 0) >= 50:
                        scores.append(opgg.get("advantage", 0))
                    else:
                        c_score, _ = cd.get_counter_score(our, [enemy])
                        cd_score, _ = cd.get_countered_score(our, [enemy])
                        scores.append((c_score - cd_score) * 0.6)
                else:
                    scores.append(0)

            # Weighted: ADC matchups matter more for the lane outcome
            avg_advantage = (scores[0] * 0.35 + scores[1] * 0.15 +
                             scores[2] * 0.15 + scores[3] * 0.35)
            our_wr = 50.0 + avg_advantage / 2

            # Bot lane synergy bonus
            if our_adc and our_supp:
                syn, _ = cd.get_synergy_score(our_adc, [our_supp])
                our_wr += min(syn * 0.15, 4.0)
            if enemy_adc and enemy_supp:
                syn, _ = cd.get_synergy_score(enemy_adc, [enemy_supp])
                our_wr -= min(syn * 0.15, 4.0)

            our_heroes = [cd.get_name(h) for h in [our_adc, our_supp] if h]
            enemy_heroes = [cd.get_name(h) for h in [enemy_adc, enemy_supp] if h]
        else:
            our_hero = our_team.get(lane)
            enemy_hero = enemy_team.get(lane)

            if not our_hero or not enemy_hero:
                our_heroes = [cd.get_name(our_hero)] if our_hero else []
                enemy_heroes = [cd.get_name(enemy_hero)] if enemy_hero else []
                lane_predictions[lane] = {"our_wr": 50.0, "verdict": "暂无数据",
                                           "our_heroes": our_heroes, "enemy_heroes": enemy_heroes}
                continue

            # Three-tier data source: personal stats > OP.GG > built-in matrix
            pers = _get_matchup_from_stats(our_hero, enemy_hero, lane)
            if pers:
                wr_delta = (pers["win_rate"] - 50.0) * 2
                our_wr = 50.0 + wr_delta / 2
                gd10 = pers.get("avg_gold_diff_10", 0)
                our_wr += max(-3.0, min(3.0, gd10 / 200))
            else:
                from meta_fetcher import get_opgg_matchup
                opgg = get_opgg_matchup(our_hero, enemy_hero, lane)
                if opgg and opgg.get("games", 0) >= 50:
                    advantage = opgg.get("advantage", 0)
                    our_wr = 50.0 + advantage / 2
                else:
                    c_score, _ = cd.get_counter_score(our_hero, [enemy_hero])
                    cd_score, _ = cd.get_countered_score(our_hero, [enemy_hero])
                    our_wr = 50.0 + (c_score - cd_score) * 0.3

            our_heroes = [cd.get_name(our_hero)]
            enemy_heroes = [cd.get_name(enemy_hero)]

        our_wr = max(20.0, min(80.0, our_wr))
        verdict = "优势" if our_wr >= 53 else ("劣势" if our_wr <= 47 else "均势")

        lane_predictions[lane] = {
            "our_heroes": our_heroes,
            "enemy_heroes": enemy_heroes,
            "our_wr": round(our_wr, 1),
            "verdict": verdict,
        }

        weight = LANE_INFLUENCE.get(lane, 0.25)
        lane_weighted_sum += our_wr * weight
        lane_total_weight += weight

    # ── Lane win rate (pure matchup-based) ──
    lane_wr = round(lane_weighted_sum / lane_total_weight, 1) if lane_total_weight > 0 else 50.0

    # ── Game win rate (lane WR + composition analysis) ──
    our_pick_ids = [v for v in our_team.values() if v]
    enemy_pick_ids = [v for v in enemy_team.values() if v]
    our_comp = analyze_composition(tuple(our_pick_ids))
    enemy_comp = analyze_composition(tuple(enemy_pick_ids))

    # Composition modifier: comp score advantage contributes ±up to 5% WR
    comp_modifier = (our_comp.get("score", 0) - enemy_comp.get("score", 0)) * 0.3
    comp_modifier = max(-5.0, min(5.0, comp_modifier))

    game_wr = round(lane_wr + comp_modifier, 1)
    game_wr = max(20.0, min(80.0, game_wr))
    game_verdict = "优势" if game_wr >= 53 else ("劣势" if game_wr <= 47 else "均势")

    return {
        "lane_winrate": {
            "lanes": lane_predictions,
            "our_wr": lane_wr,
            "verdict": "优势" if lane_wr >= 53 else ("劣势" if lane_wr <= 47 else "均势"),
        },
        "game_winrate": {
            "our_wr": game_wr,
            "enemy_wr": round(100.0 - game_wr, 1),
            "verdict": game_verdict,
            "our_comp": our_comp.get("name", ""),
            "enemy_comp": enemy_comp.get("name", ""),
        },
    }
