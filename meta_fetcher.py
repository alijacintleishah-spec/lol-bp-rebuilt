"""
OP.GG MCP API meta data fetcher. Caches live tier/winrate data.
"""

import json
import os
import re
import sys
import time
import logging

import requests

logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(sys._MEIPASS, "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

META_LIVE_CACHE = os.path.join(DATA_DIR, "champion_meta_live.json")
DD_VERSION_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
OPGG_MCP_URL = "https://mcp-api.op.gg/mcp"

POSITION_MAP = {"top": "top", "mid": "mid", "jungle": "jungle", "adc": "bot", "support": "support"}
TIER_MAP = {1: "S", 2: "A", 3: "B", 4: "C", 5: "C"}
META_CACHE_HOURS = 24


def get_latest_dd_version():
    try:
        r = requests.get(DD_VERSION_URL, timeout=10)
        return r.json()[0]
    except Exception:
        return None


def fetch_opgg_meta():
    try:
        init = {"jsonrpc":"2.0","id":0,"method":"initialize",
                "params":{"protocolVersion":"2024-11-05","capabilities":{},
                          "clientInfo":{"name":"lol-bp","version":"2.0"}}}
        r = requests.post(OPGG_MCP_URL, json=init,
                         headers={"Content-Type":"application/json"}, timeout=10)
        if r.status_code != 200: return None

        call = {"jsonrpc":"2.0","id":2,"method":"tools/call",
                "params":{"name":"lol_list_lane_meta_champions","arguments":{}}}
        r2 = requests.post(OPGG_MCP_URL, json=call,
                          headers={"Content-Type":"application/json"}, timeout=20)
        if r2.status_code != 200: return None

        data = r2.json()
        content = data.get("result",{}).get("content",[])
        if not content: return None
        text = "".join([c["text"] for c in content if c["type"]=="text"])
        return parse_opgg(text)
    except Exception as e:
        logger.error("OP.GG fetch failed: %s", e)
        return None


def parse_opgg(text):
    result = {}
    for pos_key in ["Top","Mid","Jungle","Adc","Support"]:
        pattern = rf'{pos_key}\("([^"]+)",(true|false),(\d+),(\d+),(\d+),([\d.]+),([\d.]+),([\d.]+),([\d.]+),([\d.]+),(\d+),(\d+),(\d+),(\d+)\)'
        for m in re.findall(pattern, text):
            name = m[0]
            result[name] = {
                "role": POSITION_MAP.get(pos_key.lower(),"unknown"),
                "tier": TIER_MAP.get(int(m[10]),"B"),
                "winrate": round(float(m[5])*100,1),
                "pickrate": round(float(m[6])*100,1),
                "banrate": round(float(m[8])*100,1),
                "rank": int(m[11]),
            }
    return result if result else None


def merge_meta(champion_data, opgg_meta):
    merged = {}
    name_to_keys = {}
    for key, info in champion_data.champions.items():
        nl = info["name"].lower().strip()
        name_to_keys.setdefault(nl, []).append(key)

    opgg_to_key = {}
    for opgg_name, meta in opgg_meta.items():
        nl = opgg_name.lower().strip()
        if nl in name_to_keys:
            for key in name_to_keys[nl]:
                if champion_data.get_role(key) == meta["role"]:
                    opgg_to_key[key] = meta; break
            else:
                opgg_to_key[name_to_keys[nl][0]] = meta

    for key in champion_data.all_champions():
        if key in opgg_to_key:
            m = opgg_to_key[key]
            merged[key] = {"tier":m["tier"],"wr":m["winrate"],"pr":m["pickrate"],"br":m["banrate"]}
        else:
            from champion_data import META_DATA
            b = META_DATA.get(key,{"tier":"B","wr":50.0,"pr":3.0,"br":2.0})
            merged[key] = {"tier":b.get("tier","B"),"wr":b.get("wr",50.0),"pr":b.get("pr",3.0),"br":b.get("br",2.0)}
    return merged


def update_meta_if_needed(champion_data, force=False):
    os.makedirs(DATA_DIR, exist_ok=True)
    latest = get_latest_dd_version()
    if not latest:
        return None, "cannot get version"

    cached_meta = None
    if os.path.exists(META_LIVE_CACHE):
        try:
            with open(META_LIVE_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            cached_meta = cached.get("meta",{})
        except Exception:
            pass

    needs = force
    if not needs:
        if not cached:
            needs = True
        elif cached.get("version","") != latest:
            needs = True
        elif time.time() - cached.get("cached_at",0) > META_CACHE_HOURS * 3600:
            needs = True
        elif not cached_meta:
            needs = True

    if not needs:
        return cached_meta, f"up to date ({latest})"

    opgg = fetch_opgg_meta()
    if not opgg:
        if cached_meta: return cached_meta, "OP.GG failed, using cache"
        return None, "OP.GG failed, no cache"

    merged = merge_meta(champion_data, opgg)
    cache_data = {"version":latest,"cached_at":time.time(),"meta":merged}
    with open(META_LIVE_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False)
    return merged, f"updated to {latest}"


def get_live_meta(champion_key):
    if os.path.exists(META_LIVE_CACHE):
        try:
            with open(META_LIVE_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            meta = cached.get("meta",{})
            if str(champion_key) in meta:
                return meta[str(champion_key)]
        except Exception:
            pass
    return None


# ── OP.GG Counter/Matchup Data ──

COUNTERS_DIR = os.path.join(DATA_DIR, "opgg_counters")
COUNTER_CACHE_HOURS = 48


def _fetch_opgg_champion_analysis(champion_name: str, position: str):
    """Fetch champion analysis from OP.GG MCP API. Returns parsed dict or None."""
    try:
        init = {"jsonrpc":"2.0","id":0,"method":"initialize",
                "params":{"protocolVersion":"2024-11-05","capabilities":{},
                          "clientInfo":{"name":"lol-bp","version":"2.0"}}}
        r = requests.post(OPGG_MCP_URL, json=init,
                         headers={"Content-Type":"application/json"}, timeout=10)
        if r.status_code != 200:
            return None

        pos_map = {"top":"top","jungle":"jungle","mid":"mid","bot":"adc","support":"support"}
        opgg_pos = pos_map.get(position, position)

        call = {"jsonrpc":"2.0","id":2,"method":"tools/call",
                "params":{"name":"lol_get_champion_analysis",
                          "arguments":{
                              "champion": champion_name.upper(),
                              "position": opgg_pos,
                              "game_mode":"ranked",
                              "lang":"en_US",
                              "desired_output_fields": [
                                  "champion","position",
                                  "data.strong_counters",
                                  "data.weak_counters",
                                  "data.summary.positions",
                              ]
                          }}}
        r2 = requests.post(OPGG_MCP_URL, json=call,
                          headers={"Content-Type":"application/json"}, timeout=20)
        if r2.status_code != 200:
            return None

        data = r2.json()
        content = data.get("result",{}).get("content",[])
        if not content:
            return None
        text = "".join([c["text"] for c in content if c["type"]=="text"])
        return _parse_counter_response(text, position)
    except Exception as e:
        logger.error("OP.GG counter fetch failed for %s %s: %s", champion_name, position, e)
        return None


def _parse_counter_response(text: str, position: str) -> dict | None:
    """Parse the class-instantiation text format into structured counter data."""
    # Extract Data(strong_list, weak_list)
    # Format: Data([StrongCounter(id,"name",play,win,wr),...],[WeakCounter(...),...])
    data_match = re.search(r'Data\((\[.*?\]),\s*(\[.*?\])\)', text)
    if not data_match:
        return None

    strong_str = data_match.group(1)
    weak_str = data_match.group(2)

    def _parse_counter_list(s):
        result = []
        # Counter(id,"name",play,win) or Counter(id,"name",play,win,win_rate)
        # win_rate from API is a ratio (0.55), convert to percentage (55.0)
        for m in re.finditer(r'(\w+)\((\d+),\s*"([^"]*)",\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)', s):
            cid = int(m.group(2))
            cname = m.group(3)
            play = int(m.group(4))
            win = int(m.group(5))
            wr = float(m.group(6)) * 100 if m.group(6) else (round(win/play*100,1) if play > 0 else 50.0)
            result.append({
                "champion_id": cid,
                "champion_name": cname,
                "play": play,
                "win": win,
                "win_rate": wr,
            })
        return result

    strong_counters = _parse_counter_list(strong_str)
    weak_counters = _parse_counter_list(weak_str)

    # Extract per-position counters
    pos_counters = []
    pos_pattern = r'Position\("([^"]+)",.*?\[(Counter\(.*?\)(?:\s*,\s*Counter\(.*?\))*)?\]'
    for m in re.finditer(pos_pattern, text):
        pname = m.group(1).lower()
        clist = m.group(2) if m.group(2) else ""
        pos_counters.append({
            "position": pname,
            "counters": _parse_counter_list(clist),
        })

    return {
        "strong_counters": strong_counters,
        "weak_counters": weak_counters,
        "position_counters": pos_counters,
    }


def _counters_cache_path(champion_key: int) -> str:
    return os.path.join(COUNTERS_DIR, f"{champion_key}.json")


def _load_counters_cache(champion_key: int) -> dict | None:
    path = _counters_cache_path(champion_key)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _save_counters_cache(champion_key: int, data: dict, champion_name: str, position: str):
    os.makedirs(COUNTERS_DIR, exist_ok=True)
    cache = {
        "champion_id": champion_key,
        "champion_name": champion_name,
        "position": position,
        "fetched_at": time.time(),
        **data,
    }
    with open(_counters_cache_path(champion_key), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def _classify_counter_entry(entry: dict, my_champion_id: int, enemy_id: int) -> dict | None:
    """Determine matchup from counter entry, robust to locale-dependent list order.

    OP.GG API inconsistency: the "strong_counters" and "weak_counters" lists swap order
    across locales, and the class names vary. This function uses the independent win/play
    ratio to determine whether the entry represents:
    - strong counter: enemy beats us (wr = counter's win rate ≈ win/play)
    - weak counter: we beat enemy (wr = our win rate ≈ 1 - win/play)

    Returns {win_rate, games, advantage} from our champion's perspective, or None.
    """
    play = entry.get("play", 0)
    win = entry.get("win", 0)
    api_wr = entry.get("win_rate", 50)

    if play < 50:
        return None

    counter_wr_from_ratio = win / play * 100
    loaded_wr_from_ratio = (play - win) / play * 100

    # Determine if api_wr represents counter's WR or loaded champion's WR
    api_wr_pct = api_wr  # Already in percentage (0-100)

    if abs(counter_wr_from_ratio - api_wr_pct) <= abs(loaded_wr_from_ratio - api_wr_pct):
        # api_wr ≈ win/play → counter's win rate → strong counter (enemy beats us)
        our_wr = loaded_wr_from_ratio
    else:
        # api_wr ≈ 1-win/play → loaded champion's win rate → weak counter (we beat enemy)
        our_wr = api_wr_pct

    return {
        "win_rate": round(our_wr, 1),
        "games": play,
        "advantage": round(our_wr - 50.0, 1),
    }


def _lookup_counter_data(champion_key: int, enemy_key: int,
                         direction: str = "forward") -> dict | None:
    """Look up enemy in champion's counter data (all lists combined).
    direction="forward": check strong+weak of champion_key for enemy_key.
    Returns {win_rate, games, advantage} or None.
    """
    cached = _load_counters_cache(champion_key)
    if not cached:
        return None

    for c in cached.get("strong_counters", []):
        if c["champion_id"] == enemy_key:
            return _classify_counter_entry(c, champion_key, enemy_key)

    for c in cached.get("weak_counters", []):
        if c["champion_id"] == enemy_key:
            return _classify_counter_entry(c, champion_key, enemy_key)

    return None


def _ensure_cache(champion_key: int, lane: str = "") -> dict | None:
    """Ensure OP.GG counter cache exists and is fresh for a champion."""
    cached = _load_counters_cache(champion_key)
    if cached is None:
        from champion_data import get_champion_data
        cd = get_champion_data()
        name = cd.champions.get(champion_key, {}).get("dd_id", "")
        role = cd.get_role(champion_key) or lane
        if not name:
            return None
        raw = _fetch_opgg_champion_analysis(name, role)
        if raw:
            _save_counters_cache(champion_key, raw, name, role)
            return _load_counters_cache(champion_key)
        return None

    age = time.time() - cached.get("fetched_at", 0)
    if age > COUNTER_CACHE_HOURS * 3600:
        from champion_data import get_champion_data
        cd = get_champion_data()
        name = cd.champions.get(champion_key, {}).get("dd_id", "")
        role = cd.get_role(champion_key) or lane
        if name:
            raw = _fetch_opgg_champion_analysis(name, role)
            if raw:
                _save_counters_cache(champion_key, raw, name, role)
                return _load_counters_cache(champion_key)

    return cached


# ── Cached lookup API ──

def get_opgg_matchup(my_champion_key: int, enemy_key: int, lane: str) -> dict | None:
    """Get OP.GG matchup data for my_champion vs enemy in lane.
    Returns {win_rate, games, advantage} or None if insufficient data.
    advantage > 0 means my champion is favored, < 0 means countered.
    """
    # 1. Forward lookup: check my champion's counter data
    _ensure_cache(my_champion_key, lane)
    result = _lookup_counter_data(my_champion_key, enemy_key)
    if result:
        return result

    # 2. Reverse lookup: check enemy champion's counter data for us
    _ensure_cache(enemy_key, lane)
    result = _lookup_counter_data(enemy_key, my_champion_key)
    if result:
        # Reverse the advantage: if enemy has advantage over us, we have negative advantage
        return {
            "win_rate": round(100.0 - result["win_rate"], 1),
            "games": result["games"],
            "advantage": round(-result["advantage"], 1),
        }

    return None
