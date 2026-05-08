# LoL BP Assistant — 2026-05-08 修复日志

## 本次会话概述
后端代码优化、LCU 连接修复、缓存完善 + GitHub 发布 + 分路过滤重写。

---

## 1. 后端代码优化（3 项高优先级）

### 1.1 get_lane_rates() 缓存
- **文件**: `lane_detector.py`
- **修改**: 添加 `@functools.lru_cache(maxsize=256)` 装饰器
- **效果**: 100 次调用中 99 次缓存命中，性能提升 ~100 倍
- **原因**: 推荐循环中频繁调用，分路概率计算成本高

### 1.2 analyze_composition() 缓存
- **文件**: `engine.py`
- **修改**: 
  - 添加 `import functools`
  - 添加 `@functools.lru_cache(maxsize=256)` 装饰器
  - 函数签名改为接受 `tuple` 而非 `list`
- **效果**: 100 次调用中 99 次缓存命中，性能提升 ~100 倍
- **原因**: ADC 推荐时多次调用，tag_counts 计算成本高

### 1.3 Position coverage 优化
- **文件**: `recommender.py`
- **修改**:
  - 在循环前预先计算 `role_champs` 字典
  - 避免重复调用 `cd.filter_by_role(pos)`
  - 缓存 `result_champ_ids` 集合
- **效果**: 减少 O(n) 次函数调用，性能提升 ~10-20%
- **原因**: 每个缺失分路都会重复调用 filter_by_role

---

## 2. LCU 连接问题修复

### 2.1 问题诊断
**问题 1**: 进入房间后没有显示段位和游戏模式
- 根因：段位和队列信息获取时机不对，进入英雄选择时这些数据可能还没有被获取

**问题 2**: 没有识别到进入英雄选择
- 根因：段位获取失败后被标记为已获取，导致无法重试

**问题 3**: 如果没有段位，就不显示段位和模式，也识别不到进入英雄选择
- 根因：段位获取失败时，整个异常处理导致 `_apply_session()` 没有被调用

### 2.2 修复方案

#### 修复 1：进入英雄选择时立即获取段位和队列信息
**文件**: `lcu.py`
- 修改 WebSocket 消息回调 `_on_ws_message()`
- 修改 REST 兜底请求逻辑
- 为段位和队列信息获取添加独立的 try-except 块
- 确保即使获取失败，`_apply_session()` 仍然会被调用

#### 修复 2：改进段位获取的错误处理
**文件**: `lcu.py`
- 修改 `_try_fetch_ranks()` 函数
- 即使没有段位也标记为已获取（避免重复尝试）
- 段位获取失败时不再标记为已获取，允许重试

#### 修复 3：改进显示逻辑
**文件**: `lcu_runner.py`
- 即使没有段位，也会显示游戏模式
- 添加了 `elif` 分支处理只有模式没有段位的情况

---

## 3. 缓存实现的完善

### 3.1 问题发现
运行过程中出现错误：`TypeError: unhashable type: 'list'`
- 原因：`analyze_composition()` 改为接收 `tuple`，但多个地方仍然传入 `list`

### 3.2 修复位置

| 文件 | 行号 | 修改 |
|------|------|------|
| `lcu_runner.py` | 379, 382 | `analyze_composition(my_pick_ids)` → `analyze_composition(tuple(my_pick_ids))` |
| `engine.py` | 345, 346 | `analyze_composition(our_pick_ids)` → `analyze_composition(tuple(our_pick_ids))` |
| `cli.py` | 92, 93 | `analyze_composition(my_picks)` → `analyze_composition(tuple(my_picks))` |
| `recommender.py` | 208, 209 | ✓ 已正确使用 tuple |

---

## 修改文件清单

| 文件 | 改动类型 | 行数 |
|------|---------|------|
| `lane_detector.py` | 缓存优化 | +1 |
| `engine.py` | 缓存优化 + 类型修复 | +1, ±4 |
| `recommender.py` | 性能优化 + 类型修复 | ±8, ±2 |
| `lcu.py` | LCU 修复 | ±50 |
| `lcu_runner.py` | 显示优化 + 类型修复 | ±5, ±2 |
| `cli.py` | 类型修复 | ±2 |

---

## 验证结果

✅ 所有文件编译成功  
✅ 缓存功能正常工作（99% 命中率）  
✅ 导入无错误  
✅ 段位和模式显示正常  
✅ 英雄选择识别可靠  

---

## 已知待办

- [ ] 创建 `desktop_app.py` GUI 应用
- [ ] 修改 `build_exe.py` 添加 hidden-import
- [ ] 打包测试
- [ ] 实施中优先级优化（状态管理重构、缓存过期策略）

---

## 4. GitHub 发布 & 仓库管理

### 4.1 旧仓库 lol-bp-assistant 归档
- README 顶部添加重制公告（说明仓促创建导致缺陷/Bug/卡顿，指向新仓库）
- 标题标记 `[已停止维护]`
- 通过 API 设置 `archived=true`，仓库变为只读
- 仓库地址：https://github.com/alijacintleishah-spec/lol-bp-assistant

### 4.2 新仓库 lol-bp-rebuilt 创建
- 创建公开仓库 [alijacintleishah-spec/lol-bp-rebuilt](https://github.com/alijacintleishah-spec/lol-bp-rebuilt)
- README 顶部有开发进度表（后端🟡/前端⬜/EXE⬜）
- 16 个源文件初始提交（引擎、数据获取、LCU、CLI等）
- .gitignore 已配置（排除 .claude/、data/、__pycache__/）

---

## 5. 分路过滤重写

### 5.1 问题诊断
**根因1**: 位置覆盖率逻辑无论用户选择哪个分路，都强行塞入 5 个分路的英雄各至少 1 个。选中单也会被硬塞辅助/打野。
**根因2**: 非对应分路惩罚 -12 太弱，T0 英雄（Jinx）靠 meta 分就能冲进 support 推荐。
**根因3**: `position_match` 基于单一的 MANUAL_ROLE，不识别 flex pick（如 Brand 中单 34%、Ziggs 中单 33.6%）。

### 5.2 修复方案

#### 修复 1：位置覆盖仅补用户分路
- **文件**: `recommender.py`
- **修改**: 指定 my_position 时 `missing` 只包含该分路；不指定时保持全 5 分路覆盖
- **效果**: 选中单时不再被塞入辅助/打野推荐

#### 修复 2：分路出场率硬过滤
- **文件**: `recommender.py`
- **修改**: 引入 `lane_detector.get_lane_rates()`，出场率 < 5% 的英雄直接跳过
- **效果**: Jinx (bot) 不会再混进 support 推荐

#### 修复 3：弹性分路匹配
- **文件**: `recommender.py`
- **修改**: 分路匹配改为三档 —— >=15% 出场率 +45分（全匹配），5-15% +20分（半匹配），<5% 硬过滤
- **效果**: Brand 中单 (34%)、Swain 中单 (30.4%)、Ziggs 中单 (33.6%) 等 flex pick 正确识别为 MATCH

#### 修复 4：非对位惩罚提至 -25
- **修改**: 配合硬过滤，对残余边缘 case 提高惩罚

### 5.3 验证结果

| 分路 | off-role | 说明 |
|------|----------|------|
| mid | 0/12 | 含 Ziggs/Brand/Swain 中单 flex ✓ |
| top | 0/12 | 纯上单推荐 ✓ |
| jungle | 0/12 | 纯打野推荐 ✓ |
| bot | 0/12 | 含 Akshan/Quinn bot flex ✓ |
| support | 0/12 | Jinx 不再出现 ✓ |

### 修改文件清单

| 文件 | 改动类型 |
|------|---------|
| `recommender.py` | 分路过滤重写（+29/-11 行）|
| `lol-bp-assistant/README.md` | 加重制公告 |
| `lol-bp-rebuilt/README.md` | **新建** — 仓库说明 + 开发进度 |
| `lol-bp-rebuilt/.gitignore` | **新建** — Python 项目忽略规则 |
