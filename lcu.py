"""
LCU (League Client Update) API connection module.
WebSocket-based champ select detection + REST fallback.
"""

import base64
import json
import os
import re
import ssl
import subprocess
import threading
import time
import logging
import requests
import websocket

# 抑制本地 LCU API 自签名证书警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

_last_port = None
_cached_lcu = {"port": None, "token": None, "found": False}


def _is_game_client(port, token):
    """检查端口是否是真正的游戏客户端（而非启动器）."""
    try:
        auth = base64.b64encode(f"riot:{token}".encode()).decode()
        h = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
        r = requests.get(
            f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
            headers=h, verify=False, timeout=3
        )
        return r.status_code == 200
    except Exception:
        return False


def find_lcu_process():
    """多种方式检测 LCU 进程，获取端口和 token。优先返回游戏客户端端口。"""
    global _last_port
    import psutil
    candidates = []  # (port, token, source)

    try:
        for proc in psutil.process_iter(["name", "cmdline", "exe"]):
            try:
                name = (proc.info["name"] or "").lower()
                cmdline = proc.info["cmdline"] or []
                cmd_str = " ".join(cmdline)
                exe_path = proc.info.get("exe") or ""

                if name in ("leagueclientux.exe", "leagueclient.exe",
                            "league of legends.exe", "riotclientservices.exe"):
                    for pattern_token in [
                        (r"--app-port=(\d+)", r"--remoting-auth-token=([\w-]+)"),
                        (r"--riotclient-app-port=(\d+)", r"--riotclient-auth-token=([\w-]+)"),
                    ]:
                        pm = re.search(pattern_token[0], cmd_str)
                        tm = re.search(pattern_token[1], cmd_str)
                        if pm and tm:
                            candidates.append((pm.group(1), tm.group(1), name))

                    if exe_path:
                        lock_dir = os.path.dirname(exe_path)
                        lf = os.path.join(lock_dir, "lockfile")
                        if os.path.exists(lf):
                            with open(lf, "r") as f:
                                content = f.read().strip()
                            parts = content.split(":")
                            if len(parts) >= 3:
                                candidates.append((parts[1], parts[2], f"lockfile({name})"))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass

    # 搜索已知 lockfile 路径
    for lf_path in [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Riot Games", "League of Legends", "lockfile"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), "League of Legends", "lockfile"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "League of Legends", "lockfile"),
        "C:/Program Files/League of Legends/lockfile",
        "C:/Riot Games/League of Legends/lockfile",
        "D:/WeGame/英雄联盟/lockfile",
        "D:/英雄联盟/lockfile",
        "E:/英雄联盟/lockfile",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Tencent", "League of Legends", "lockfile"),
    ]:
        try:
            if os.path.exists(lf_path):
                with open(lf_path, "r") as f:
                    content = f.read().strip()
                parts = content.split(":")
                if len(parts) >= 3:
                    candidates.append((parts[1], parts[2], lf_path))
        except Exception:
            continue

    # wmic 兜底
    try:
        for proc_name in ("LeagueClientUx.exe", "LeagueClient.exe"):
            result = subprocess.run(
                ["cmd", "/c", "wmic", "PROCESS", "WHERE", f"name='{proc_name}'", "GET", "commandline"],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            cmd = result.stdout
            if cmd and "No Instance" not in cmd:
                pm = re.search(r"--app-port=(\d+)", cmd)
                tm = re.search(r"--remoting-auth-token=([\w-]+)", cmd)
                if pm and tm:
                    candidates.append((pm.group(1), tm.group(1), "wmic"))
    except Exception:
        pass

    # 候选去重，优先返回游戏客户端端口
    seen = set()
    unique = []
    for port, token, source in candidates:
        key = (port, token)
        if key not in seen:
            seen.add(key)
            unique.append((port, token, source))

    for port, token, source in unique:
        if _is_game_client(port, token):
            if port != _last_port:
                logger.info("找到游戏客户端: 端口 %s (来源: %s)", port, source)
                _last_port = port
            return port, token

    # 无游戏客户端，返回任意可用端口
    for port, token, source in unique:
        if port != _last_port:
            logger.info("找到 LCU (启动器): 端口 %s (来源: %s)", port, source)
            _last_port = port
        return port, token

    return None, None


def fetch_teammate_mastery(headers, base_url, session=None):
    """
    获取队友擅长英雄数据：
    1. 本地玩家的英雄熟练度 (level>=4 的英雄)
    2. 队友的 championPickIntent（预选英雄）
    返回: {champion_id: weight}  weight 范围 3~10
    """
    pool = {}

    # 1. 本地玩家英雄熟练度
    try:
        r = requests.get(
            f"{base_url}/lol-champion-mastery/v1/local-player/champion-mastery",
            headers=headers, verify=False, timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            data.sort(key=lambda x: x.get("championPoints", 0), reverse=True)
            for m in data[:8]:
                cid = m.get("championId", 0)
                level = m.get("championLevel", 1)
                if cid and level >= 4:
                    pool[cid] = min(10, level + 2)
    except Exception:
        pass

    # 2. 队友 championPickIntent
    if session:
        local_cell = session.get("localPlayerCellId", -1)
        for p in session.get("myTeam", []):
            if p.get("cellId") == local_cell:
                continue
            intent = p.get("championPickIntent", 0)
            if intent and intent > 0 and intent not in pool:
                pool[intent] = 5

    return pool


# ── Rank & Queue Detection ──────────────────────────────────────────────────

# LCU tier → Chinese display name
TIER_NAMES = {
    "IRON": "黑铁", "BRONZE": "青铜", "SILVER": "白银",
    "GOLD": "黄金", "PLATINUM": "铂金", "EMERALD": "翡翠",
    "DIAMOND": "钻石", "MASTER": "大师", "GRANDMASTER": "宗师",
    "CHALLENGER": "王者", "UNRANKED": "未定级",
}

# LCU division → Roman numeral
DIV_NAMES = {"I": "I", "II": "II", "III": "III", "IV": "IV", "NA": ""}

# Queue ID → game mode name
QUEUE_NAMES = {
    420: "单双排位", 440: "灵活排位", 400: "普通征召",
    430: "普通盲选", 450: "极地大乱斗", 700: "冠军杯赛",
    1700: "冠军杯赛", 1710: "冠军杯赛",
    490: "快速游戏", 890: "人机", 900: "无限火力",
}

# Queue ID → short key
QUEUE_KEY = {
    420: "solo_duo", 440: "flex", 400: "normal_draft",
    430: "normal_blind", 450: "aram", 490: "quickplay",
}


def fetch_summoner_ranks(headers, base_url):
    """Fetch summoner's Solo/Duo and Flex ranks from LCU.
    Returns {(solo_duo|flex): {tier, division, lp, display}}.
    """
    ranks = {}
    try:
        r = requests.get(
            f"{base_url}/lol-ranked/v1/current-ranked-stats",
            headers=headers, verify=False, timeout=5
        )
        if r.status_code == 200:
            data = r.json()
            for queue in data.get("queues", []):
                q_type = queue.get("queueType", "")
                tier = queue.get("tier", "UNRANKED")
                div = queue.get("division", "NA")
                lp = queue.get("leaguePoints", 0)
                wins = queue.get("wins", 0)
                losses = queue.get("losses", 0)
                display = TIER_NAMES.get(tier, tier)
                if div and div != "NA":
                    display += f" {DIV_NAMES.get(div, div)}"
                if lp > 0 and tier in ("MASTER", "GRANDMASTER", "CHALLENGER"):
                    display += f" {lp}LP"

                rank_info = {
                    "tier": tier, "division": div, "lp": lp,
                    "display": display, "wins": wins, "losses": losses,
                }

                if q_type == "RANKED_SOLO_5x5":
                    ranks["solo_duo"] = rank_info
                elif q_type == "RANKED_FLEX_SR":
                    ranks["flex"] = rank_info
    except Exception:
        logger.debug("Failed to fetch summoner ranks", exc_info=True)

    return ranks


def detect_game_mode(session):
    """Detect game mode from champ select session or gameflow.
    Returns {queue_id, queue_name, queue_key}.
    """
    queue_id = session.get("queueId", 0) or session.get("queue", {}).get("id", 0)

    # Fallback: check actions structure to infer mode
    if not queue_id:
        actions = session.get("actions", [])
        if isinstance(actions, list):
            # 10 bans + 10 picks = ranked draft
            flat_actions = [a for g in actions if g for a in g] if actions else []
            total_actions = len(flat_actions)
            if total_actions >= 20:
                queue_id = 420  # Assume ranked draft
            elif total_actions > 0:
                queue_id = 400  # Assume normal draft

    return {
        "queue_id": queue_id,
        "queue_name": QUEUE_NAMES.get(queue_id, f"未知模式({queue_id})"),
        "queue_key": QUEUE_KEY.get(queue_id, "unknown"),
    }


def _norm_pos(pos):
    """归一化 LCU 位置名 → 项目内部名."""
    if not pos:
        return "unknown"
    pos = pos.lower()
    if pos == "bottom":
        return "bot"
    if pos == "utility":
        return "support"
    return pos


def parse_session(session):
    """解析 LCU session 数据."""
    raw_actions = session.get("actions") or []
    actions_flat = []
    for group in raw_actions:
        if group is not None and isinstance(group, list):
            actions_flat.extend(group)
    my_team_ids = {p["cellId"] for p in session.get("myTeam", [])}
    local_cell = session.get("localPlayerCellId", -1)

    my_bans, enemy_bans = [], []
    my_picks, enemy_picks = [], []

    for a in actions_flat:
        if a["type"] == "ban" and a.get("completed") and a["championId"] != 0:
            if a["actorCellId"] in my_team_ids:
                my_bans.append(a["championId"])
            else:
                enemy_bans.append(a["championId"])

    for p in session.get("myTeam", []):
        cid = p.get("championId", 0)
        if cid != 0:
            pos = _norm_pos(p.get("assignedPosition", ""))
            my_picks.append({"champion_id": cid, "position": pos})

    for p in session.get("theirTeam", []):
        cid = p.get("championId", 0)
        if cid != 0:
            pos = _norm_pos(p.get("assignedPosition", ""))
            enemy_picks.append({"champion_id": cid, "position": pos})

    # 预选英雄 (championPickIntent) — ban 阶段用于推荐
    my_prepicks, enemy_prepicks = [], []
    for p in session.get("myTeam", []):
        intent = p.get("championPickIntent", 0)
        if intent and intent > 0:
            my_prepicks.append(intent)
    for p in session.get("theirTeam", []):
        intent = p.get("championPickIntent", 0)
        if intent and intent > 0:
            enemy_prepicks.append(intent)

    my_position = ""
    for p in session.get("myTeam", []):
        if p.get("cellId") == local_cell:
            my_position = _norm_pos(p.get("assignedPosition", ""))

    timer_info = session.get("timer", {})
    phase = timer_info.get("phase", "BAN_PICK")
    total = timer_info.get("totalTime", 0) / 1000.0
    remaining = timer_info.get("adjustedTimeLeftInPhase", total * 1000) / 1000.0

    # Build position maps
    my_cell_to_pos = {}
    for p in session.get("myTeam", []):
        my_cell_to_pos[p.get("cellId", -1)] = _norm_pos(p.get("assignedPosition", ""))
    enemy_cell_to_pos = {}
    for p in session.get("theirTeam", []):
        enemy_cell_to_pos[p.get("cellId", -1)] = _norm_pos(p.get("assignedPosition", ""))

    action_seq = []
    for a in actions_flat:
        actor = a.get("actorCellId", -1)
        is_mine = actor in my_team_ids
        actor_pos = ""
        if is_mine:
            actor_pos = my_cell_to_pos.get(actor, "")
        else:
            actor_pos = enemy_cell_to_pos.get(actor, "")

        action_seq.append({
            "type": a["type"],
            "champion_id": a.get("championId", 0),
            "completed": a.get("completed", False),
            "is_mine": is_mine,
            "is_self": actor == local_cell,
            "position": actor_pos,
        })

    # Find all uncompleted actions in the first active phase (sub-array)
    # In duo pick phases, 2 players act simultaneously — we need both
    next_actions = []
    for group in raw_actions:
        if group is None or not isinstance(group, list):
            continue
        uncompleted = [a for a in group
                       if not a.get("completed", False)
                       and a.get("championId", 0) == 0]
        if uncompleted:
            for a in uncompleted:
                actor = a.get("actorCellId", -1)
                is_mine = actor in my_team_ids
                actor_pos = ""
                if is_mine:
                    actor_pos = my_cell_to_pos.get(actor, "")
                else:
                    actor_pos = enemy_cell_to_pos.get(actor, "")
                next_actions.append({
                    "type": a["type"],
                    "is_mine": is_mine,
                    "is_self": actor == local_cell,
                    "position": actor_pos,
                })
            break  # Only process the first active sub-array

    game_mode = detect_game_mode(session)

    return {
        "my_team_bans": my_bans,
        "enemy_bans": enemy_bans,
        "my_team_picks": my_picks,
        "enemy_picks": enemy_picks,
        "my_prepicks": my_prepicks,
        "enemy_prepicks": enemy_prepicks,
        "my_position": my_position,
        "phase": phase,
        "timer": {"phase": phase, "total_sec": int(total), "remaining_sec": int(remaining)},
        "action_seq": action_seq,
        "next_actions": next_actions,
        "next_action": next_actions[0] if next_actions else None,
        "queue_id": game_mode["queue_id"],
        "queue_name": game_mode["queue_name"],
        "queue_key": game_mode["queue_key"],
    }


def _has_players(session):
    """检查 session 是否真的有玩家（不是大厅空 session）."""
    if not isinstance(session, dict):
        return False
    my_team = session.get("myTeam", [])
    their_team = session.get("theirTeam", [])
    if len(my_team) > 0 or len(their_team) > 0:
        return True
    actions = session.get("actions", [])
    if actions and len(actions) > 0 and len(actions[0]) > 0:
        return True
    return False


def poll_lcu(mstate, lcu_conn, manual_mode_ref, on_session_parsed_cb):
    """
    主循环：WebSocket 监听 + REST 兜底。
    阻塞循环，在独立线程中运行。
    """
    global _cached_lcu

    ws = None
    ws_thread = None
    ws_connected = False
    was_connected = False
    poll_count = 0

    def _on_ws_message(ws_conn, message):
        """WebSocket 消息回调."""
        nonlocal ws_connected
        try:
            event = json.loads(message)
            # LCU 事件格式: [msgType, eventName, data]
            if isinstance(event, list) and len(event) >= 3:
                msg_type, event_name, event_data = event[0], event[1], event[2]
                if msg_type == 8 and event_name == "OnJsonApiEvent":
                    uri = event_data.get("uri", "")
                    if "champ-select" in uri and "session" in uri:
                        event_type = event_data.get("eventType", "")
                        data = event_data.get("data", {})
                        logger.debug("WS champ-select: %s (uri=%s)", event_type, uri)
                        if event_type in ("Create", "Update"):
                            if _has_players(data):
                                if not mstate["in_champ_select"]:
                                    logger.info("WebSocket: 检测到进入英雄选择!")
                                    # 进入英雄选择时立即获取段位和队列信息（不阻塞主流程）
                                    try:
                                        if not lcu_conn.get("ranks_fetched"):
                                            _try_fetch_ranks(lcu_conn, headers, base_url)
                                    except Exception as e:
                                        logger.debug("获取段位失败: %s", e)
                                    try:
                                        q_info = _fetch_queue_info(headers, base_url)
                                        if q_info:
                                            lcu_conn["queue_id"] = q_info["queue_id"]
                                            lcu_conn["queue_name"] = q_info["queue_name"]
                                            lcu_conn["queue_key"] = q_info["queue_key"]
                                            logger.info("模式: %s", q_info["queue_name"])
                                    except Exception as e:
                                        logger.debug("获取队列信息失败: %s", e)
                                _apply_session(mstate, data, on_session_parsed_cb)
                        elif event_type == "Delete":
                            if mstate["in_champ_select"]:
                                logger.info("WebSocket: 退出英雄选择")
                            mstate["in_champ_select"] = False
                            mstate["recommendations"] = []
                            lcu_conn["_cs_restart"] = True
        except Exception:
            logger.debug("WS 消息解析异常", exc_info=True)

    def _on_ws_open(ws_conn):
        """WebSocket 连接成功."""
        nonlocal ws_connected
        ws_connected = True
        logger.info("WebSocket 已连接 LCU (端口 %s)", _cached_lcu.get("port", "?"))
        # 订阅 champ-select 事件
        try:
            ws_conn.send(json.dumps([5, "OnJsonApiEvent"]))
        except Exception:
            pass

    def _on_ws_error(ws_conn, error):
        nonlocal ws_connected
        ws_connected = False
        logger.debug("WebSocket 错误: %s", error)

    def _on_ws_close(ws_conn, close_status_code, close_msg):
        nonlocal ws_connected
        ws_connected = False
        logger.info("WebSocket 断开")

    def _apply_session(mstate, session, on_session_parsed_cb):
        """将 session 数据应用到 mstate."""
        try:
            parsed = parse_session(session)
        except Exception:
            logger.exception("Session 解析失败，使用最小状态")
            parsed = {
                "my_team_bans": [], "enemy_bans": [],
                "my_team_picks": [], "enemy_picks": [],
                "my_prepicks": [], "enemy_prepicks": [],
                "my_position": "", "phase": "BAN_PICK",
                "timer": {"phase": "BAN_PICK", "total_sec": 0, "remaining_sec": 0},
                "action_seq": [], "next_actions": [], "next_action": None,
                "queue_id": 0, "queue_name": "", "queue_key": "",
            }
        mstate.update(parsed)
        mstate["in_champ_select"] = True
        if on_session_parsed_cb:
            try:
                on_session_parsed_cb(parsed, session)
            except Exception:
                logger.exception("推荐引擎异常")

    def _fetch_gameflow_phase(headers, base_url):
        """REST 方式查 gameflow phase."""
        try:
            r = requests.get(
                f"{base_url}/lol-gameflow/v1/gameflow-phase",
                headers=headers, verify=False, timeout=3
            )
            if r.status_code == 200:
                return r.text.strip().strip('"')
        except Exception:
            pass
        return None

    def _fetch_queue_info(headers, base_url):
        """从 lobby 或 gameflow 获取当前队列信息."""
        # Try gameflow session first (has queue info during match)
        try:
            r = requests.get(
                f"{base_url}/lol-gameflow/v1/session",
                headers=headers, verify=False, timeout=3
            )
            if r.status_code == 200:
                data = r.json()
                queue = data.get("gameData", {}).get("queue", {})
                qid = queue.get("id", 0)
                if qid:
                    return {
                        "queue_id": qid,
                        "queue_name": QUEUE_NAMES.get(qid, f"未知({qid})"),
                        "queue_key": QUEUE_KEY.get(qid, "unknown"),
                    }
        except Exception:
            pass

        # Fallback: try lobby
        try:
            r = requests.get(
                f"{base_url}/lol-lobby/v2/lobby",
                headers=headers, verify=False, timeout=3
            )
            if r.status_code == 200:
                data = r.json()
                qid = data.get("gameConfig", {}).get("queueId", 0)
                if qid:
                    return {
                        "queue_id": qid,
                        "queue_name": QUEUE_NAMES.get(qid, f"未知({qid})"),
                        "queue_key": QUEUE_KEY.get(qid, "unknown"),
                    }
        except Exception:
            pass
        return None

    def _try_fetch_ranks(lcu_conn, headers, base_url):
        """Fetch summoner ranks once and cache in lcu_conn."""
        try:
            ranks = fetch_summoner_ranks(headers, base_url)
            if ranks:
                lcu_conn["ranks"] = ranks
                lcu_conn["ranks_fetched"] = True
                parts = []
                for key, label in [("solo_duo", "单双"), ("flex", "灵活")]:
                    if key in ranks:
                        parts.append(f"{label}:{ranks[key]['display']}")
                if parts:
                    logger.info("段位: %s", "  ".join(parts))
            else:
                # 没有段位信息（未定级或新账号）
                lcu_conn["ranks"] = {}
                lcu_conn["ranks_fetched"] = True
                logger.debug("未获取到段位信息（可能未定级）")
        except Exception as e:
            logger.debug("Rank fetch failed: %s", e)
            # 不标记为已获取，允许重试
            lcu_conn["ranks_fetched"] = False

    POLL_INTERVAL = 3.0
    RECONNECT_DELAY = 3

    while True:
        poll_count += 1
        if poll_count % 20 == 0:
            logger.debug("心跳 #%d (ws=%s, connected=%s, in_cs=%s)",
                        poll_count, ws_connected,
                        mstate.get("connected"), mstate.get("in_champ_select"))

        if manual_mode_ref():
            time.sleep(2)
            continue

        # ── 进程发现 ──
        if not _cached_lcu["found"]:
            port, token = find_lcu_process()
            if port:
                _cached_lcu = {"port": port, "token": token, "found": True}
            else:
                _cached_lcu = {"port": None, "token": None, "found": False}
        else:
            port, token = _cached_lcu["port"], _cached_lcu["token"]

        if not port:
            if not mstate["connected"]:
                mstate["connected"] = False
            lcu_conn["active"] = False
            ws_connected = False
            time.sleep(RECONNECT_DELAY)
            continue

        auth = base64.b64encode(f"riot:{token}".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "Accept": "application/json"
        }
        base_url = f"https://127.0.0.1:{port}"
        lcu_conn.update({"headers": headers, "base_url": base_url, "active": True})
        mstate["connected"] = True

        # ── WebSocket 连接 ──
        if not ws_connected and _cached_lcu["found"]:
            try:
                ws_url = f"wss://127.0.0.1:{port}/"
                ws = websocket.WebSocketApp(
                    ws_url,
                    header={"Authorization": f"Basic {auth}"},
                    on_open=_on_ws_open,
                    on_message=_on_ws_message,
                    on_error=_on_ws_error,
                    on_close=_on_ws_close,
                )
                ws_thread = threading.Thread(
                    target=ws.run_forever,
                    kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}},
                    daemon=True,
                )
                ws_thread.start()
                time.sleep(0.5)  # 等连接建立
            except Exception:
                logger.debug("WebSocket 连接失败，使用 REST 兜底", exc_info=True)

        # ── REST 兜底：查 session ──
        try:
            resp = requests.get(
                f"{base_url}/lol-champ-select/v1/session",
                headers=headers, verify=False, timeout=3
            )
            if resp.status_code == 200:
                try:
                    session = resp.json()
                except Exception:
                    session = None
                if session and _has_players(session):
                    if not mstate["in_champ_select"]:
                        logger.info("REST: 检测到进入英雄选择!")
                        # 进入英雄选择时立即获取段位和队列信息（不阻塞主流程）
                        try:
                            if not lcu_conn.get("ranks_fetched"):
                                _try_fetch_ranks(lcu_conn, headers, base_url)
                        except Exception as e:
                            logger.debug("获取段位失败: %s", e)
                        try:
                            q_info = _fetch_queue_info(headers, base_url)
                            if q_info:
                                lcu_conn["queue_id"] = q_info["queue_id"]
                                lcu_conn["queue_name"] = q_info["queue_name"]
                                lcu_conn["queue_key"] = q_info["queue_key"]
                                logger.info("模式: %s", q_info["queue_name"])
                        except Exception as e:
                            logger.debug("获取队列信息失败: %s", e)
                    _apply_session(mstate, session, on_session_parsed_cb)
                else:
                    if mstate["in_champ_select"]:
                        logger.info("REST: Session 变空，退出英雄选择")
                    mstate["in_champ_select"] = False
                    mstate["recommendations"] = []
                    lcu_conn["_cs_restart"] = True
            elif resp.status_code == 404:
                if mstate["in_champ_select"]:
                    logger.info("REST: 退出英雄选择 (404)")
                mstate["in_champ_select"] = False
                mstate["recommendations"] = []
        except requests.exceptions.SSLError:
            _cached_lcu["found"] = False
            mstate["connected"] = False
            lcu_conn["active"] = False
        except requests.exceptions.ConnectionError:
            _cached_lcu["found"] = False
            mstate["connected"] = False
            lcu_conn["active"] = False
        except Exception:
            if not was_connected:
                logger.debug("REST 请求异常", exc_info=True)

        # ── REST: gameflow phase + lobby queue + ranks ──
        if lcu_conn.get("active"):
            phase = _fetch_gameflow_phase(headers, base_url)
            if phase:
                prev = mstate.get("gameflow_phase", "")
                if phase != prev:
                    logger.info("Gameflow: %s → %s", prev or "(初始)", phase)
                mstate["gameflow_phase"] = phase
            else:
                mstate["gameflow_phase"] = ""

            # Periodically refresh lobby/gameflow queue info
            if poll_count % 5 == 0:
                q_info = _fetch_queue_info(headers, base_url)
                if q_info:
                    prev_q = lcu_conn.get("queue_name", "")
                    lcu_conn["queue_id"] = q_info["queue_id"]
                    lcu_conn["queue_name"] = q_info["queue_name"]
                    lcu_conn["queue_key"] = q_info["queue_key"]
                    if q_info["queue_name"] != prev_q:
                        logger.info("模式: %s", q_info["queue_name"])

            # Fetch ranks once after connection
            if not lcu_conn.get("ranks_fetched"):
                _try_fetch_ranks(lcu_conn, headers, base_url)

        was_connected = mstate["connected"]
        time.sleep(POLL_INTERVAL)
