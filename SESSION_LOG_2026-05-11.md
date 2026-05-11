# 2026-05-11 开发日志 — 数据源重构：移除 lolalytics，全面接入 OP.GG

## 概述

删除 lolalytics_scraper.py，将其符文/技能缓存功能迁入 tencent_fetcher.py，并对位预测和推荐引擎全面接入 OP.GG 实时克制数据。

## 变更详情

### 1. lolalytics_scraper.py — 删除

该文件实质是空壳：
- `get_runes()` / `get_spells()` 内部已走腾讯 101 数据，lolalytics 仅做缓存
- `get_matchup()` 只读本地缓存，实际爬取从未成功，永远返回 None

功能迁移至 tencent_fetcher.py（缓存包装）和 meta_fetcher.py（克制数据）。

### 2. meta_fetcher.py — 新增 OP.GG 克制数据系统

基于 `lol_get_champion_analysis` MCP API：
- **strong_counters**: 克制我方的英雄（我方胜率 < 50%）
- **weak_counters**: 我方克制的英雄（我方胜率 > 50%）
- **per-position counters**: 分路对位克制数据

关键技术问题及解决：
- **Locale 不一致**: zh_CN 和 en_US 下 `strong_counters`/`weak_counters` 列表顺序互换，类名也变化。改用 `win/play` 独立比率与 API `wr` 字段比对，鲁棒判定 counter 类型
- **Champion 名称**: Data Dragon `get_name()` 返回中文名，API 需要英文 key。改用 `champions[key]["dd_id"]` 获取英文名
- **缓存策略**: `data/opgg_counters/{champion_id}.json`，48 小时过期

### 3. engine.py — 对位预测三级数据源

`predict_matchups()` solo lane 和 2v2 bottom:
1. 个人统计 (≥5 场) — `stats_engine.get_counter_matchup_stats()`
2. **OP.GG 实时数据** (≥50 场) — `meta_fetcher.get_opgg_matchup()`
3. 内置 TAG_COUNTER_MATRIX — `champion_data.get_counter_score()`

### 4. recommender.py — 推荐评分新增 OP.GG 维度

新增 `_build_opgg_counter_map()` 预加载敌方英雄 OP.GG 数据，在评分循环中追加 OP.GG 克制加成（±15 上限），与个人统计、TAG_COUNTER_MATRIX 并行。

### 5. tencent_fetcher.py — 迁入缓存包装函数

从 lolalytics_scraper 迁入 `get_runes()` / `get_spells()` 缓存包装：
- 一级：腾讯 101 champion detail API
- 二级：本地 `runes.json` / `summoner_spells.json` 缓存

### 6. build_exe.py — 移除 lolalytics hidden import

## 数据源最终分工

| 数据 | 来源 |
|------|------|
| 英雄强度 / Tier / 胜率 / 禁用率 | OP.GG `lol_list_lane_meta_champions` |
| 分路分布 | 内置 `lane_distribution.json` |
| 克制关系 (对位预测) | OP.GG `lol_get_champion_analysis` → 内置矩阵 |
| 克制关系 (推荐评分) | 个人统计 + TAG_COUNTER_MATRIX + OP.GG 加成 |
| 符文 / 技能 | 腾讯 101 CDN (`game.gtimg.cn`) |
| 英雄基础数据 | Data Dragon |

## 文件变更统计

| 文件 | 操作 | 行数变化 |
|------|------|---------|
| `lolalytics_scraper.py` | 删除 | -272 |
| `meta_fetcher.py` | 新增 OP.GG counter 系统 | +180 |
| `engine.py` | 修改数据源引用 | +12/-10 |
| `recommender.py` | 新增 OP.GG 评分维度 | +40 |
| `tencent_fetcher.py` | 迁入缓存包装函数 | +100 |
| `build_exe.py` | 移除 hidden import | -1 |

净变化: ~+60 行，删除 1 文件，功能从 0 → 完整 OP.GG 克制数据集成
