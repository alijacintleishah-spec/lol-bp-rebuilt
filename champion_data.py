"""
Champion data from Data Dragon API + built-in meta + archetypes.
Replaces hardcoded CHAMPIONS dict in recommender.py.
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

CHAMPION_CACHE = os.path.join(DATA_DIR, "champion_data.json")
DD_VERSION_URL = "https://ddragon.leagueoflegends.com/api/versions.json"

# ── Built-in meta data (16.9 patch) ──────────────────────────────────────────
META_DATA = {
    266: {"tier":"B","wr":49.2,"pr":5.1,"br":3.2},
    103: {"tier":"A","wr":51.8,"pr":7.3,"br":4.1},
    84:  {"tier":"A","wr":50.9,"pr":8.5,"br":6.8},
    166: {"tier":"A","wr":51.2,"pr":4.8,"br":3.5},
    12:  {"tier":"B","wr":50.1,"pr":3.2,"br":1.5},
    32:  {"tier":"A","wr":52.0,"pr":4.5,"br":2.1},
    34:  {"tier":"A","wr":51.2,"pr":6.8,"br":3.2},
    1:   {"tier":"A","wr":51.5,"pr":5.2,"br":2.8},
    22:  {"tier":"A","wr":51.3,"pr":8.2,"br":2.5},
    268: {"tier":"B","wr":49.5,"pr":3.1,"br":1.8},
    432: {"tier":"A","wr":51.0,"pr":4.2,"br":2.2},
    53:  {"tier":"S","wr":52.1,"pr":9.5,"br":5.8},
    63:  {"tier":"A","wr":51.2,"pr":7.1,"br":4.5},
    201: {"tier":"B","wr":50.0,"pr":3.5,"br":2.1},
    51:  {"tier":"A","wr":51.4,"pr":9.1,"br":3.8},
    69:  {"tier":"A","wr":52.0,"pr":5.5,"br":3.1},
    31:  {"tier":"B","wr":49.8,"pr":3.2,"br":1.5},
    42:  {"tier":"B","wr":49.2,"pr":4.5,"br":1.8},
    122: {"tier":"S","wr":52.8,"pr":7.2,"br":6.5},
    131: {"tier":"A","wr":50.8,"pr":6.8,"br":4.2},
    119: {"tier":"A","wr":50.5,"pr":5.8,"br":3.5},
    36:  {"tier":"B","wr":50.2,"pr":3.8,"br":2.1},
    245: {"tier":"A","wr":51.2,"pr":5.5,"br":3.8},
    60:  {"tier":"B","wr":49.5,"pr":4.2,"br":2.5},
    81:  {"tier":"A","wr":51.0,"pr":9.2,"br":3.5},
    9:   {"tier":"B","wr":49.8,"pr":3.5,"br":2.8},
    114: {"tier":"A","wr":50.8,"pr":6.5,"br":4.5},
    105: {"tier":"A","wr":50.5,"pr":6.2,"br":4.8},
    3:   {"tier":"B","wr":49.5,"pr":3.2,"br":1.5},
    41:  {"tier":"S","wr":52.5,"pr":8.5,"br":5.5},
    86:  {"tier":"A","wr":51.8,"pr":7.8,"br":3.5},
    150: {"tier":"B","wr":49.0,"pr":4.5,"br":2.1},
    79:  {"tier":"B","wr":50.1,"pr":5.2,"br":3.1},
    104: {"tier":"A","wr":51.5,"pr":6.8,"br":5.2},
    120: {"tier":"S","wr":52.5,"pr":7.2,"br":6.1},
    420: {"tier":"B","wr":49.8,"pr":3.5,"br":2.2},
    39:  {"tier":"A","wr":51.0,"pr":5.5,"br":3.5},
    40:  {"tier":"A","wr":52.2,"pr":5.8,"br":2.5},
    59:  {"tier":"A","wr":51.5,"pr":7.5,"br":4.5},
    24:  {"tier":"S","wr":52.5,"pr":8.2,"br":6.8},
    126: {"tier":"A","wr":51.0,"pr":6.5,"br":3.8},
    202: {"tier":"A","wr":51.8,"pr":7.8,"br":4.2},
    115: {"tier":"S","wr":52.3,"pr":9.8,"br":5.5},
    222: {"tier":"S","wr":52.3,"pr":9.8,"br":5.5},
    10:  {"tier":"B","wr":50.2,"pr":4.2,"br":2.8},
    55:  {"tier":"B","wr":50.5,"pr":5.5,"br":4.2},
    89:  {"tier":"S","wr":52.0,"pr":8.5,"br":4.5},
    64:  {"tier":"A","wr":50.2,"pr":9.5,"br":7.2},
    127: {"tier":"B","wr":49.5,"pr":4.8,"br":3.5},
    99:  {"tier":"A","wr":51.2,"pr":8.5,"br":3.8},
    54:  {"tier":"A","wr":51.8,"pr":6.5,"br":3.2},
    90:  {"tier":"A","wr":52.0,"pr":5.8,"br":3.5},
    57:  {"tier":"B","wr":50.0,"pr":4.5,"br":2.5},
    11:  {"tier":"A","wr":50.5,"pr":6.8,"br":4.2},
    21:  {"tier":"B","wr":50.8,"pr":7.2,"br":3.5},
    82:  {"tier":"A","wr":51.5,"pr":7.8,"br":4.5},
    25:  {"tier":"A","wr":50.8,"pr":6.2,"br":5.2},
    267: {"tier":"B","wr":50.2,"pr":5.5,"br":3.1},
    75:  {"tier":"B","wr":49.8,"pr":4.2,"br":2.8},
    111: {"tier":"S","wr":51.8,"pr":8.2,"br":5.5},
    76:  {"tier":"B","wr":49.5,"pr":4.5,"br":2.5},
    56:  {"tier":"B","wr":49.2,"pr":4.8,"br":3.2},
    20:  {"tier":"A","wr":50.8,"pr":5.2,"br":2.8},
    2:   {"tier":"B","wr":49.5,"pr":3.5,"br":1.8},
    61:  {"tier":"A","wr":51.2,"pr":6.5,"br":3.2},
    80:  {"tier":"B","wr":50.1,"pr":5.5,"br":3.8},
    78:  {"tier":"B","wr":49.8,"pr":4.2,"br":2.1},
    133: {"tier":"A","wr":50.8,"pr":6.8,"br":4.5},
    33:  {"tier":"B","wr":50.2,"pr":4.5,"br":2.5},
    58:  {"tier":"S","wr":52.5,"pr":7.8,"br":5.5},
    107: {"tier":"B","wr":49.8,"pr":5.5,"br":3.2},
    92:  {"tier":"A","wr":51.0,"pr":6.5,"br":4.2},
    68:  {"tier":"B","wr":49.5,"pr":3.5,"br":2.1},
    13:  {"tier":"B","wr":50.0,"pr":3.2,"br":1.5},
    113: {"tier":"A","wr":51.5,"pr":5.8,"br":3.5},
    35:  {"tier":"B","wr":50.2,"pr":4.8,"br":2.8},
    98:  {"tier":"A","wr":51.2,"pr":6.5,"br":3.8},
    102: {"tier":"B","wr":49.8,"pr":3.5,"br":2.1},
    27:  {"tier":"B","wr":50.0,"pr":4.2,"br":2.5},
    14:  {"tier":"B","wr":49.5,"pr":3.2,"br":1.8},
    72:  {"tier":"B","wr":49.2,"pr":3.5,"br":2.1},
    37:  {"tier":"A","wr":52.5,"pr":6.8,"br":3.5},
    16:  {"tier":"B","wr":50.2,"pr":4.5,"br":2.5},
    50:  {"tier":"A","wr":51.8,"pr":7.5,"br":5.2},
    91:  {"tier":"A","wr":51.5,"pr":5.8,"br":3.5},
    44:  {"tier":"B","wr":50.0,"pr":3.8,"br":1.5},
    17:  {"tier":"B","wr":49.8,"pr":4.2,"br":2.8},
    412: {"tier":"S","wr":51.2,"pr":9.2,"br":5.5},
    23:  {"tier":"A","wr":51.5,"pr":5.8,"br":2.5},
    48:  {"tier":"B","wr":49.5,"pr":3.8,"br":2.1},
    77:  {"tier":"B","wr":49.8,"pr":4.5,"br":2.5},
    6:   {"tier":"B","wr":50.0,"pr":3.2,"br":1.8},
    67:  {"tier":"A","wr":50.8,"pr":7.5,"br":3.5},
    45:  {"tier":"B","wr":49.5,"pr":3.5,"br":2.1},
    161: {"tier":"A","wr":51.5,"pr":5.8,"br":3.5},
    112: {"tier":"A","wr":51.0,"pr":6.2,"br":4.5},
    8:   {"tier":"B","wr":50.5,"pr":5.5,"br":3.2},
    106: {"tier":"A","wr":51.8,"pr":6.8,"br":4.5},
    19:  {"tier":"A","wr":52.0,"pr":6.5,"br":4.2},
    62:  {"tier":"A","wr":51.2,"pr":7.2,"br":5.8},
    101: {"tier":"A","wr":51.5,"pr":6.5,"br":4.5},
    5:   {"tier":"A","wr":51.8,"pr":6.2,"br":3.5},
    157: {"tier":"S","wr":52.5,"pr":8.5,"br":6.5},
    83:  {"tier":"B","wr":49.8,"pr":4.5,"br":2.8},
    154: {"tier":"B","wr":49.5,"pr":4.2,"br":2.5},
    238: {"tier":"A","wr":50.5,"pr":6.8,"br":5.5},
    26:  {"tier":"B","wr":50.0,"pr":3.8,"br":2.1},
    142: {"tier":"A","wr":51.0,"pr":5.5,"br":3.8},
    236: {"tier":"S","wr":52.2,"pr":9.2,"br":5.8},
    117: {"tier":"A","wr":52.0,"pr":6.8,"br":3.2},
    43:  {"tier":"B","wr":50.2,"pr":4.5,"br":2.5},
    203: {"tier":"B","wr":49.8,"pr":3.5,"br":1.5},
    223: {"tier":"A","wr":51.2,"pr":5.8,"br":3.5},
    164: {"tier":"A","wr":51.5,"pr":7.2,"br":5.5},
    141: {"tier":"S","wr":52.8,"pr":8.5,"br":6.8},
    240: {"tier":"A","wr":51.2,"pr":6.5,"br":4.2},
    145: {"tier":"A","wr":51.8,"pr":8.5,"br":5.5},
    235: {"tier":"A","wr":51.0,"pr":7.8,"br":4.5},
    234: {"tier":"A","wr":51.5,"pr":6.5,"br":4.2},
    147: {"tier":"A","wr":50.8,"pr":5.5,"br":3.5},
    200: {"tier":"B","wr":49.5,"pr":4.2,"br":2.5},
    221: {"tier":"B","wr":50.0,"pr":5.5,"br":3.8},
    233: {"tier":"A","wr":51.2,"pr":6.8,"br":4.5},
    360: {"tier":"A","wr":51.8,"pr":6.2,"br":3.5},
    901: {"tier":"B","wr":50.2,"pr":5.8,"br":3.2},
    427: {"tier":"A","wr":51.5,"pr":6.5,"br":4.5},
}

TAG_TO_ROLE = {
    "Fighter": "top", "Tank": "top", "Mage": "mid",
    "Assassin": "mid", "Marksman": "bot", "Support": "support",
}

MANUAL_ROLE = {
    266:"top",103:"mid",84:"mid",166:"mid",12:"support",32:"jungle",34:"mid",
    1:"mid",22:"bot",268:"mid",432:"support",53:"support",63:"support",201:"support",
    51:"bot",69:"mid",31:"top",42:"mid",122:"top",131:"jungle",119:"bot",
    36:"top",245:"jungle",60:"jungle",81:"bot",9:"jungle",114:"top",105:"mid",
    3:"mid",41:"top",86:"top",150:"top",79:"top",104:"jungle",120:"jungle",
    420:"jungle",39:"top",40:"support",59:"jungle",24:"top",126:"top",
    202:"bot",115:"bot",222:"bot",10:"mid",55:"mid",89:"support",64:"jungle",
    127:"mid",99:"support",54:"top",90:"mid",57:"top",11:"jungle",21:"bot",
    82:"top",25:"support",267:"support",75:"top",111:"support",76:"jungle",
    56:"jungle",20:"jungle",2:"top",61:"mid",80:"top",78:"top",133:"top",
    33:"top",58:"top",107:"jungle",92:"top",68:"mid",13:"mid",113:"jungle",
    35:"jungle",98:"top",102:"jungle",27:"top",14:"top",72:"bot",37:"support",
    16:"support",50:"support",91:"mid",44:"support",17:"top",412:"support",
    23:"bot",48:"top",77:"jungle",6:"top",67:"bot",45:"mid",161:"support",
    112:"mid",8:"mid",106:"top",19:"jungle",62:"jungle",101:"mid",5:"jungle",
    157:"mid",83:"top",154:"jungle",238:"mid",26:"mid",142:"mid",236:"bot",
    117:"support",43:"support",203:"jungle",223:"top",164:"top",141:"jungle",
    240:"top",145:"bot",235:"support",234:"jungle",147:"top",200:"jungle",
    221:"bot",233:"support",360:"bot",427:"support",
}

# ── Specific counter/synergy relations (38 popular champions) ─────────────────
SPECIFIC_RELATIONS = {
    157: {"synergy": [54,32,89,111,53], "counters": [22,51,81,21,202], "countered_by": [24,58,122,92,55]},
    238: {"synergy": [64,59,254], "counters": [22,51,99,67,81], "countered_by": [127,90,54,3,25]},
    64:  {"synergy": [238,157,92,84], "counters": [120,5,76,56], "countered_by": [19,32,35,24]},
    115: {"synergy": [89,111,412,53,117], "counters": [119,67,236,22], "countered_by": [238,11,105,84]},
    51:  {"synergy": [40,99,117,267], "counters": [22,202,236,81], "countered_by": [119,24,120,55]},
    81:  {"synergy": [37,89,40,412], "counters": [119,67,202,51], "countered_by": [22,51,53,157]},
    67:  {"synergy": [412,117,40,89], "counters": [54,33,82,122], "countered_by": [119,51,22,115]},
    412: {"synergy": [115,22,51,67,202,222], "counters": [37,89,53,111], "countered_by": [40,117,37,267]},
    53:  {"synergy": [22,51,115,119,202], "counters": [412,89,99,25], "countered_by": [117,37,40,267]},
    89:  {"synergy": [115,119,202,22,145], "counters": [37,117,53], "countered_by": [117,40,37,412]},
    117: {"synergy": [67,81,115,51], "counters": [89,111,105,240], "countered_by": [53,412,53]},
    24:  {"synergy": [64,59,254,141], "counters": [86,58,157,240], "countered_by": [54,33,82,114]},
    86:  {"synergy": [254,59,64,89], "counters": [24,420,11,157], "countered_by": [67,126,58,114]},
    92:  {"synergy": [254,64,59,238], "counters": [24,86,157,240], "countered_by": [54,33,58,122]},
    114: {"synergy": [64,59,254,122], "counters": [58,86,420,122], "countered_by": [54,33,24,92]},
    58:  {"synergy": [59,254,64,114], "counters": [24,11,92,240], "countered_by": [114,67,86,82]},
    54:  {"synergy": [157,202,67,238], "counters": [114,67,92,119], "countered_by": [24,58,82,114]},
    120: {"synergy": [32,61,89,111], "counters": [64,5,76,56], "countered_by": [19,254,24,59]},
    59:  {"synergy": [238,92,58,157], "counters": [120,121,76,56], "countered_by": [19,254,64,24]},
    22:  {"synergy": [412,89,53,117], "counters": [202,81,67,236], "countered_by": [119,24,120,238]},
    119: {"synergy": [89,111,53,412], "counters": [81,67,22,202], "countered_by": [51,115,202,54]},
    84:  {"synergy": [64,113,59,157], "counters": [22,51,99,67], "countered_by": [3,127,90,54]},
    55:  {"synergy": [59,254,64,157], "counters": [22,51,69,99], "countered_by": [3,25,90,54]},
    131: {"synergy": [157,64,254,240], "counters": [22,51,69,67], "countered_by": [3,25,82,54]},
    141: {"synergy": [89,32,111,54], "counters": [64,120,254,19], "countered_by": [19,24,64,58]},
    240: {"synergy": [157,54,32,89], "counters": [22,51,67,81], "countered_by": [24,58,114,92]},
    145: {"synergy": [89,111,412,53], "counters": [81,67,202,22], "countered_by": [51,115,119,24]},
    236: {"synergy": [89,40,412,111], "counters": [81,22,67,202], "countered_by": [51,115,202,24]},
    5:   {"synergy": [89,32,111,59], "counters": [64,120,254,76], "countered_by": [19,24,64,58]},
    11:  {"synergy": [89,32,40,53], "counters": [22,51,99,67], "countered_by": [24,58,19,54]},
    122: {"synergy": [59,254,64,92], "counters": [86,157,420,240], "countered_by": [67,114,24,82]},
    62:  {"synergy": [157,59,64,238], "counters": [22,51,81,67], "countered_by": [24,58,86,122]},
    234: {"synergy": [89,32,111,54], "counters": [64,120,19,254], "countered_by": [24,58,64,92]},
    164: {"synergy": [64,59,254,141], "counters": [86,157,92,240], "countered_by": [24,58,114,122]},
    147: {"synergy": [59,254,64,157], "counters": [86,157,82,122], "countered_by": [24,58,92,114]},
}

# ── Lane proximity weights ────────────────────────────────────────────────────
LANE_PROXIMITY = {
    ("top","top"):1.5,("jungle","jungle"):1.5,("mid","mid"):1.5,
    ("bot","bot"):1.5,("support","support"):1.5,
    ("jungle","top"):0.9,("jungle","mid"):0.9,("jungle","bot"):0.8,("jungle","support"):0.7,
    ("top","jungle"):0.8,("mid","jungle"):0.8,("bot","jungle"):0.7,("support","jungle"):0.7,
    ("mid","top"):0.7,("mid","bot"):0.6,("mid","support"):0.5,
    ("top","mid"):0.6,("bot","mid"):0.5,("support","mid"):0.5,
    ("support","top"):0.4,("support","bot"):1.0,("bot","support"):1.0,
    ("top","bot"):0.3,("top","support"):0.3,("bot","top"):0.3,
}

ROLE_SYNERGY = {
    ("bot","support"):22,("support","bot"):22,
    ("top","jungle"):18,("jungle","top"):18,
    ("mid","jungle"):18,("jungle","mid"):18,
    ("top","mid"):12,("mid","top"):12,
    ("jungle","support"):10,("support","jungle"):10,
}

TAG_COUNTER_MATRIX = {
    ("Assassin","Marksman"):25,("Assassin","Mage"):20,("Assassin","Support"):15,
    ("Tank","Assassin"):25,("Tank","Fighter"):15,("Tank","Mage"):15,
    ("Mage","Fighter"):20,("Mage","Tank"):15,("Mage","Assassin"):10,
    ("Marksman","Tank"):22,("Marksman","Fighter"):15,("Marksman","Assassin"):10,
    ("Fighter","Tank"):20,("Fighter","Assassin"):18,("Fighter","Marksman"):18,
    ("Fighter","Mage"):15,
    ("Support","Assassin"):22,("Support","Fighter"):15,("Support","Mage"):10,
}

COUNTER_ARCHES = {"assassin", "dive", "engage", "pick"}
VULNERABLE_ARCHES = {"marksman", "hypercarry", "control-mage", "poke"}


class ChampionData:
    def __init__(self):
        self.champions: dict[int, dict] = {}
        self.id_to_key: dict[int, str] = {}
        self.key_to_id: dict[str, int] = {}
        self.version = ""
        self._load_or_fetch()
        self._load_archetypes()

    def _load_or_fetch(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(CHAMPION_CACHE):
            with open(CHAMPION_CACHE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if time.time() - cache.get("cached_at", 0) < 86400:
                self._parse_dd(cache)
                return
        self._fetch()

    def _fetch(self):
        try:
            versions = requests.get(DD_VERSION_URL, timeout=10).json()
            self.version = versions[0]
        except Exception:
            self.version = "16.9.1"
        try:
            url = f"https://ddragon.leagueoflegends.com/cdn/{self.version}/data/zh_CN/champion.json"
            data = requests.get(url, timeout=15).json()
            data["cached_at"] = time.time()
            with open(CHAMPION_CACHE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            self._parse_dd(data)
        except Exception:
            if os.path.exists(CHAMPION_CACHE):
                with open(CHAMPION_CACHE, "r", encoding="utf-8") as f:
                    self._parse_dd(json.load(f))

    def _parse_dd(self, data):
        self.version = data.get("version", self.version)
        dd = data.get("data", {})
        self.champions.clear(); self.id_to_key.clear(); self.key_to_id.clear()
        for dd_id, info in dd.items():
            key = int(info["key"])
            tags = info["tags"]
            role = MANUAL_ROLE.get(key)
            if not role:
                for tag in tags:
                    if tag in TAG_TO_ROLE:
                        role = TAG_TO_ROLE[tag]; break
                if not role:
                    role = "unknown"
            image_url = f"https://ddragon.leagueoflegends.com/cdn/{self.version}/img/champion/{dd_id}.png"
            self.champions[key] = {"name": info["name"], "dd_id": dd_id, "tags": tags, "image_url": image_url, "role": role}
            self.id_to_key[key] = dd_id
            self.key_to_id[dd_id] = key

    def _load_archetypes(self):
        arch_file = os.path.join(DATA_DIR, "champion_archetypes.json")
        self.champion_archetypes: dict[str, list[str]] = {}
        self.synergy_rules: dict[str, float] = {}
        self.anti_synergy_rules: dict[str, float] = {}
        try:
            if os.path.exists(arch_file):
                with open(arch_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.champion_archetypes = data.get("archetypes", {})
                self.synergy_rules = data.get("synergy_rules", {})
                self.anti_synergy_rules = data.get("anti_synergy_rules", {})
        except Exception:
            pass

    # ── Accessors ──
    def get_name(self, key): return self.champions.get(key, {}).get("name", f"#{key}")
    def get_image(self, key): return self.champions.get(key, {}).get("image_url", "")
    def get_role(self, key): return self.champions.get(key, {}).get("role", "unknown")
    def get_tags(self, key): return self.champions.get(key, {}).get("tags", [])
    def get_archetypes(self, key):
        dd_id = self.id_to_key.get(key, "")
        return self.champion_archetypes.get(dd_id, [])

    def get_meta(self, key):
        from meta_fetcher import get_live_meta
        live = get_live_meta(key)
        if live:
            return live
        return META_DATA.get(key, {"tier":"B","wr":50.0,"pr":3.0,"br":2.0})

    def get_tier(self, key): return self.get_meta(key).get("tier", "B")
    def get_winrate(self, key): return self.get_meta(key).get("wr", 50.0)
    def get_pickrate(self, key): return self.get_meta(key).get("pr", 3.0)
    def get_banrate(self, key): return self.get_meta(key).get("br", 2.0)

    def all_champions(self): return list(self.champions.keys())

    def filter_by_role(self, role):
        if role == "all": return list(self.champions.keys())
        return [k for k, v in self.champions.items() if v["role"] == role]

    def get_lane_weight(self, my_pos, enemy_role):
        if not my_pos or not enemy_role: return 1.0
        mp = my_pos.lower().replace("utility","support").replace("bottom","bot")
        ep = enemy_role.lower().replace("utility","support").replace("bottom","bot")
        return LANE_PROXIMITY.get((mp, ep), 0.5)

    # ── Synergy ──
    def _calc_archetype_synergy(self, arches1, arches2):
        if not arches1 or not arches2: return 0.1
        best = 0.1
        for a1 in arches1:
            for a2 in arches2:
                pair = "+".join(sorted([a1, a2]))
                if pair in self.synergy_rules:
                    best = max(best, self.synergy_rules[pair])
                elif pair in self.anti_synergy_rules:
                    best = min(best, self.anti_synergy_rules[pair])
        return best

    def get_synergy_score(self, champ_key, teammate_keys):
        score = 0; syn_names = []
        my_role = self.get_role(champ_key)
        my_arches = set(self.get_archetypes(champ_key))
        team_roles = set()
        spec = SPECIFIC_RELATIONS.get(champ_key, {})
        spec_syn = spec.get("synergy", [])

        for tk in teammate_keys:
            if tk in spec_syn:
                score += 22; syn_names.append(self.get_name(tk))
            t_arches = set(self.get_archetypes(tk))
            arch_syn = self._calc_archetype_synergy(my_arches, t_arches)
            if arch_syn > 0.3:
                score += int(arch_syn * 25)
                if tk not in spec_syn: syn_names.append(self.get_name(tk))
            t_role = self.get_role(tk)
            score += ROLE_SYNERGY.get((my_role, t_role), 4)
            team_roles.add(t_role)

        if my_role in team_roles: score -= 10
        else: score += 12
        return score, syn_names

    # ── Counter ──
    def get_counter_score(self, champ_key, enemy_keys):
        score = 0; names = []
        my_tags = set(self.get_tags(champ_key))
        my_arches = set(self.get_archetypes(champ_key))
        spec = SPECIFIC_RELATIONS.get(champ_key, {})
        spec_counters = spec.get("counters", [])

        for ek in enemy_keys:
            if ek in spec_counters:
                score += 25; names.append(self.get_name(ek)); continue
            e_tags = set(self.get_tags(ek))
            best = 0
            for mt in my_tags:
                for et in e_tags:
                    best = max(best, TAG_COUNTER_MATRIX.get((mt, et), 0))
            e_arches = set(self.get_archetypes(ek))
            if my_arches & COUNTER_ARCHES and e_arches & VULNERABLE_ARCHES:
                best = max(best, 18)
            if best >= 12:
                score += best; names.append(self.get_name(ek))
        return score, names

    def get_countered_score(self, champ_key, enemy_keys):
        score = 0; names = []
        my_tags = set(self.get_tags(champ_key))
        my_arches = set(self.get_archetypes(champ_key))
        spec = SPECIFIC_RELATIONS.get(champ_key, {})
        spec_countered = spec.get("countered_by", [])

        for ek in enemy_keys:
            if ek in spec_countered:
                score += 22; names.append(self.get_name(ek)); continue
            e_tags = set(self.get_tags(ek))
            best = 0
            for et in e_tags:
                for mt in my_tags:
                    best = max(best, TAG_COUNTER_MATRIX.get((et, mt), 0))
            e_arches = set(self.get_archetypes(ek))
            if e_arches & COUNTER_ARCHES and my_arches & VULNERABLE_ARCHES:
                best = max(best, 18)
            if best >= 12:
                score += best; names.append(self.get_name(ek))
        return score, names


_instance = None

def get_champion_data():
    global _instance
    if _instance is None:
        _instance = ChampionData()
    return _instance
