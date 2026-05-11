"""
Tencent 101.qq.com data fetcher — runes, summoner spells, item builds.
Data sourced from game.gtimg.cn CDN and lol.qq.com guide APIs.
"""
import json
import os
import sys
import time
import logging

import requests

logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(sys._MEIPASS, "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# CDN endpoints
RUNE_LIST_URL = "https://game.gtimg.cn/images/lol/act/img/js/runeList/rune_list.js"
SPELL_LIST_URL = "https://game.gtimg.cn/images/lol/act/img/js/summonerskillList/summonerskill_list.js"
HERO_LIST_URL = "https://game.gtimg.cn/images/lol/act/img/js/heroList/hero_list.js"
CHAMP_DETAIL_URL = "https://lol.qq.com/act/lbp/common/guides/champDetail/champDetail_{}.js"

# Local cache files
RUNE_CACHE = os.path.join(DATA_DIR, "tencent_runes.json")
SPELL_CACHE = os.path.join(DATA_DIR, "tencent_spells.json")
CHAMP_DETAIL_DIR = os.path.join(DATA_DIR, "champ_detail")

# Rune tree IDs → names
TREE_NAMES = {
    "8000": "精密", "8100": "主宰", "8200": "巫术",
    "8300": "启迪", "8400": "坚决",
}

# Rune slot labels
SLOT_LABELS = {
    "Slot1": "基石", "Slot2": "第一行", "Slot3": "第二行", "Slot4": "第三行",
}


def _get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://101.qq.com/",
    }


def _fetch_json(url, timeout=15):
    """Fetch a JSON/JS endpoint, handling var assignment wrappers."""
    r = requests.get(url, headers=_get_headers(), timeout=timeout)
    if r.status_code != 200:
        return None
    text = r.text
    # Some endpoints wrap JSON in var XXX = {...};
    if text.startswith("var "):
        import re
        m = re.match(r'var\s+\w+\s*=\s*', text)
        if m:
            text = text[m.end():].rstrip(";").strip()
    # Some have extra data after the JSON
    depth = 0
    start = -1
    for i, c in enumerate(text):
        if c == '{':
            if depth == 0:
                start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    return json.loads(text)


def fetch_rune_dict(force=False):
    """Fetch complete rune dictionary. Returns {rune_id: {name, icon, style_name, slot}}."""
    if not force and os.path.exists(RUNE_CACHE):
        cache_age = time.time() - os.path.getmtime(RUNE_CACHE)
        if cache_age < 86400 * 7:  # 7-day cache
            with open(RUNE_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)

    try:
        data = _fetch_json(RUNE_LIST_URL)
        if data and "rune" in data:
            runes = data["rune"]
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(RUNE_CACHE, "w", encoding="utf-8") as f:
                json.dump(runes, f, ensure_ascii=False)
            logger.info("Fetched %d runes from CDN", len(runes))
            return runes
    except Exception as e:
        logger.warning("Rune fetch failed: %s", e)
        if os.path.exists(RUNE_CACHE):
            with open(RUNE_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
    return {}


def fetch_spell_dict(force=False):
    """Fetch summoner spell dictionary. Returns {spell_id: {name, icon, ...}}."""
    if not force and os.path.exists(SPELL_CACHE):
        cache_age = time.time() - os.path.getmtime(SPELL_CACHE)
        if cache_age < 86400 * 7:
            with open(SPELL_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)

    try:
        data = _fetch_json(SPELL_LIST_URL)
        if data and "summonerskill" in data:
            spells = data["summonerskill"]
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(SPELL_CACHE, "w", encoding="utf-8") as f:
                json.dump(spells, f, ensure_ascii=False)
            logger.info("Fetched %d summoner spells from CDN", len(spells))
            return spells
    except Exception as e:
        logger.warning("Spell fetch failed: %s", e)
        if os.path.exists(SPELL_CACHE):
            with open(SPELL_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
    return {}


def fetch_champion_detail(hero_id, force=False):
    """Fetch champion detail data including rune/spell/build recommendations."""
    cache_file = os.path.join(CHAMP_DETAIL_DIR, f"{hero_id}.json")
    cache_age = 0
    if not force and os.path.exists(cache_file):
        cache_age = time.time() - os.path.getmtime(cache_file)

    if not force and cache_age < 86400:  # 24-hour cache
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    url = CHAMP_DETAIL_URL.format(hero_id)
    try:
        data = _fetch_json(url)
        if data and "list" in data:
            detail = data["list"]
            os.makedirs(CHAMP_DETAIL_DIR, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(detail, f, ensure_ascii=False)
            logger.debug("Fetched champion detail for hero %s", hero_id)
            return detail
    except Exception as e:
        logger.warning("Champion detail fetch for %s failed: %s", hero_id, e)
        if os.path.exists(cache_file):
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
    return {}


def parse_perk_detail(perk_json_str, rune_dict=None):
    """Parse perkdetail field into rune pages with actual rune names.
    Returns list of {keystone, primary_tree, secondary_tree, runes, winrate, pickrate}.
    """
    if not perk_json_str:
        return []
    try:
        perk_data = json.loads(perk_json_str)
    except (json.JSONDecodeError, TypeError):
        return []

    if rune_dict is None:
        rune_dict = {}

    pages = []
    for key, entry in perk_data.items():
        perk_str = entry.get("perk", "")
        if not perk_str:
            continue
        # Format: "keystone&primary1&primary2&primary3&secondary1&secondary2&shard1&shard2&shard3"
        ids = perk_str.split("&")
        if len(ids) < 9:
            continue

        keystone_id = ids[0]
        primary_runes = ids[1:4]
        secondary_runes = ids[4:6]
        shard_runes = ids[6:9]

        primary_tree = ""
        if keystone_id in rune_dict:
            primary_tree = rune_dict[keystone_id].get("style_name", "")
        elif keystone_id in PRIMARY_TREE_LOOKUP:
            primary_tree = PRIMARY_TREE_LOOKUP[keystone_id]

        secondary_entry = ""
        if secondary_runes and secondary_runes[0] in rune_dict:
            secondary_entry = rune_dict[secondary_runes[0]].get("style_name", "")
        elif secondary_runes and secondary_runes[0] in PRIMARY_TREE_LOOKUP:
            secondary_entry = PRIMARY_TREE_LOOKUP[secondary_runes[0]]

        keystone_name = rune_dict.get(keystone_id, {}).get("name", keystone_id)
        if isinstance(keystone_name, str) and len(keystone_name) > 20:
            keystone_name = keystone_id

        pages.append({
            "keystone": keystone_name,
            "keystone_id": keystone_id,
            "primary": primary_tree,
            "secondary": secondary_entry,
            "runes": ids,
            "winrate": round(entry.get("winrate", 5000) / 100, 1),
            "pickrate": round(entry.get("showrate", 0) / 100, 1),
            "games": entry.get("igamecnt", 0),
        })

    pages.sort(key=lambda x: -x["games"])
    return pages


def parse_spells(spell_json_str, spell_dict=None):
    """Parse spellidjson field into spell combos.
    Returns list of {spells: [name, name], winrate, pickrate}.
    """
    if not spell_json_str:
        return []
    try:
        spell_data = json.loads(spell_json_str)
    except (json.JSONDecodeError, TypeError):
        return []

    if spell_dict is None:
        spell_dict = {}

    combos = []
    for key, entry in spell_data.items():
        spell_ids = entry.get("spellid", "").split("&")
        names = []
        for sid in spell_ids:
            s_info = spell_dict.get(sid, {})
            name = s_info.get("name", sid)
            if isinstance(name, str) and len(name) > 10:
                name = sid
            names.append(str(name))

        combos.append({
            "spells": names,
            "spell_ids": spell_ids,
            "winrate": round(entry.get("winrate", 5000) / 100, 1),
            "pickrate": round(entry.get("showrate", 0) / 100, 1),
            "games": entry.get("igamecnt", 0),
        })

    combos.sort(key=lambda x: -x["games"])
    return combos


# Fallback: map rune tree ID + keystone → primary tree name
PRIMARY_TREE_LOOKUP = {
    "8005": "精密", "8008": "精密", "8021": "精密", "8010": "精密",
    "8112": "主宰", "8124": "主宰", "8128": "主宰", "9923": "主宰",
    "8214": "巫术", "8229": "巫术", "8230": "巫术",
    "8351": "启迪", "8360": "启迪", "8369": "启迪",
    "8437": "坚决", "8439": "坚决", "8465": "坚决",
}


def get_champion_runes(hero_id, lane="", champion_name=""):
    """Get recommended rune pages for a champion in a specific lane.
    Returns list of {keystone, primary, secondary, winrate, pickrate, games}.
    """
    detail = fetch_champion_detail(hero_id)
    lane_data = detail.get("championLane", {}).get(lane, {})
    if not lane_data:
        return []

    rune_dict = fetch_rune_dict()
    pages = parse_perk_detail(lane_data.get("perkdetail", ""), rune_dict)

    # If no perkdetail, fall back to mainviceperk summary
    if not pages:
        mvp = lane_data.get("mainviceperk", "")
        if mvp:
            try:
                mvp_data = json.loads(mvp)
            except (json.JSONDecodeError, TypeError):
                return []
            for key, entry in mvp_data.items():
                main_name = entry.get("mainname", "")
                main_perk = entry.get("mainperk", "")
                vice_name = entry.get("viceperk", "")
                keystone = rune_dict.get(main_perk, {}).get("name", main_name)
                if isinstance(keystone, str) and len(keystone) > 20:
                    keystone = main_name
                pages.append({
                    "keystone": keystone,
                    "keystone_id": main_perk,
                    "primary": main_name,
                    "secondary": vice_name,
                    "runes": [],
                    "winrate": round(entry.get("winrate", 5000) / 100, 1),
                    "pickrate": round(entry.get("showrate", 0) / 100, 1),
                    "games": entry.get("igamecnt", 0),
                })
            pages.sort(key=lambda x: -x["games"])

    return pages[:3]


def get_champion_spells(hero_id, lane=""):
    """Get recommended summoner spells for a champion in a lane.
    Returns list of {spells: [name, name], winrate, pickrate, games}.
    """
    detail = fetch_champion_detail(hero_id)
    lane_data = detail.get("championLane", {}).get(lane, {})
    if not lane_data:
        return []

    spell_dict = fetch_spell_dict()
    return parse_spells(lane_data.get("spellidjson", ""), spell_dict)


# ── Cached wrappers (used by engine.py) ──

def get_runes(champion_key: int, role: str = "") -> list[dict]:
    """Get rune pages for a champion in a specific role (cached)."""
    import json
    from champion_data import get_champion_data
    cd = get_champion_data()
    role = role or cd.get_role(champion_key)

    runes_cache = os.path.join(DATA_DIR, "runes.json")

    # 1. Try Tencent 101 data
    tc_runes = get_champion_runes(champion_key, role)
    if tc_runes:
        result = []
        for r in tc_runes:
            primary_tree = r.get("primary", "")
            secondary_tree = r.get("secondary", "")
            display = f"{r['keystone']} {primary_tree}"
            if secondary_tree:
                display += f"/{secondary_tree}"
            result.append({
                "keystone": r["keystone"],
                "primary": primary_tree,
                "secondary": secondary_tree,
                "pick_rate": r.get("pickrate", 0),
                "win_rate": r.get("winrate", 50.0),
                "display": display,
            })
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            cache = {}
            if os.path.exists(runes_cache):
                with open(runes_cache, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            cache[f"{champion_key}_{role}"] = result
            with open(runes_cache, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass
        return result

    # 2. Try local file cache
    if os.path.exists(runes_cache):
        try:
            with open(runes_cache, "r", encoding="utf-8") as f:
                cached = json.load(f)
            key = f"{champion_key}_{role}"
            if key in cached:
                return cached[key]
        except Exception:
            pass

    return []


def get_spells(champion_key: int, role: str = "") -> list[dict]:
    """Get summoner spells for a champion in a specific role (cached)."""
    import json
    from champion_data import get_champion_data
    cd = get_champion_data()
    role = role or cd.get_role(champion_key)

    spells_cache = os.path.join(DATA_DIR, "summoner_spells.json")

    # 1. Try Tencent 101 data
    tc_spells = get_champion_spells(champion_key, role)
    if tc_spells:
        result = []
        for s in tc_spells:
            result.append({
                "spells": s["spells"],
                "pick_rate": s.get("pickrate", 0),
                "win_rate": s.get("winrate", 50.0),
            })
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            cache = {}
            if os.path.exists(spells_cache):
                with open(spells_cache, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            cache[f"{champion_key}_{role}"] = result
            with open(spells_cache, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass
        return result

    # 2. Try local file cache
    if os.path.exists(spells_cache):
        try:
            with open(spells_cache, "r", encoding="utf-8") as f:
                cached = json.load(f)
            key = f"{champion_key}_{role}"
            if key in cached:
                return cached[key]
        except Exception:
            pass

    return []
