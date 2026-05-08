# LoL BP Assistant Rebuilt

> **🚧 重构中 | Work in Progress — 当前不可用**
>
> | 模块 | 状态 |
> |------|------|
> | 后端核心引擎 | 🟡 开发中 |
> | Web 前端 | ⬜ 未开始 |
> | 桌面 EXE 打包 | ⬜ 未开始 |
>
> 稳定版本请使用旧仓库 **[lol-bp-assistant v1.x](https://github.com/alijacintleishah-spec/lol-bp-assistant)**

LoL 排位赛 BP 辅助工具重制版。全新架构，整合三方数据源（腾讯 101 + OP.GG + Data Dragon），支持段位自适应推荐。

## 与 v1 的主要区别

- **三数据源融合**：腾讯 101 官方数据 + OP.GG 实时胜率 + Data Dragon 静态数据
- **段位自适应**：根据玩家段位调整推荐权重（低分段更看重 counter，高分段更看重 meta）
- **LCU 独立进程**：LCU 连接与推荐引擎分离，避免 UI 卡顿
- **模块化架构**：引擎/数据/UI 三层分离，易于维护和扩展

## 技术栈

- **后端**: Python 3.11+
- **前端**: 待定（计划 Web 界面）
- **数据源**: 腾讯 101 API, OP.GG, Data Dragon, Lolalytics

## 项目结构

```
lol-bp-rebuilt/
├── engine.py              # 推荐评分引擎
├── recommender.py         # 推荐决策层
├── champion_data.py       # 英雄数据模型
├── meta_fetcher.py        # OP.GG 元数据获取
├── tencent_fetcher.py     # 腾讯 101 数据获取
├── lolalytics_scraper.py  # Lolalytics 数据爬取
├── lcu.py                 # LCU 客户端连接核心
├── lcu_runner.py          # LCU 独立进程入口
├── lane_detector.py       # 分路检测
├── cli.py                 # 命令行接口
├── build_exe.py           # EXE 打包脚本
└── data/                  # 缓存数据
```

## 开发计划

1. ✅ 后端引擎核心逻辑
2. 🔄 数据源整合与验证
3. ⬜ CLI 端到端可用
4. ⬜ Web 前端界面
5. ⬜ EXE 打包与自动更新
6. ⬜ 集成测试与性能优化
