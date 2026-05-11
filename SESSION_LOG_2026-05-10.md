# 2026-05-10 开发日志 — 个人对局数据系统

## 概述

设计并实现了完整的个人对局数据采集与统计系统，涵盖本地 SQLite 存储、LCU API 数据拉取、多人数据汇总。

## 核心发现

- **LCU Timeline 端点** `/lol-match-history/v1/matches/{gameId}/timeline` 直接提供全部 10 人逐分钟 frame 数据（totalGold/CS/XP/level），无需 Riot API Key
- **LCU 对局列表端点** 只返回 1 个参与者，需额外调用 `/lol-match-history/v1/games/{gameId}` 详情端点获取全部 10 人数据

## 新增文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `match_collector.py` | ~400 | SQLite 5表建表 + 对局采集 + Timeline 采集 |
| `stats_engine.py` | ~310 | 5类统计查询 + 匿名 JSON 导出 |
| `stats_export.py` | ~95 | 7天提醒弹窗 + mailto 一键发邮件 |
| `stats_merge.py` | ~195 | 多人 JSON 加权合并为 global_stats.json |

## 修改文件

| 文件 | 改动 |
|------|------|
| `lcu.py` | +110行: fetch_match_list, fetch_match_detail, fetch_match_timeline, extract_10min_stats, detect_game_end, _on_game_end |
| `recommender.py` | +65行: 双维度克制（对局影响评分 + 对线仅展示），全局+个人双数据源 |
| `engine.py` | +10行: predict_matchups 三级数据源（个人>=5 > lolalytics > 50%） |
| `lcu_runner.py` | +25行: 启动初始化 DB + 加载 global_stats + 状态卡显示 |

## 数据库设计

5 张表：matches, participants, timeline_snapshots, collected_games, current_account
索引：(game_id), (champion_id, normalized_role), (champion_id, normalized_role, win)

## 克制判定标准

### 对线克制（10min数据，不影响评分）
经济差 +/-300/500, 补刀差 +/-10/15, 经验差 +/-140/280，取最差指标

### 对局克制（胜率，影响评分）
保守阈值：54%/56%/58%。

### 置信度
5-14场 30% 权重, 15-29场 50%, 30+场 70%, <5场退回内置矩阵

## 多人数据共享

导出 → 邮件发送至 y3493627922@outlook.com → Claude 执行 stats_merge.py 合并 → 分发 global_stats.json

## 已修复的 Bug

1. recommender.py `ek` 变量作用域错误 — 移入 for 循环内
2. gameflow 对局结束检测漏检 — 添加 `_was_in_champ_select` 兜底
3. 对局列表只返回 1 个参与者 — 改用详情端点逐局拉取

## 待验证

- 下次启动 lcu_runner.py 验证完整 10 人数据采集
- Timeline 数据是否能正常获取
