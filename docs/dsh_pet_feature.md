# DSH-Pet 集成渲染层 Feature 设计与架构文档

## 概述与核心原则

`dsh-pet` 是 StepLedger 渲染层（Render Layer）的扩展渠道。

**渲染层核心原则**：
> 渲染层只负责“呈现”，**不做任何 AI 推理，不调用任何 LLM API**。

DshPetChannel 负责把 `Judgment`（总结、建议、存钱进度）组装成给 DeepSeek Harness (dsh) 的提示词并写入归档文件 `archive/YYYY-MM-DD/dsh_prompt.md`；并可选地通过 `dsh-ai-bridge` HTTP POST 接口投递至常驻 DSH 会话，由常驻 Agent 消费并调用 `pet_say` 工具驱动桌宠表达。

**前提假设**：
- 用户已常驻运行 DSH 会话，并已安装启用桌宠插件（如注册了 `pet_say` 工具的桌宠）；
- 投递为可选增强：未配置 `DSH_BRIDGE_TOKEN` 时，渠道自动退化为“仅产出提示词文件”。

---

## 核心流程与架构

```
Judgment (summary, advice, progress)
                       │
                       ▼
             DshPetChannel.render()
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
    归档 dsh_prompt.md     dsh-ai-bridge HTTP POST
  (archive/YYYY-MM-DD/)  (DSH_BRIDGE_TOKEN 配置时)
             │                   │
             └─────────┬─────────┘
                       ▼
        返回 RenderResult (稳妥降级)
     (不阻止网络失败，不中断 pipeline)
```

---

## 配置说明

在 `.env` 或环境变量中配置：

```env
# 渲染渠道启用 dsh-pet
RENDER_CHANNELS=console,dsh-pet

# DSH AI Bridge 配置
DSH_BRIDGE_URL=http://127.0.0.1:8000/api/ai-bridge/post
DSH_BRIDGE_TOKEN=your-dsh-bridge-token
```

- **`DSH_BRIDGE_URL`**：桥接端点，默认 `http://127.0.0.1:8000/api/ai-bridge/post`；
- **`DSH_BRIDGE_TOKEN`**：桥接令牌。未配置时跳过投递，日志输出提示，归档文件依然稳妥产出。

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
然后调用 pet_say 工具，让桌宠说出这句话（参数：{ text, mood? }，建议 mood：happy、worried 或 neutral；若当前环境或工具不支持所给 mood 参数则可忽略）。
```

### 2. `pet.md` (人类可读摘要)

`archive/YYYY-MM-DD/pet.md` 仅提取 `Judgment` 原始信息，不包含任何 AI 伪造的动作或情绪字段。
