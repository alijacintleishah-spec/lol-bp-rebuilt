# LoL BP Assistant — 2026-05-08 修复日志 (续)

## 本次会话概述
后端推荐逻辑修复 + 个人对局数据系统方案设计。

---

## 1. 推荐逻辑重构

### 1.1 _on_session() 推荐分支统一
- **文件**: `lcu_runner.py`
- **修改**: 合并 `self_actions` + `our_pick_actions` + `else` 三个分支为统一的 `our_pick_actions` 处理
- **效果**: 始终以当前选人者的 position 为准，不再以 `my_position` 为中心
- **移除**: enemy action 时的兜底推荐

### 1.2 Role 字段修复
- **文件**: `recommender.py`
- **修改**: result 的 `role` 字段改用 `mapped if (my_position and position_match) else role`
- **效果**: Flex pick 正确显示推荐分路而非 MANUAL_ROLE
- **初始化**: `mapped = ""` 确保变量始终有定义

### 1.3 Primary Lane 硬过滤
- **文件**: `recommender.py`
- **修改**: 硬过滤从 "lane rate >= 5%" 改为 "primary lane == 请求分路"
- **效果**: 只有主路匹配的英雄才通过，杜绝 off-role 混入
- **验证**: 5 个分路 off-role 全部为 0

---

## 2. 兜底逻辑移除

### 2.1 符文/技能
- **文件**: `lolalytics_scraper.py`
- **删除**: `_default_runes()` / `_default_spells()` / `_default_matchups()` 三个硬编码兜底函数
- **修改**: `get_runes()` / `get_spells()` 无数据时返回空列表 `[]`
- **显示**: "默认"/"Flash+TP" → "暂无推荐"

### 2.2 对位胜率
- **文件**: `engine.py`
- **修改**: `predict_matchups()` 无对位数据时返回 50.0% 均势（不再用 counter score 估算）
- **显示**: "no data"/"数据不足" → "暂无数据"

---

## 3. LCU 位置数据修复

### 3.1 "middle" → "mid" 映射
- **文件**: `lcu.py`
- **修改**: `_norm_pos()` 添加 `if pos == "middle": return "mid"`
- **根因**: LCU 返回 "MIDDLE"，但函数只处理了 "bottom"→"bot" 和 "utility"→"support"
- **影响**: 中单位置过滤失效 + 胜率预测中路显示 "?"

### 3.2 teammate_positions 参数
- **文件**: `recommender.py`
- **新增**: `teammate_positions: dict[int, str]` 可选参数
- **效果**: position fill bonus 优先用客户端 assignedPosition 而非 MANUAL_ROLE 推测
- **调用**: `lcu_runner.py` 从 `my_picks` 构建字典传入

---

## 4. 个人对局数据系统（方案设计）

### 4.1 概述
新增 `personal_stats.py` 模块，从 LCU Match History API 读取玩家对局历史，积累个人对位数据库。

### 4.2 数据结构
- **文件**: `data/personal_matchups.json`
- **核心字段**: game_id, timestamp, my_champion, my_lane, win, enemy_team(lane→champ), cs_diff_15, gold_diff_15
- **加权算法**: 30天半衰期指数衰减，5场加权为显著性阈值

### 4.3 两种克制
- **对线克制**: 同路对位，(my_champ, lane) vs (enemy_champ, same_lane)
- **全局克制**: 跨路统计，my_champ vs enemy_champ（所有路汇总）

### 4.4 集成方式
- **recommender.py 维度3**: 个人数据(40%) + 内置数据(60%) 混合
- **engine.py predict_matchups**: 优先级 个人(>=5场) > lolalytics > 均势50%
- **lcu.py**: 新增 fetch_match_list / fetch_match_details / sync_recent_matches
- **lcu_runner.py**: 启动同步 + 游戏结束自动采集 + 显示更新

### 4.5 待确认方案（已存入记忆）
1. 动态权重: 5-15场 30%, 15-30场 50%, 30场+ 70%
2. 仅排位赛 (queue_id 420/440)
3. 全局克制包含所有对位（同路+跨路），不仅限于同路

---

## 修改文件清单

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `lcu_runner.py` | 重构推荐逻辑 + 显示更新 | +8/-40 |
| `recommender.py` | role修复 + primary lane过滤 + teammate_positions | +8/-3 |
| `lolalytics_scraper.py` | 移除兜底函数 | +2/-51 |
| `engine.py` | 移除counter score兜底 + verdict中文 | +3/-6 |
| `lcu.py` | _norm_pos "middle"→"mid" | +2 |

---

## 验证结果

✅ 所有文件编译通过  
✅ 5 个分路 off-role 全部为 0  
✅ 中单推荐全部 primary=mid  
✅ "middle" → "mid" 映射正常  
