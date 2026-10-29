# DSH-Pet 集成渲染层 Feature 设计与架构文档

## 概述

`dsh-pet` 是 StepLedger 渲染层（Render Layer）的全新扩展渠道，旨在将每日财务复盘结果（`Judgment`）通过 DeepSeek Harness (DSH) 桌宠插件（如 `dsh-aemeath-pet`）的互动形态展现给用户。

通过该渠道，系统能够根据每日的花销总结、理财建议和存钱进度：
1. **生成 DSH 交互 Prompt**：构建面向 DeepSeek Harness 桌宠的专属 Prompt；
2. **调用 API 生成桌面宠物状态**：使用项目已配置的 AI API（或模型适配器）将复盘定性解读转化为桌宠的动作（`action`）、情绪（`mood`）和气泡台词（`bubble_text`）；
3. **降级与本地兜底**：当 API 不可用或模型降级时，基于规则矩阵输出兜底状态；
4. **归档与终端直显**：落盘 `pet_status.json` 与 `pet.md` 到 `archive/YYYY-MM-DD/`，并在控制台中以桌宠视觉卡片输出。

---

## 核心流程与架构

```
Judgment (summary, advice, progress, degraded)
                       │
                       ▼
             DshPetChannel.render()
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
    生成 DSH Pet Prompt    判断 API 可用性
             │                   │
             └─────────┬─────────┘
                       ▼
           调用 Provider / API 解读
       (失败/离线时降级到规则匹配引擎)
                       │
                       ▼
        生成 Pet Status (action, mood, bubble)
                       │
           ┌───────────┴───────────┐
           ▼                       ▼
    落盘归档文件             控制台卡片直显
 archive/YYYY-MM-DD/
 ├── pet_status.json
 └── pet.md
```

---

## 数据契约 (Data Contract)

### 1. `pet_status.json` Schema

归档文件 `archive/YYYY-MM-DD/pet_status.json` 包含如下字段：

```json
{
  "date": "2026-10-28",
  "pet_name": "Aemeath",
  "mood": "happy",
  "action": "jumping",
  "bubble_text": "今天工资到账太给力啦！继续保持，离100万又近了一步✨",
  "prompt": "...",
  "progress": {
    "target": 1000000,
    "savings": 18000,
    "distance": 982000,
    "percent": 0.018
  },
  "degraded": false
}
```

### 2. 状态与动作映射 (Action & Mood Mapping)

| 场景 / 复盘类型 | 情绪 (`mood`) | 桌宠动作 (`action`) | 经典台词提示 |
| :--- | :--- | :--- | :--- |
| **收入增加 / 进度提升明显** | `happy` | `jumping` (跳跃庆祝) | "太棒啦！财富小木屋又盖高了一层✨" |
| **常规日常 / 平稳无大额消费** | `normal` | `idle` / `running` (待机/工作) | "今天过得很平稳呢，继续小步前进～" |
| **开销过大 / 冲动消费** | `worried` | `failed` / `thinking` (沉思/沮丧) | "今天口袋稍微瘦了一点点，明天要注意哦～" |
| **首日建档 / 重大里程碑** | `celebrating` | `jumping` (跳跃) | "欢迎来到跬步账，一起朝100万出发吧！" |
| **AI 降级模式 (Degraded)** | `thinking` | `thinking` (思考) | "系统稍微打了个瞌睡，不过记录都已经收好啦！" |

---

## DeepSeek Harness Prompt 设计

面向 AI Provider / DSH API 调用的 Prompt 结构如下：

```markdown
你是 DeepSeek Harness 桌宠（Aemeath），正在陪伴主人的每日理财复盘。

今天（{date}）的理财分析如下：
- 总结：{summary}
- 建议：{advice}
- 存钱进度：{progress_percent}%（存款：{savings} / 目标：{target}）
- 降级状态：{degraded}

请以桌宠轻快、有温度、说人话且鼓励主人的口气，输出符合 JSON 格式的桌宠响应：
{
  "mood": "happy|normal|worried|celebrating|thinking",
  "action": "jumping|running|thinking|failed|idle",
  "bubble_text": "简短的一两句气泡台词（30字以内）"
}
```

---

## 渲染管道配置

在 `.env` 或环境变量中添加：

```env
RENDER_CHANNELS=console,dsh-pet
```

当 `RENDER_CHANNELS` 包含 `dsh-pet`（或 `dsh_pet`）时，Pipeline 会自动触发 `DshPetChannel`。
