"""
LoL BP Assistant — LCU Auto Mode Runner.
Polls LCU for champ select, feeds data to recommender with state dedup.
"""
import time
import hashlib
import json
import logging

from recommender import recommend
from champion_data import get_champion_data
from engine import (
    build_ban_recommendations,
    analyze_composition,
    recommend_runes_spells,
    predict_matchups,
)
from lcu import poll_lcu, fetch_teammate_mastery, parse_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

cd = get_champion_data()

champ_select_state = {
    "connected": False, "in_champ_select": False, "gameflow_phase": "",
    "my_team_bans": [], "enemy_bans": [],
    "my_team_picks": [], "enemy_picks": [],
    "my_prepicks": [], "enemy_prepicks": [], "my_position": "",
    "phase": "BAN_PICK", "recommendations": [],
    "timer": {"phase": "idle", "total_sec": 0, "remaining_sec": 0},
    "action_seq": [], "next_action": None,
}

lcu_connection = {"headers": {}, "base_url": "", "active": False}

_manual_mode = False
_last_state_hash = ""
_last_action_key = ""   # dedup by action change, not just time
_last_rec_time = 0.0
_final_summary_shown = False
_status_card_shown = False  # data status card already shown for this champ select

MIN_REC_INTERVAL = 2.0  # seconds between SAME-action re-recommendations


def _manual_ref():
    return _manual_mode


def _show_status_once():
    """Show data source status card once per champ select entry.
    Reset signal: lcu.py sets lcu_connection['_cs_restart'] = True on champ select exit.
    """
    global _status_card_shown
    if lcu_connection.get("_cs_restart"):
        _status_card_shown = False
        lcu_connection["_cs_restart"] = False
    if not _status_card_shown:
        _print_data_status()
        _status_card_shown = True


def _action_key(parsed):
    """Compute a short key for the current action(s) — changes trigger immediate display."""
    na = parsed.get("next_actions", [])
    if not na:
        return ""
    parts = sorted(
        f"{a.get('type','')}|{a.get('is_mine','')}|{a.get('is_self','')}|{a.get('position','')}"
        for a in na
    )
    return "|".join(parts)


def _check_meta_source():
    """Check if OP.GG live meta is available."""
    import os, sys, time, json
    if getattr(sys, 'frozen', False):
        data_dir = os.path.join(sys._MEIPASS, "data")
    else:
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    cache = os.path.join(data_dir, "champion_meta_live.json")
    if os.path.exists(cache):
        try:
            with open(cache, "r", encoding="utf-8") as f:
                d = json.load(f)
            age_h = (time.time() - d.get("cached_at", 0)) / 3600
            if age_h < 48:
                return f"OP.GG 实时 ({age_h:.0f}h前)"
            return f"OP.GG 缓存 ({age_h:.0f}h前, 已过期)"
        except Exception:
            pass
    return "内置硬编码"


def _print_data_status():
    """Print data source status card at champ select entry."""
    ranks = lcu_connection.get("ranks", {})
    queue_name = lcu_connection.get("queue_name", "")
    meta_src = _check_meta_source()

    # Count cached Tencent champion details
    tc_count = 0
    try:
        import os, sys
        if getattr(sys, 'frozen', False):
            dd = os.path.join(sys._MEIPASS, "data", "champ_detail")
        else:
            dd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "champ_detail")
        if os.path.isdir(dd):
            tc_count = len([f for f in os.listdir(dd) if f.endswith('.json')])
    except Exception:
        pass
    tc_info = f"腾讯101 CDN ({tc_count}英雄)" if tc_count > 0 else "腾讯101 CDN (按需)"

    # Rank-adjusted strategy (weights match recommender.RANK_META_WEIGHT)
    rank_tier = ""
    if queue_name and "排位" in queue_name:
        qk = lcu_connection.get("queue_key", "")
        r = ranks.get(qk, ranks.get("solo_duo", {}))
        rank_tier = r.get("display", "") if r else ""
    RANK_STRATEGY_DISPLAY = {
        "王者": "Meta 优先 ×1.30", "宗师": "Meta 优先 ×1.25",
        "大师": "Meta 优先 ×1.20", "钻石": "Meta 优先 ×1.15",
        "翡翠": "Meta 优先 ×1.10", "铂金": "标准权重 ×1.05",
        "黄金": "标准权重", "白银": "稳健优先 (高操作扣分)",
        "青铜": "稳健优先 (高操作扣分)", "黑铁": "稳健优先 ×0.85",
    }
    strategy = "标准权重"
    if rank_tier:
        for t, s in RANK_STRATEGY_DISPLAY.items():
            if t in rank_tier:
                strategy = s
                break

    conn_status = "✓ 已连接" if lcu_connection.get("active") else "✗ 未连接"
    rank_status = "✗ 未获取"
    if ranks:
        parts = [f"{l}:{r['display']}" for l, r in ranks.items()]
        rank_status = "✓ " + "  ".join(parts)
    mode_status = f"✓ {queue_name}" if queue_name and "未知" not in queue_name else "✗ 未检测"

    print(f"""
  ┌─ 数据源状态 ─────────────────────────────────────┐
  │ LCU:  {conn_status:<38s} │
  │ 段位: {rank_status:<38s} │
  │ 模式: {mode_status:<38s} │
  │                                                  │
  │ 推荐策略: {strategy:<36s} │
  │                                                  │
  │ Meta 数据 │ {meta_src:<32s} │
  │ 符文      │ {tc_info:<32s} │
  │ 技能      │ {tc_info:<32s} │
  │ 对位胜率  │ 内置克制矩阵 (估算值):16s              │
  │ 分路检测  │ 标签概率 + OP.GG 混合:16s              │
  └──────────────────────────────────────────────────┘""")


def _state_hash(parsed):
    """Compute a hash of recommendation-relevant state fields."""
    key_data = {
        "my_bans": sorted(parsed.get("my_team_bans", [])),
        "enemy_bans": sorted(parsed.get("enemy_bans", [])),
        "my_picks": sorted(
            (p["champion_id"], p.get("position", ""))
            for p in parsed.get("my_team_picks", [])
        ),
        "enemy_picks": sorted(
            (p["champion_id"], p.get("position", ""))
            for p in parsed.get("enemy_picks", [])
        ),
        "my_prepicks": sorted(parsed.get("my_prepicks", [])),
        "enemy_prepicks": sorted(parsed.get("enemy_prepicks", [])),
        "my_position": parsed.get("my_position", ""),
        "next_actions": [(a.get("type"), a.get("is_mine"), a.get("is_self"), a.get("position"))
                         for a in parsed.get("next_actions", [])],
    }
    raw = json.dumps(key_data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def _on_session(parsed_state, raw_session=None):
    global _last_state_hash, _last_action_key, _last_rec_time, _final_summary_shown

    # ── State dedup ──
    new_hash = _state_hash(parsed_state)
    if new_hash == _last_state_hash:
        return
    _last_state_hash = new_hash

    # ── Data source status card (once per champ select entry) ──
    _show_status_once()

    # ── Update global state ──
    champ_select_state.update(parsed_state)

    my_bans = parsed_state.get("my_team_bans", [])
    enemy_bans = parsed_state.get("enemy_bans", [])
    my_picks = parsed_state.get("my_team_picks", [])
    enemy_picks = parsed_state.get("enemy_picks", [])
    my_prepicks = parsed_state.get("my_prepicks", [])
    enemy_prepicks = parsed_state.get("enemy_prepicks", [])
    my_position = parsed_state.get("my_position", "")
    next_action = parsed_state.get("next_action")
    phase = parsed_state.get("phase", "BAN_PICK")

    used = set(my_bans + enemy_bans + [p["champion_id"] for p in my_picks + enemy_picks])
    my_pick_ids = [p["champion_id"] for p in my_picks]
    enemy_pick_ids = [p["champion_id"] for p in enemy_picks]
    ban_only = set(my_bans + enemy_bans)

    all_picks_done = len(my_picks) >= 5 and len(enemy_picks) >= 5

    # After final summary, don't print anything until next champ select
    if all_picks_done and _final_summary_shown:
        return

    # ── Action-based throttle (same action: wait, new action: show immediately) ──
    if not all_picks_done or _final_summary_shown:
        cur_action_key = _action_key(parsed_state)
        if cur_action_key == _last_action_key:
            # Same action — apply time throttle
            now = time.time()
            if now - _last_rec_time < MIN_REC_INTERVAL:
                return
        else:
            # Action changed (e.g., self-pick → enemy-pick, or teammate-ban → self-ban)
            # Always show immediately
            pass
        _last_action_key = cur_action_key
        _last_rec_time = time.time()

    # ── Header ──
    next_actions = parsed_state.get("next_actions", [])
    action_desc_parts = []
    for na_item in next_actions:
        na_type = "Ban" if na_item["type"] == "ban" else "Pick"
        na_side = "我方" if na_item["is_mine"] else "敌方"
        na_pos = f"({na_item.get('position', '')})" if na_item.get("position") else ""
        na_self = "←你" if na_item["is_self"] else ""
        action_desc_parts.append(f"{na_side}{na_type}{na_pos}{na_self}")
    action_desc = " + ".join(action_desc_parts) if action_desc_parts else ""

    # Build rank/mode line (from lcu_connection, refreshed by poll_lcu)
    rank_info = ""
    ranks = lcu_connection.get("ranks", {})
    if ranks:
        rank_parts = []
        for key, label in [("solo_duo", "单双"), ("flex", "灵活")]:
            if key in ranks:
                rank_parts.append(f"{label}:{ranks[key]['display']}")
        if rank_parts:
            rank_info = f"  段位: {'  '.join(rank_parts)}"

    # Queue name: prefer lcu_connection (from lobby/gameflow), fallback to parsed session
    queue_name = lcu_connection.get("queue_name", "") or parsed_state.get("queue_name", "")
    if queue_name and "未知" not in queue_name:
        sep = "  |  " if rank_info else "  "
        rank_info += f"{sep}模式: {queue_name}"

    print(f"\n{'='*55}")
    if rank_info:
        print(f"{rank_info}")
    elif queue_name and "未知" not in queue_name:
        # 即使没有段位，也要显示模式
        print(f"  模式: {queue_name}")
    print(f"  Bans  我方: {_names(my_bans):<30s} 敌方: {_names(enemy_bans)}")
    print(f"  Picks 我方: {_pick_names(my_picks):<30s} 敌方: {_pick_names(enemy_picks)}")
    print(f"  阶段: {phase}  |  你的位置: {my_position or '未分配'}  |  {action_desc}")
    print(f"{'='*55}")

    # ── Determine what kind of recommendation to show ──
    # Get rank tier for recommendation adjustments
    rank_tier = ""
    queue_key = lcu_connection.get("queue_key", "") or parsed_state.get("queue_key", "")
    ranks = lcu_connection.get("ranks", {})
    if queue_key in ("solo_duo", "flex"):
        rank_info_r = ranks.get(queue_key, ranks.get("solo_duo", {}))
        rank_tier = rank_info_r.get("tier", "")

    teammate_pool = {}
    if lcu_connection.get("active") and raw_session:
        teammate_pool = fetch_teammate_mastery(
            lcu_connection["headers"], lcu_connection["base_url"], raw_session
        )

    # Reset final summary flag when not all picks done
    if not all_picks_done:
        _final_summary_shown = False

    if all_picks_done:
        # ── Full team: show final summary once ──
        if not _final_summary_shown:
            _final_summary_shown = True
            _show_final_summary(my_picks, enemy_picks, teammate_pool)
        return  # Don't show any pick/ban recommendations after all picks done

    # Determine action type from first item; handle duo picks
    our_actions = [a for a in next_actions if a.get("is_mine")]
    enemy_actions = [a for a in next_actions if not a.get("is_mine")]
    self_actions = [a for a in next_actions if a.get("is_self")]
    our_ban_actions = [a for a in our_actions if a["type"] == "ban"]
    our_pick_actions = [a for a in our_actions if a["type"] == "pick"]
    enemy_ban_actions = [a for a in enemy_actions if a["type"] == "ban"]
    enemy_pick_actions = [a for a in enemy_actions if a["type"] == "pick"]

    if our_ban_actions:
        # ── Our team is banning, show per-role recommendations ──
        ban_positions = [a.get("position", "") for a in our_ban_actions]
        ban_pos_str = "+".join(ban_positions) if ban_positions else ""
        recs_by_role = build_ban_recommendations(
            used, my_prepicks, enemy_prepicks, my_position,
            teammate_pool=teammate_pool, per_role=5
        )
        print(f"  >>> 我方 Ban 推荐 ({ban_pos_str}) (预选: {_names(my_prepicks)})")
        role_labels = {"top": "上路", "jungle": "打野", "mid": "中路", "bot": "ADC", "support": "辅助"}
        for role in ["top", "jungle", "mid", "bot", "support"]:
            recs = recs_by_role.get(role, [])
            if not recs:
                continue
            print(f"  ── {role_labels.get(role, role)} ──")
            for i, r in enumerate(recs):
                reasons = " · ".join(r.get("reasons", [])[:2])
                print(f"  #{i+1}  {r['name']:10s} {r['tier']} WR {r['winrate']:.1f}%  +{r['score']:.0f}  {reasons}")

    elif self_actions:
        # ── You are picking (possibly alongside a teammate in duo pick) ──
        # Show your recommendation first, then teammate's if applicable
        self_action = self_actions[0]
        recs = recommend(my_position, enemy_pick_ids, list(ban_only), my_pick_ids,
                         rank_tier=rank_tier)
        print(f"  >>> 你的 Pick 推荐 ({my_position})")
        for i, r in enumerate(recs[:8]):
            pos_tag = "✓对位" if r.get("position_match") else ""
            reasons = " · ".join(r.get("reasons", [])[:3])
            print(f"  #{i+1:<2} {r['name']:10s} {r['tier']} WR {r['winrate']:.1f}%  +{r['score']:.0f}  {pos_tag}  {reasons}")

        # Also show for co-picking teammate
        teammate_actions = [a for a in our_pick_actions if not a.get("is_self")]
        for ta in teammate_actions:
            tpos = ta.get("position", "")
            trecs = recommend(tpos, enemy_pick_ids, list(ban_only), my_pick_ids,
                              rank_tier=rank_tier)
            print(f"\n  >>> 同时推荐 — 队友 ({tpos})")
            for i, r in enumerate(trecs[:5]):
                reasons = " · ".join(r.get("reasons", [])[:3])
                print(f"  #{i+1}  {r['name']:10s} {r['tier']} WR {r['winrate']:.1f}%  +{r['score']:.0f}  {reasons}")

    elif our_pick_actions:
        # ── Teammate(s) picking, not you ──
        for ta in our_pick_actions:
            tpos = ta.get("position", "")
            trecs = recommend(tpos, enemy_pick_ids, list(ban_only), my_pick_ids,
                              rank_tier=rank_tier)
            print(f"  >>> 队友 Pick 推荐 ({tpos})")
            for i, r in enumerate(trecs[:5]):
                reasons = " · ".join(r.get("reasons", [])[:3])
                print(f"  #{i+1}  {r['name']:10s} {r['tier']} WR {r['winrate']:.1f}%  +{r['score']:.0f}  {reasons}")
            if len(our_pick_actions) > 1:
                print()  # Separator between multiple teammate recs

    else:
        # ── Enemy action or unknown ──
        recs = recommend(my_position, enemy_pick_ids, list(ban_only), my_pick_ids,
                         rank_tier=rank_tier)
        print(f"  >>> 参考推荐 ({my_position or '全局'})")
        for i, r in enumerate(recs[:5]):
            reasons = " · ".join(r.get("reasons", [])[:3])
            print(f"  #{i+1}  {r['name']:10s} {r['tier']} WR {r['winrate']:.1f}%  +{r['score']:.0f}  {reasons}")

    # ── Composition preview (after 3+ picks on either team) ──
    if len(my_pick_ids) >= 3 or len(enemy_pick_ids) >= 3:
        if my_pick_ids:
            my_comp = analyze_composition(tuple(my_pick_ids))
            print(f"  我方阵容: {my_comp.get('icon','')} {my_comp.get('name','')}  ", end="")
        if enemy_pick_ids:
            enemy_comp = analyze_composition(tuple(enemy_pick_ids))
            print(f"敌方阵容: {enemy_comp.get('icon','')} {enemy_comp.get('name','')}", end="")
        print()

    print()


def _show_final_summary(my_picks, enemy_picks, teammate_pool):
    """Display runes, spells, matchups, and composition analysis when all picks done."""
    my_pick_ids = [p["champion_id"] for p in my_picks]
    enemy_pick_ids = [p["champion_id"] for p in enemy_picks]

    # Build lane assignments
    from lane_detector import predict_enemy_lanes

    my_lanes = {}
    for p in my_picks:
        pos = p.get("position", "unknown")
        if pos and pos != "unknown":
            my_lanes[pos] = p["champion_id"]

    enemy_lanes = predict_enemy_lanes(enemy_pick_ids)

    print(f"\n{'='*55}")
    print(f"  🎯 阵容完成 — 符文 & 召唤师技能推荐")
    print(f"{'='*55}")

    # Runes & Spells for our team
    if my_lanes:
        runes_data = recommend_runes_spells(my_lanes, enemy_lanes)
        for side_key, data in runes_data.items():
            if side_key.startswith("我方"):
                lane = data.get("lane", "?")
                runes = data.get("runes", [])
                spells = data.get("spells", [])
                r_str = _format_rune(runes[0]) if runes else "默认"
                s_str = _format_spells(spells[0]) if spells else "Flash+TP"
                print(f"  {data['champion_name']:8s} ({lane:7s})  "
                      f"符文: {r_str:<20s}  技能: {s_str}")

    print(f"\n{'='*55}")
    print(f"  ⚔️ 对线胜率预测 (四路)")
    print(f"{'='*55}")

    # Matchup predictions — 4 lanes (bottom = bot+support)
    matchups = predict_matchups(my_lanes, enemy_lanes)
    lane_labels = {"top": "上路", "jungle": "野区", "mid": "中路", "bottom": "下路"}
    lane_wr = matchups.get("lane_winrate", {})
    for lane in ["top", "jungle", "mid", "bottom"]:
        m = lane_wr.get("lanes", {}).get(lane, {})
        our_names = "/".join(m.get("our_heroes", []))
        enemy_names = "/".join(m.get("enemy_heroes", []))
        label = lane_labels.get(lane, lane)
        if our_names and enemy_names:
            bar = _winrate_bar(m["our_wr"])
            print(f"  {label:5s}  {our_names:14s} vs {enemy_names:14s}  "
                  f"{bar} {m['our_wr']:.1f}%  {m['verdict']}")
        else:
            # Show lane even when data is incomplete
            our_display = our_names or "?"
            enemy_display = enemy_names or "?"
            print(f"  {label:5s}  {our_display:14s} vs {enemy_display:14s}  {'─':>10} 数据不足")
    print(f"  {'─'*45}")
    bar = _winrate_bar(lane_wr.get("our_wr", 50))
    print(f"  对线综合:  {bar} {lane_wr.get('our_wr', 50):.1f}%  {lane_wr.get('verdict', '?')}")

    # Game win rate
    game_wr = matchups.get("game_winrate", {})
    print(f"\n{'='*55}")
    print(f"  📊 对局胜率预测")
    print(f"{'='*55}")
    bar = _winrate_bar(game_wr.get("our_wr", 50))
    print(f"  我方阵容: {game_wr.get('our_comp', '?')}  vs  敌方阵容: {game_wr.get('enemy_comp', '?')}")
    print(f"  对局胜率:  {bar} {game_wr.get('our_wr', 50):.1f}%  {game_wr.get('verdict', '?')}")


def _names(ids):
    return ", ".join(cd.get_name(c) for c in ids) if ids else "-"


def _pick_names(picks):
    return ", ".join(cd.get_name(p["champion_id"]) for p in picks) if picks else "-"


def _format_rune(rune_page):
    if not rune_page:
        return "默认"
    keystone = rune_page.get("keystone", "")
    primary = rune_page.get("primary", "")
    secondary = rune_page.get("secondary", "")
    if secondary:
        return f"{keystone} {primary}/{secondary}"
    return f"{keystone}({primary})"


def _format_spells(spell_page):
    if not spell_page:
        return "闪现+传送"
    spells = spell_page.get("spells", [])
    return "+".join(spells) if spells else "闪现+传送"


def _winrate_bar(wr, width=10):
    """Draw a simple text winrate bar."""
    filled = round((wr - 30) / 40 * width)
    filled = max(0, min(width, filled))
    bar_filled = "█" * filled
    bar_empty = "░" * (width - filled)
    return f"[{bar_filled}{bar_empty}]"


if __name__ == "__main__":
    print("LoL BP Assistant — LCU Auto Mode v2.0")
    print("等待进入英雄选择...")
    import threading
    t = threading.Thread(
        target=poll_lcu,
        args=(champ_select_state, lcu_connection, _manual_ref, _on_session),
        daemon=True,
    )
    t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting...")
