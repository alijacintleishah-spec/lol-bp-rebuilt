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
