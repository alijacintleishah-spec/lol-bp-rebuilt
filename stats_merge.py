"""
Merge multiple stats_export.json files into a single global_stats.json.
Weighted average: each user's stats are weighted by their game count.
No deduplication — every game is treated as an independent data point.

Usage: python stats_merge.py file1.json file2.json ... [--output global_stats.json]
"""

import json
import sys
from datetime import datetime


def _weighted_merge_counter(base: dict, add: dict, weight: int,
                             add_weight: int) -> dict:
    """Merge counter_matchups stats with weighted averaging."""
    for cid_str, roles in add.items():
        b_cid = base.setdefault(cid_str, {})
        for role, enemies in roles.items():
            b_role = b_cid.setdefault(role, {})
            for eid_str, stats in enemies.items():
                g = stats.get("g", 0)
                w = stats.get("w", 0)
                gd10 = stats.get("gd10", 0)
                cd10 = stats.get("cd10", 0)
                xd10 = stats.get("xd10", 0)
                if eid_str in b_role:
                    b = b_role[eid_str]
                    b["g"] += g
                    b["w"] += w
                    # Weighted average for diffs
                    if g > 0:
                        b["gd10"] = round(
                            (b["gd10"] * b["g"] + gd10 * g) / (b["g"] + g), 1
                        ) if g > 0 else b["gd10"]
                        b["cd10"] = round(
                            (b["cd10"] * b["g"] + cd10 * g) / (b["g"] + g), 1
                        ) if g > 0 else b["cd10"]
                        b["xd10"] = round(
                            (b["xd10"] * b["g"] + xd10 * g) / (b["g"] + g), 1
                        ) if g > 0 else b["xd10"]
                else:
                    b_role[eid_str] = {
                        "g": g, "w": w,
                        "gd10": gd10, "cd10": cd10, "xd10": xd10,
                    }
    return base


def _weighted_merge_list(base: dict, add: dict) -> dict:
    """Merge rune/spell/item lists by summing games+wins, keeping top by games."""
    for cid_str, roles in add.items():
        b_cid = base.setdefault(cid_str, {})
        for role, entries in roles.items():
            b_role = b_cid.setdefault(role, [])
            existing_keys = {}
            for i, be in enumerate(b_role):
                if "k" in be:  # runes: key by keystone+primary+sub
                    key = (be.get("k"), be.get("p"), be.get("s"))
                elif "s" in be:  # spells: key by sorted spell pair
                    key = tuple(sorted(be.get("s", [])))
                elif "i" in be:  # items: key by sorted item tuple
                    key = tuple(sorted(be.get("i", [])))
                else:
                    key = None
                if key:
                    existing_keys[key] = i

            for entry in entries:
                if "k" in entry:
                    key = (entry.get("k"), entry.get("p"), entry.get("s"))
                elif "s" in entry:
                    key = tuple(sorted(entry.get("s", [])))
                elif "i" in entry:
                    key = tuple(sorted(entry.get("i", [])))
                else:
                    key = None

                g = entry.get("g", 0)
                w = entry.get("w", 0)
                if key and key in existing_keys:
                    idx = existing_keys[key]
                    b_role[idx]["g"] += g
                    b_role[idx]["w"] += w
                else:
                    b_role.append(dict(entry))
                    if key:
                        existing_keys[key] = len(b_role) - 1

            b_role.sort(key=lambda x: -x["g"])
            b_cid[role] = b_role[:15]  # Keep top 15
    return base


def _weighted_merge_synergy(base: dict, add: dict) -> dict:
    """Merge synergy rates by summing games+wins."""
    for cid_str, teammates in add.items():
        b_cid = base.setdefault(cid_str, {})
        for tid_str, stats in teammates.items():
            g = stats.get("g", 0)
            w = stats.get("w", 0)
            if tid_str in b_cid:
                b_cid[tid_str]["g"] += g
                b_cid[tid_str]["w"] += w
            else:
                b_cid[tid_str] = {"g": g, "w": w}
    return base


def merge_stats_files(file_paths: list[str],
                       output_path: str = "global_stats.json") -> dict:
    """Merge multiple export files into one global stats file."""
    if not file_paths:
        print("No files to merge.")
        return {}

    merged = {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "total_games": 0,
        "rank_distribution": {},
        "stats": {
            "counter_matchups": {},
            "rune_rates": {},
            "spell_rates": {},
            "item_rates": {},
            "synergy_rates": {},
        },
    }

    total_users = 0
    for path in file_paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  SKIP {path}: {e}")
            continue

        total_users += 1
        games = data.get("total_games", 0)
        merged["total_games"] += games

        # Merge rank distribution
        for tier, cnt in data.get("rank_distribution", {}).items():
            merged["rank_distribution"][tier] = (
                merged["rank_distribution"].get(tier, 0) + cnt
            )

        stats = data.get("stats", {})

        merged["stats"]["counter_matchups"] = _weighted_merge_counter(
            merged["stats"]["counter_matchups"],
            stats.get("counter_matchups", {})
        )
        merged["stats"]["rune_rates"] = _weighted_merge_list(
            merged["stats"]["rune_rates"],
            stats.get("rune_rates", {})
        )
        merged["stats"]["spell_rates"] = _weighted_merge_list(
            merged["stats"]["spell_rates"],
            stats.get("spell_rates", {})
        )
        merged["stats"]["item_rates"] = _weighted_merge_list(
            merged["stats"]["item_rates"],
            stats.get("item_rates", {})
        )
        merged["stats"]["synergy_rates"] = _weighted_merge_synergy(
            merged["stats"]["synergy_rates"],
            stats.get("synergy_rates", {})
        )


    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)

    # Print summary
    counter_entries = sum(
        len(enemies)
        for roles in merged["stats"]["counter_matchups"].values()
        for enemies in roles.values()
    )
    rune_entries = sum(
        len(entries)
        for roles in merged["stats"]["rune_rates"].values()
        for entries in roles.values()
    )
    print(f"合并完成: {total_users} 个用户, {merged['total_games']} 局")
    print(f"  对位条目: {counter_entries}")
    print(f"  符文条目: {rune_entries}")
    print(f"  输出: {output_path}")

    return merged


if __name__ == "__main__":
    args = sys.argv[1:]
    output = "global_stats.json"
    files = []

    for arg in args:
        if arg == "--output" or arg == "-o":
            output_idx = args.index(arg) + 1
            if output_idx < len(args):
                output = args[output_idx]
            continue
        if arg.endswith(".json"):
            files.append(arg)

    if not files:
        print("Usage: python stats_merge.py file1.json file2.json ... [--output global_stats.json]")
        sys.exit(1)

    merge_stats_files(files, output)
