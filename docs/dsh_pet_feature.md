# DSH-Pet 集成渲染层 Feature 设计与架构文档

## 概述与核心原则

`dsh-pet` 是 StepLedger 渲染层（Render Layer）的扩展渠道。

**渲染层核心原则**：
> 渲染层只负责“呈现”，**不做任何 AI 推理，不调用任何 LLM API**。

DshPetChannel 作为一个纯粹的“提示词与复盘产出渠道”，把 `Judgment`（总结、建议、存钱进度）组装成一段给 DeepSeek Harness (dsh) 的提示词并写入文件 `archive/YYYY-MM-DD/dsh_prompt.md`。由 dsh 侧消费并注入 Agent 会话，Agent 处理后调用 `pet_say` 工具驱动桌宠表达。

---

## 核心流程与架构

```
Judgment (summary, advice, progress)
                       │
                       ▼
             DshPetChannel.render()
                       │
                       ▼
             生成 dsh 提示词 (Prompt)
                       │
                       ▼
        落盘归档文件 (archive/YYYY-MM-DD/)
        ├── dsh_prompt.md  (供 dsh / Agent 消费)
        └── pet.md         (复盘摘要)
                       │
                       ▼
           控制台直显 (echo=True)
  "提示词已产出到 dsh_prompt.md，等待 dsh 消费"
```

---

## 产物契约 (Artifact Contract)

### 1. `dsh_prompt.md` (供 dsh / Agent 消费)

生成的 `archive/YYYY-MM-DD/dsh_prompt.md` 包含结构清晰的复盘数据与给 Agent 的明确指令：

```markdown
【StepLedger 每日复盘】
日期：2026-10-28
总结：今日工资到账 18000 元，支出较少。
建议：顺手把一小笔挪到存款账户中。
进度：1.8% (当前存款: 18,000 / 目标: 1,000,000)

请根据以上内容，用一句话向用户播报今日复盘要点，语气轻松口语化。
然后调用 pet_say 工具，让桌宠说出这句话（参数：{ text, mood? }）；mood 可根据进度或复盘结论选择 happy、worried 或 neutral。
```

### 2. `pet.md` (人类可读摘要)

`archive/YYYY-MM-DD/pet.md` 仅提取 `Judgment` 原始信息，不包含任何 AI 伪造的动作或情绪字段。

---

## 渲染管道配置

在 `.env` 或环境变量中添加：

```env
RENDER_CHANNELS=console,dsh-pet
```

当 `RENDER_CHANNELS` 包含 `dsh-pet`（或 `dsh_pet` / `pet`）时，Pipeline 会自动触发 `DshPetChannel`，且无需配置任何 API key。
