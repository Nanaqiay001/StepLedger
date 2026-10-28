---
name: StepLedger
description: >
  把每天的收支素材变成一句有温度的复盘：采集落盘 → 定性判断（最近花销总结 + 理财建议，仅供参考）→ 可视化归档。
  当用户想记账/复盘开销、问"最近钱花得怎么样"、想设置每日理财提醒，
  或需要实现、修改、排查 StepLedger 管线时触发。
---

# StepLedger — Skill

## 类型与适用场景

- **类型**: Workflow
- **适用场景**: 用户想记录/复盘开销、问"最近钱花得怎么样"、想设置每日理财提醒；或需要实现、修改、排查本项目管线时
- **创建日期**: 2026-10-28

## 目标

给定一个收支素材，自动完成：读取该素材内用户的收支以及余额 → 让 AI 结合目标综合评估最近开支是否合理，离目标还有多远 → 归档当天情况与描述。归档连成视觉编年史。

**设计取向：定性，不定量。** 不追求算准、不追求分类齐全；要的是"最近花钱什么感觉"和"下一步可以怎么调"。判断仅供参考，但必须有温度、说人话。

## 验收标准

一个无上下文的 agent 拿到以下标准即可判断任务是否完成：

1. 产出物落盘：当天日期目录下同时存在 **总结图表** 以及 **目标里程碑** 文档，且已更新。
2. 产出内容可合理对应最近时间段的真实近况。
3. 读完能说出"最近钱花得怎么样"和"明天想怎么调"，且不觉得是在被审计。
4. 全程无人值守即可完成。

## 可用资源与边界

### 可用资源

- `materials/profile.md` — 目标 / 当前存款 / 偏好，跨天状态的单一事实源
- `materials/YYYY-MM-DD/` — 当天素材（账单、截图、随手记、转发消息）
- `COLLECT_SOURCE_DIRS` 指向的自动素材夹 — 快捷指令等一直往里写，跑采集时自动收当天那份
- `archive/YYYY-MM-DD/` — 判断结果、daily prompt 与渲染产物
- `.env` — provider、模型、目录等配置（`.env.example` 为 fake 占位）

### 边界

- 只做定性判断：不做精确对账、不做预算超支判定、不出损益表
- 建议仅供参考，不构成投资 / 税务 / 法律建议
- 不碰资金：不转账、不支付、不代填任何金融表单
- 凭证只走 `.env`，公开仓库零匹配

## 素材投递（collect）

把一段话或一个文件落成当天素材，不触发判断：

```bash
python scripts/daily_run.py --stage collect --text "午饭 35，打车 22"
python scripts/daily_run.py --stage collect --file ~/Downloads/bill.md
```

- 素材落 `materials/YYYY-MM-DD/`，文件名带内容哈希，同一天重复投递不会产生副本
- 只收 `.md` / `.txt` / `.csv` / `.json` 等文本；图片等暂跳过，并在结果里注明

### 自动素材夹（快捷指令 → iCloud）

快捷指令每天把银行短信/记账写进一个文件夹（文件名常用 `YYYYMMDD`），把它配成自动素材夹，
每次跑管线就会自动收当天那份：

```bash
# .env（gitignored）里写一行；多个素材夹用逗号分隔
COLLECT_SOURCE_DIRS=~/Library/Mobile Documents/com~apple~CloudDocs/<素材夹名>

python scripts/daily_run.py --stage collect          # 自动收当天素材
python scripts/daily_run.py --stage collect --source ~/Downloads/bill-inbox  # 临时换一个
```

- 归属日期优先看文件名里的 `20261028` / `2026-10-28`，没有才看修改时间；只收当天
- 同一份源文件当天被追加内容时，`materials/` 里只保留**最新快照**（原文件名覆盖），
  不会因为内容变了就多出一份副本，也不会把同一笔算两遍
- 素材夹不存在或当天没素材，只在 `skipped` 里注明，不中断管线，也不编造内容

## 判断（judge）

读当天素材 + `materials/profile.md`，产出 `summary` / `advice`，归档 `prompt.md` 与 `judgment.json`：

```bash
python scripts/daily_run.py --stage judge
python scripts/daily_run.py --stage judge --provider openai
```

- 默认 `JUDGE_PROVIDER=stub`：本地模板，可离线、不花钱
- `openai` 走任意 OpenAI 兼容网关（`JUDGE_BASE_URL`）；失败时自动降级到模板，并在产物里标「降级模式」
- `prompt.md` 必须归档，排查时先看它

## step-ledger run（one-shot，供 crontab）

### 调度归属

skill 不会自己定时，它只能被调用：

| 职责 | 归属 |
|------|------|
| 知道"每天该做什么" | 本 skill |
| 决定"什么时候做" | 宿主 agent 的定时 / 心跳能力 |
| 无常驻 agent 时的兜底 | `scripts/daily_run.py` + crontab |

### 首次安装：注册每日任务（必须）

第一次被调用时，先把这件事做完，再跑管线：

1. 问用户每天几点提醒；没指定就用 `PIPELINE_DAILY_RUN_TIME`（默认 21:00）
2. 宿主有定时能力 → 注册一条每日任务："调用 StepLedger 跑今天的判断"
3. 宿主没有定时能力 → 告知用户，并给出下面的 crontab 兜底

> 我可以每天 21:00 帮你复盘一下最近的收支，顺便看看离目标还有多远。要现在设置吗？

### 每天被调用时做什么

1. 读 `materials/profile.md`；没有就轻问一句，别做成问卷
2. 收当天素材；用户没给就主动问"今天有要记的吗"
3. 跑采集 → 判断 → 渲染，归档到日期目录
4. 用对话口吻说结果，并留一个可调整的点

执行体（agent 调用与 cron 共用同一条管线）：

```bash
# 完整一次
python scripts/daily_run.py --text "午饭 35，打车 22"
python scripts/daily_run.py --file ~/Downloads/bill.md

# 只重跑某一层
python scripts/daily_run.py --stage judge
python scripts/daily_run.py --stage render

# 给 agent 自己解析的结构化结果
python scripts/daily_run.py --json --no-echo
```

### 定时任务与日志调试（workspace）

```bash
# crontab -e
0 21 * * * cd /path/to/StepLedger && .venv/bin/python scripts/daily_run.py >> /tmp/step-ledger.log 2>&1
```

- 先手动跑通一遍，再挂 crontab
- 排查顺序：`/tmp/step-ledger.log` → `materials/YYYY-MM-DD/` 有没有素材 → `archive/YYYY-MM-DD/` 有没有产物
- 同一天重复执行必须幂等，不产生第二个日期目录

## step-ledger display（本地图直显）

终端直显（console channel）：把当天的判断结果渲染成人话，供 agent 直接转述或在本地查看。图形化渲染（图片 / 网页）留待后续渠道补充。

## 方法论建议（非硬约束）

- 管线：采集（只落盘）→ 判断（总结 + 建议）→ 渲染（可视化 + 归档）
- 层间以文件为界：采集层的产物是素材文件夹，判断层的输入就是它
- 判断层输入不要只认目录路径，允许 agent 直接把一段自然语言素材传进来
- 长期状态放 `materials/profile.md`，两种入口共读同一份
- 两个入口（agent 调用 / cron）必须同一管线、产物一致

## 降级行为（必须覆盖）

- 当天无素材：不编造，写一句"今天没有记录"，仍归档
- AI 不可用：用固定语气模板输出，并标注"降级模式"
- `profile.md` 缺失：按默认目标（100 万）继续，并轻问一句
- 素材无法解析：跳过该文件，在归档里注明跳过原因
- 渲染失败：至少落一份纯文本 summary
- 同日重复调用：覆盖当天产物，不新建目录

## 输出规格

```
materials/YYYY-MM-DD/        # 当天素材
archive/YYYY-MM-DD/
├── prompt.md                # 当天 prompt（必须归档）
├── judgment.json            # summary / advice
├── report.md                # 总结图表 / 渲染产物
└── milestones.md            # 目标里程碑（累计进度）
```

- `judgment.json` 的 `summary` 与 `advice` 均非空
- 渲染产物前三行内说清"最近怎么样、下一步怎么走"
- 不出现真实姓名、卡号、电话；不确定就脱敏

## 已知陷阱

- 别把"定性"做成"精确记账"：不输出对账表格、预算红线、分类饼图
- 别把建议写成命令，也不制造焦虑
- 别假设一定有常驻 agent：cron 兜底必须可用
- 别在不同入口写两套逻辑，产物必须一致
- 别把凭证或真实账单提交进仓库
