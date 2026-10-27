---
name: StepLedger
description: >
  StepLedger（跬步账）四阶段管线的技术实现 Skill。
  覆盖 collect → synthesize → render → display 全流程，
  包括数据源适配器、AI Provider 对接、输出渠道和 cron 编排。
  当需要实现或修改管线中任何阶段的代码时触发此 Skill。
---

# StepLedger — 技术实现 Skill

## 总体管线

```mermaid
sequenceDiagram
    participant DS as 📥 数据源<br/>AliPay / WeChat / 手动
    participant C as 🔍 采集 Collect
    participant S as 🧠 理解 Synthesize
    participant R as ✨ 生成 Render
    participant D as 📤 输出 Display

    DS->>C: 原始账单 / 消息
    activate C
    C->>S: RawTransaction[]
    deactivate C
    activate S
    Note over S: 聚合近况 + 目标对比
    S->>R: FinancialContext
    deactivate S
    activate R
    Note over R: AI 场景 Prompt
    R->>D: Insight (文本/图片)
    deactivate R
    activate D
    D->>D: 展示 + 归档 → DisplayResult
    deactivate D
```

## 扩展模式

- **数据源**：在 `collect/adapters/` 下新增适配器，继承 `BaseAdapter`
- **AI Provider**：在 `render/providers/` 下新增 provider，继承 `BaseProvider`
- **输出渠道**：在 `display/channels/` 下新增渠道，继承 `BaseChannel`

## 运行入口

- `scripts/daily_run.py` — cron 每日触发入口
- 手动调试：`python -m step_ledger.pipeline`

## 关键约束

1. 凭证走 `.env`，不进仓库
2. daily prompt 和输出归档到 `archive/YYYY-MM-DD/` 目录
3. 每个阶段可独立替换和测试
