"""
LoL BP Assistant — Iteration 9: lolalytics Data Scraper
Scrapes rune pages, summoner spells, and matchup data from lolalytics.com.
Uses mock data as fallback when scraping is unavailable.
"""

import json
import os
import re
import sys
import time
import logging

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # bs4 not installed, scraping disabled

logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(sys._MEIPASS, "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

RUNES_CACHE = os.path.join(DATA_DIR, "runes.json")
SPELLS_CACHE = os.path.join(DATA_DIR, "summoner_spells.json")
MATCHUPS_CACHE = os.path.join(DATA_DIR, "matchups.json")

BASE_URL = "https://lolalytics.com/lol"

# Rune ID → name mapping (Data Dragon perk IDs)
# Keystone IDs for reference
KEYSTONE_NAMES = {
    8005: "强攻", 8008: "致命节奏", 8021: "迅捷步法", 8010: "征服者",
    8112: "电刑", 8124: "掠食者", 8128: "黑暗收割", 9923: "丛刃",
    8214: "召唤艾黎", 8229: "奥术彗星", 8230: "相位猛冲",
    8351: "冰川增幅", 8360: "启封的秘籍",
    8437: "不灭之握", 8439: "余震", 8465: "守护者",
    8369: "先攻",
}

PRIMARY_TREES = {
    8000: "精密", 8100: "主宰", 8200: "巫术",
    8300: "启迪", 8400: "坚决",
}

SUMMONER_SPELL_NAMES = {
    1: "净化", 3: "虚弱", 4: "闪现", 6: "疾跑",
    7: "治疗", 11: "惩戒", 12: "传送", 13: "清晰术",
    14: "点燃", 21: "屏障",
}


def scrape_champion_page(champion_name: str, role: str = "") -> dict | None:
    """
    Scrape a lolalytics champion page for runes and summoner spells.
    URL: https://lolalytics.com/lol/{champion}/build/?lane={role}
    """
    if BeautifulSoup is None:
        return None

    # lolalytics uses URL-friendly names (lowercase, no spaces, no special chars)
    url_name = champion_name.lower().replace(" ", "").replace("'", "").replace(".", "")
    lane_param = role if role else "default"
    url = f"{BASE_URL}/{url_name}/build/?lane={lane_param}"

    try:
        headers = {"User-Agent": "LoLBP/2.0 (educational project)"}
        r = requests.get(url, headers=headers, timeout=15)

        if r.status_code != 200:
            logger.debug("HTTP %d for %s", r.status_code, url)
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # Try to find embedded JSON data in script tags
        result = {"champion": champion_name, "role": role}

        # Look for rune data in the page
        # LOLalytics embeds data in __NEXT_DATA__ or similar JSON blobs
        for script in soup.find_all("script"):
            text = script.string or ""
            if "runePages" in text or "perkPages" in text:
                try:
                    # Extract JSON-like data
                    pass  # Complex extraction, use fallback for now
                except Exception:
                    pass

        return result
    except Exception as e:
        logger.debug("Scrape error for %s: %s", champion_name, e)
        return None


def scrape_matchups(champion_name: str, role: str) -> dict[str, dict]:
    """
    Scrape lolalytics counters page for matchup data.
    URL: https://lolalytics.com/lol/{champion}/counters/?lane={role}
    """
    if BeautifulSoup is None:
        return {}
    url_name = champion_name.lower().replace(" ", "").replace("'", "").replace(".", "")
    url = f"{BASE_URL}/{url_name}/counters/?lane={role}"

    try:
        headers = {"User-Agent": "LoLBP/2.0 (educational project)"}
        r = requests.get(url, headers=headers, timeout=15)

        if r.status_code != 200:
            return {}

        soup = BeautifulSoup(r.text, "html.parser")
        matchups = {}

        # Parse counter table rows (lolalytics uses specific CSS classes)
        for row in soup.select("tr[class*='counter'], tr[class*='matchup']"):
            cells = row.find_all("td")
            if len(cells) >= 3:
                enemy_name = cells[0].get_text(strip=True)
                try:
                    wr_text = cells[1].get_text(strip=True).replace("%", "")
                    wr_delta = float(wr_text) - 50.0
                    games_text = cells[2].get_text(strip=True).replace(",", "")
                    games = int(games_text) if games_text.isdigit() else 0
                    if enemy_name:
                        matchups[enemy_name] = {"wr_delta": wr_delta, "games": games}
                except (ValueError, IndexError):
                    pass

        return matchups
    except Exception as e:
        logger.debug("Matchup scrape error for %s: %s", champion_name, e)
        return {}


def get_runes(champion_key: int, role: str = "") -> list[dict]:
    """Get rune pages for a champion in a specific role."""
    from champion_data import get_champion_data
    cd = get_champion_data()
    name = cd.get_name(champion_key)
    role = role or cd.get_role(champion_key)

    # 1. Try Tencent 101 data (champion-specific, per-lane)
    try:
        from tencent_fetcher import get_champion_runes
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
            # Cache the result
            os.makedirs(DATA_DIR, exist_ok=True)
            try:
                cache = {}
                if os.path.exists(RUNES_CACHE):
                    with open(RUNES_CACHE, "r", encoding="utf-8") as f:
                        cache = json.load(f)
                cache[f"{champion_key}_{role}"] = result
                with open(RUNES_CACHE, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False)
            except Exception:
                pass
            return result
    except ImportError:
        pass
    except Exception as e:
        logger.debug("Tencent rune fetch failed for %s %s: %s", champion_key, role, e)

    # 2. Try local file cache
    if os.path.exists(RUNES_CACHE):
        try:
            with open(RUNES_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            key = f"{champion_key}_{role}"
            if key in cached:
                return cached[key]
        except Exception:
            pass

    # 3. No data available — caller should handle empty result
    return []


def get_spells(champion_key: int, role: str = "") -> list[dict]:
    """Get summoner spells for a champion in a specific role."""
    from champion_data import get_champion_data
    cd = get_champion_data()
    name = cd.get_name(champion_key)
    role = role or cd.get_role(champion_key)

    # 1. Try Tencent 101 data (champion-specific, per-lane)
    try:
        from tencent_fetcher import get_champion_spells
        tc_spells = get_champion_spells(champion_key, role)
        if tc_spells:
            result = []
            for s in tc_spells:
                result.append({
                    "spells": s["spells"],
                    "pick_rate": s.get("pickrate", 0),
                    "win_rate": s.get("winrate", 50.0),
                })
            # Cache
            os.makedirs(DATA_DIR, exist_ok=True)
            try:
                cache = {}
                if os.path.exists(SPELLS_CACHE):
                    with open(SPELLS_CACHE, "r", encoding="utf-8") as f:
                        cache = json.load(f)
                cache[f"{champion_key}_{role}"] = result
                with open(SPELLS_CACHE, "w", encoding="utf-8") as f:
                    json.dump(cache, f, ensure_ascii=False)
            except Exception:
                pass
            return result
    except ImportError:
        pass
    except Exception as e:
        logger.debug("Tencent spell fetch failed for %s %s: %s", champion_key, role, e)

    # 2. Try local file cache
    if os.path.exists(SPELLS_CACHE):
        try:
            with open(SPELLS_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            key = f"{champion_key}_{role}"
            if key in cached:
                return cached[key]
        except Exception:
            pass

    # 3. No data available — caller should handle empty result
    return []


def get_matchup(champion_key: int, enemy_key: int, role: str = "") -> dict | None:
    """Get matchup data for champion vs enemy in a specific role."""
    from champion_data import get_champion_data
    cd = get_champion_data()
    name = cd.get_name(champion_key)
    enemy_name = cd.get_name(enemy_key)
    role = role or cd.get_role(champion_key)

    if os.path.exists(MATCHUPS_CACHE):
        try:
            with open(MATCHUPS_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            key = f"{champion_key}_{role}"
            if key in cached and enemy_name in cached[key]:
                return cached[key][enemy_name]
        except Exception:
            pass

    return None  # None = no data, use neutral prediction
