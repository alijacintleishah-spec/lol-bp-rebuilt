"""
LoL BP Assistant — Iteration 6a: CLI Interface
Interactive command-line recommendation tool.
"""

from champion_data import get_champion_data
from recommender import recommend
from engine import build_ban_recommendations, analyze_composition

cd = get_champion_data()

POSITIONS = {"1":"top","2":"jungle","3":"mid","4":"bot","5":"support",
             "t":"top","j":"jungle","m":"mid","b":"bot","s":"support"}

print("=" * 50)
print("  LoL BP Assistant CLI  v2.0")
print("=" * 50)

# ── Search helper ──
def search_champ(prompt="Search champion: "):
    while True:
        q = input(prompt).strip()
        if not q:
            return None
        results = []
        for key in cd.all_champions():
            name = cd.get_name(key)
            role = cd.get_role(key)
            if q.lower() in name.lower() or q.lower() in role.lower():
                results.append((key, name, role, cd.get_tier(key)))
        results.sort(key=lambda x: ({"S":0,"A":1,"B":2,"C":3}.get(x[3],2), x[1]))
        if not results:
            print("  No match. Try again.")
            continue
        if len(results) == 1:
            return results[0][0]
        for i, (k, n, r, t) in enumerate(results[:10]):
            print(f"  [{i+1}] {n:8s} [{r}] {t}")
        pick = input("  Pick number (or 0 to re-search): ").strip()
        if pick.isdigit():
            idx = int(pick) - 1
            if idx == -1: continue
            if 0 <= idx < len(results):
                return results[idx][0]
        print("  Invalid. Try again.")

# ── Position ──
print("\nYour position:")
for k, v in [("1","Top"),("2","Jungle"),("3","Mid"),("4","Bot"),("5","Support")]:
    print(f"  [{k}] {v}")
pos_input = input("Choice (1-5): ").strip().lower()
my_pos = POSITIONS.get(pos_input, "mid")
print(f"  → {my_pos}")

# ── My team picks ──
print("\nYour team's picks (enter champion name, blank to finish):")
my_picks = []
while len(my_picks) < 5:
    ck = search_champ(f"  Pick {len(my_picks)+1}: ")
    if ck is None: break
    if ck in my_picks:
        print("  Already picked.")
        continue
    my_picks.append(ck)

# ── Enemy picks ──
print("\nEnemy picks (enter champion name, blank to finish):")
enemy_picks = []
while len(enemy_picks) < 5:
    ck = search_champ(f"  Enemy {len(enemy_picks)+1}: ")
    if ck is None: break
    if ck in enemy_picks:
        print("  Already picked.")
        continue
    enemy_picks.append(ck)

# ── Bans ──
print("\nBans (enter champion name, blank to finish):")
banned = []
while len(banned) < 10:
    ck = search_champ(f"  Ban {len(banned)+1}: ")
    if ck is None: break
    if ck in banned:
        print("  Already banned.")
        continue
    banned.append(ck)

# ── Show results ──
used = set(banned + my_picks + enemy_picks)
recs = recommend(my_pos, enemy_picks, banned, my_picks)
ban_recs = build_ban_recommendations(used, my_picks, enemy_picks, my_pos)
my_comp = analyze_composition(tuple(my_picks))
enemy_comp = analyze_composition(tuple(enemy_picks))

print(f"\n{'='*55}")
print(f"  Pick Recommendations ({my_pos})")
print(f"{'='*55}")
for i, r in enumerate(recs):
    pos_tag = "✓对位" if r.get("position_match") else ""
    reasons = " · ".join(r.get("reasons", [])[:3])
    print(f"  #{i+1:<2} {r['name']:10s} {r['tier']:1s}  WR {r['winrate']:.1f}%  +{r['score']:.0f}  {pos_tag}  {reasons}")

print(f"\n{'='*55}")
print(f"  Ban Recommendations")
print(f"{'='*55}")
role_labels = {"top": "上路", "jungle": "打野", "mid": "中路", "bot": "ADC", "support": "辅助"}
for role in ["top", "jungle", "mid", "bot", "support"]:
    recs = ban_recs.get(role, [])
    if not recs:
        continue
    print(f"  ── {role_labels.get(role, role)} ──")
    for i, r in enumerate(recs):
        reasons = " · ".join(r.get("reasons", [])[:2])
        print(f"  #{i+1}  {r['name']:10s} {r['tier']}  WR {r['winrate']:.1f}%  +{r['score']:.0f}  {reasons}")

print(f"\n  My comp: {my_comp.get('icon','')} {my_comp.get('name','')}")
print(f"  Enemy comp: {enemy_comp.get('icon','')} {enemy_comp.get('name','')}")
