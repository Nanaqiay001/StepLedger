# StepLedger — Working Log

## Changelog

### 2026-10-30
- **实测 dsh-pet 0.3.8，修订播报方案（feature v2）**：完整走通 `lock → broadcast → anim → playback → release`，
  宠物真的说了话、动画真的播满 10 秒；同时踩到三个坑并写进文档：
  `surface` 必填且必须等于该宠物的 `display`（用 `any` 会让动画 0.5 秒后被 `superseded`）、
  `/playback?wait=ended` 的 `timeout` 上限 10000（写 15000 直接 `bad-request`）、
  一段动画正好约 10 秒所以等不到 `ended`，需 `timeout=9000` + 再等 1.5 秒
- 修正 v1 的错误假设：「播报不需要回读 `/state`」是错的。现在验收改为读回
  `say.data.text` 与 `lock.data.locked`——只断言文件生成会写出假测试
- 明确「render 不调 LLM ≠ render 不能有 socket」：本渠道允许向本机 dsh-pet 发 HTTP，
  但禁止任何模型调用；播报成功与否以读回 `/state` 为准
- 排查 PR#2 结论：它依赖的 `dsh-ai-bridge`（:8000）与 `pet_say` 工具在 DSH 与 dsh-pet 中都不存在，
  跑完宠物一句话没说（`say.counter` 前后不变）；61 项测试全过但测的是虚构契约
- 顺带发现一个与本 PR 无关的问题（只记录、不处理）：同一天重跑时，若傍晚模型调不通而降级到 stub，
  会用模板话覆盖掉当天上午正常生成的 `judgment.json`。修法涉及判断层策略，另开 issue，不塞进这个 PR
- **实现桌宠渠道 `pet`**：新增 `render/channels/pet.py`（约 240 行，标准库 urllib），
  `pipeline._render` 加一行注册，`config.py` 加 `PET_BASE_URL` / `PET_ID` / `PET_ANIM_TIERS`，
  `.env.example` 补三行；管线其余部分零改动，不配 `PET_BASE_URL` 时零网络请求
- 端到端抓到一个单测抓不到的 bug：等回执的长轮询要挂 9 秒，而统一 1.5s 的 HTTP 超时必然先超时，
  结果是动画播 1.5 秒就被"释放锁"顶掉。修法是长轮询单次放宽到 `wait + 1s`，并加回归断言
- 真实 dsh-pet 验证：30% 进度时 `/state` 的 `anim` 叶子出现 `余额-数金皱眉`，`say` 文本与发出的一致，
  跑完 `lock.locked == false`；`PET_ANIM_TIERS=off` 时整条渲染 0.08 秒
- 测试 70 项全过，隐私扫描零匹配
- **改成 agent 驱动（v3）**：`pet` 渠道不再自己发 HTTP，改为产出 `archive/<日期>/pet_task.md`
  （事实 + 可发挥空间 + 命令）；台词、动画、表情包由宿主 agent 决定，机械层收进
  `scripts/pet_play.py`（surface/锁/投喂/点播/回执/释放/读回），另有 `--list` 与 `--auto` 兜底
- 这样随机性与语气不再由模板决定：实测同一份判断，按进度该播「余额-数金皱眉」，
  agent 改挑「收红包」并自己写了一句，`/state` 读回一致、`anim.name` 正确、锁已释放
- 代价明确：没有 agent 读简报时宠物不说话，cron 场景要用 `pet_play.py --auto`
- 测试 74 项全过（新增 20 个桌宠用例），隐私扫描零匹配
- **无人值守收口**：空素材日 `pet` 渠道静默跳过（不写简报、不播报），定时任务 prompt 里
  去掉「先问我要不要补记」，明确不向用户提问——每天 21:00 跑完只留一句结论
- **防「每天同一句」**：简报里的播报命令删掉示例台词（照抄示例就是固定文案）；
  简报按日期在 7 种口吻里轮换，并列出前几天的台词；`pet_play.py` 每次播报追加
  `archive/<日期>/pet_said.md`，次日简报会读到——实测「关心」口吻那句已出现在下一条简报的「最近说过」
- 明确宠物的 LLM 边界：`/whisper`、`/chat` 走模型（与 DSH 同账号同额度），`/broadcast` 不生成、零 token；
  宠物聊天是独立 5 轮记忆、无工具、无反向通道，做不到"跟宠物说话来控制 agent"
- **定时任务实测**：`.env` 只有 `RENDER_CHANNELS=console,pet`、没写 `PET_BASE_URL` 时，pet 渠道会静默跳过
  （只在 `render.log` 留一行），播报链路等于没接上；本机地址已补进 `.env`，DSH 端口变了要跟着改

### 2026-10-29
- **设计文档：桌宠播报渠道（未实现，待审阅）**。新增 `docs/feature-pet-channel.md`：
  复用 dsh-pet 的 `/lock → /broadcast → /anim → /playback(wait) → /release` 把当天判断送到桌宠气泡，
  按目标完成度选档位动画；`RENDER_CHANNELS=console,pet` 才启用，未配 `PET_BASE_URL` 静默跳过
- 实测过本机 dsh-pet 通道：`GET /dsh-pet-7340/state` 返回 200、`pets.main` 在、锁为空闲，
  端点与字段按 `openapi.yaml` 核对过，无需改 dsh-pet
- RFC 只做最小扩展：架构图加一条「可选外部呈现」边，当前实现状态加一条待办 + 指向 feature 文档；
  渲染层的概念（渠道职责、管线兜底）一律不动，避免 PR 外溢到架构重构
- 渠道独立的约束写进 feature 文档而不是 RFC：本渠道只读 `Judgment` + `RenderContext`，
  不读别人的产物、也不要求 `console` 先跑；顺序只影响体验，不影响正确性
- 未动任何实现代码：`src/`、`scripts/`、`tests/` 与 `.env.example` 保持原样

### 2026-10-28
- README 第三轮：删掉「三步上手」整节，示例下方的两行运行说明也一并去掉（示例自解释）；
  uv 作为可选 runner 回归，「接真模型」并进管线一节，README 收在 5 节 70 行
- README 命令统一成 `uv run --no-project scripts/daily_run.py ...`：跨平台、不用纠结
  `python3` / `py`，`--no-project` 必须带（不带会去装项目依赖 `pytest`，离线直接失败）
- 去掉 `run` 外壳脚本（bash，Windows 不可用），入口统一成 `python3 scripts/daily_run.py`；
  README 里的示例、stage 命令、开发命令一并改掉，并注一行「Windows 上把 `python3` 换成 `py`」
- README 第二轮瘦身（126 → 79 行）：tagline + 一段真实输出版本先行，之后才是「三步上手」；
  mermaid 从 5 参与者的时序图换成 3 节点流程图，「设计取向 / 快速开始 / 产物 / 文档」四节合并，
  投递方式表、uv 坑、profile 兜底等细节下沉到 `skills/StepLedger.md` 与代码注释
- **CI 门禁**：新增 `.github/workflows/ci.yml`，push / PR / 手动触发，三个 job——
  pytest 矩阵（Python 3.11–3.14）、隐私扫描、安装冒烟（`pip install .` 后用 `step-ledger` 跑完整管线）
- 本地按 CI 场景验证：干净检出复制副本里 45 项测试全过、隐私扫描零匹配；全新 venv 安装后入口能产出 `report.md`
- README 加 CI 徽章与门禁说明，`docs/test.md` 补 CI 一节，AGENTS.md 项目结构加 `.github/workflows/`

- **下一阶段实现：MVP 管线跑通**（采集 → 判断 → 渲染）
- 新增 `pyproject.toml`（hatchling + `step-ledger` 入口 + pytest 配置），零运行时依赖
- `shared/`：`types.py`（Judgment / CollectResult / RenderContext / RenderResult / PipelineResult）、`config.py`（`.env` 轻量读取 + 默认值）、`profile.py`（目标 / 存款 / 偏好解析，缺文件写模板）
- `collect/`：`BaseAdapter` + `ManualAdapter`（一段文字 / 文件 / 目录 → `materials/YYYY-MM-DD/`，文件名带内容哈希，重复投递不产生副本）
- `judge/`：`BaseProvider`、共用 prompt 构建与响应解析、`StubProvider`（本地语气模板）、`OpenAICompatibleProvider`（urllib 直连任意兼容网关）
- 判断失败 / 未配 key 自动降级到 stub，并在 `judgment.json` 与 `report.md` 标注「降级模式」
- `render/`：`BaseChannel` + `ConsoleChannel`（`report.md` 前三行说清现状与下一步、`milestones.md` 从历史 judgment 汇总进度）
- `pipeline.py`：`run()` 支持 `--stage collect|judge|render` 单独重跑；同日覆盖、不新建目录；prompt 必归档
- 入口：`scripts/daily_run.py`（cron 兜底，自动把 `src` 加入 path）、`python -m step_ledger`、安装后的 `step-ledger`
- `scripts/privacy_scan.py`：API key / 手机号 / 邮箱 / 本机路径 / `.env` 误提交检查
- 测试：`test_pipeline` / `test_collect` / `test_judge` / `test_render` / `test_profile` / `test_privacy`，36 项全过；隐私扫描零匹配
- `.env.example` 增加 `JUDGE_BASE_URL`
- 自动素材夹：`FolderAdapter` 按日期（文件名 `20261028` / `2026-10-28`，否则文件修改时间）只收当天文件；
  `COLLECT_SOURCE_DIRS`（逗号分隔）+ `--source` 接入管线，与手动投递落同一个 `materials/YYYY-MM-DD/`
- 修复：快捷指令当天追加内容会让同一源文件产生多份快照，模型把同一笔算两遍；
  素材夹改为按原文件名覆盖当天最新快照，并清掉旧 `原名-哈希` 副本
- 真实模型（DeepSeek `deepseek-flash`）端到端跑通：素材 1 份、`degraded=false`，判断内容与账单对得上
- `judgment.json` 的 `meta.usage` 记录 token 用量，方便核对计费
- 存款兜底：`profile.md` 没填「当前存款」时，用模型从素材里读到的 `balance` 补进进度快照，
  报告标注「AI 从素材识别」；手填仍优先（档案是单一事实源）。不用正则硬编码匹配短信格式
- 新增 `./run`：`PYTHONPATH=src uv run --no-project python -m step_ledger`，绕开 uv 的
  可编辑安装 / 本地 wheel 缓存问题，改完代码立刻生效
- 测试 53 项（含 `test_balance.py`）
- 采集层抽出 `store_file` / `material_files`，手动与素材夹共用「原名-内容哈希」落盘，两个来源都幂等
- 新增 `tests/test_source_folder.py`（只收当天 / 幂等 / 日期回退 / 缺目录 / 配置与覆盖），47 项全过
- `.env.example` 增加 `COLLECT_SOURCE_DIRS`（留空 = 只用手动投递）
- 文档同步：README 快速开始改为实际可用命令、RFC 勾掉实现清单、test.md 补测试清单、skill 填上 collect/judge/运行命令

- 脚手架重构：管线调整为 采集 → 判断 → 渲染（原为四阶段：collect → synthesize → render → display）
- 采集层改为以素材文件（夹）为产物，判断层直接以素材目录为输入
- 判断层输出收敛为「最近花销总结 + 理财建议」，明确仅供参考
- 产品哲学重申：定性优先、不求定量、有温度
- 同步更新 prd / rfc / test / README / skills/StepLedger.md / AGENTS.md
- 明确最终形态为 **agent 的 skill**：对外接口是 skill 触发，`scripts/` 只是执行体，cron 为可选包装
- 厘清调度归属：**skill 定流程，宿主 agent 定时间**，cron 降为无常驻 agent 时的兜底
- skill 新增「首次安装：注册每日任务（必须）」与「每天被调用时做什么」两节
- skill 的 description 改为面向真实使用场景触发（记账复盘、理财提醒），不再只限"改管线代码"
- 新增 `materials/profile.md` 作为长期状态（目标 / 存款 / 偏好）的单一事实源
- 归档目录约定拆分为 `materials/YYYY-MM-DD/`（素材）与 `archive/YYYY-MM-DD/`（判断 + 产物）
- 拉取远端 `9d4020e`（skill 骨架重构），以骨架为准填入内容；`Collector CLI` / `Synthesize CLI` 两节留空待写
- 修正骨架验收标准序号（原为 1/2/4），补回 `name` / `description` frontmatter 以保证可触发

### 2026-10-27

- 初始化项目脚手架：目录结构、文档骨架、环境配置
- 填充 AGENTS.md 项目规则
- 填充 .gitignore（Python 项目规则）
- 填充 .env.example（fake 占位值）
- 填充 README.md（管线概览 + 快速开始）
- 填充 docs/prd.md（产品需求文档）
- 填充 docs/rfc.md（架构设计文档 — 四阶段管线）
- 填充 docs/test.md（测试策略）
- 填充 skills/StepLedger.md（Skill 定义）

## Lessons Learned

- 脚手架、实现、验证应分步提交，不要一次塞太多。
- 层的边界最好落在"文件"上：素材异构、来源不固定，内存强类型会逼着过早统一格式。
- 先定口味再定结构：定性还是定量决定了要不要分类报表、预算阈值这些模块。
- uv 0.10.11 的 editable 安装会写 `_editable_impl_*.pth`（下划线开头），CPython 3.13+ 的
  `site.py` 会跳过隐藏 `.pth`，导致 `uv pip install -e .` 后 `import step_ledger` 失败。
  规避：用 `uv pip install .`（非可编辑）或 `PYTHONPATH=src`；pytest 里已配 `pythonpath = ["src"]`。
- 本机直连 PyPI 失败时，用 `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`。
- 层间以文件为界后，测试可以直接断言归档产物，不需要 mock 层与层之间的调用。
- 快捷指令写素材夹这件事，最好让「归属哪一天」由文件名决定（`YYYYMMDD`）：文件系统时间会被同步/拷贝改掉，
  改天补跑时按 mtime 分天会把昨天的账算进今天。
- iCloud 这类个人路径只放 `.env`（gitignored），仓库里只出现 `~/Library/.../<素材夹名>` 这种占位写法。
- CI 不复用本机 uv 流程：uv editable 在 3.13+ 的隐藏 `.pth` 坑只影响开发机，流水线用
  `setup-python + pip` 验「干净检出 + 纯 pytest」更稳；公开仓库的隐私扫描 pytest 里有一份、CI 里再单列一个 job，
  前者让开发者本地就能发现，后者让发布门禁在 Actions 页面一眼可见。
- 接外部进程前先**实测它的接口**，别照 README 的功能列表写设计：dsh-pet 的档位动画看着像"余额越低越惨"，
  但它的档位是"已用百分比"，与"目标完成度"方向相反——直接复用 `events.balance` 会天天播错情绪。
  设计文档里把这类"名字对得上、语义对不上"的点逐条写出来，审阅时才好否。
- 投喂类渠道（桌宠、通知、音箱）的价值在"有人看见"，所以它必须**可失败、可跳过、不落产物**；
  一旦让它写归档或调模型，它就会从锦上添花变成管线的又一个故障点。
- **验收要写"用户看得见的结果"，不能写"文件生成了"**。PR#2 的 61 项测试全绿，因为每条断言都在验
  「`dsh_prompt.md` 被写出」；但没有一条验「宠物说了话」，于是 `pet_say`、`dsh-ai-bridge` 这些
  根本不存在的接口一路绿灯合进了代码。能读回状态的系统（`/state`、数据库、页面）一定读回来断言。
- **接口假设本身就是风险**。给 agent 的指令里如果出现没验证过的 API 名（`pet_say`、`ctx.pet.announce()`），
  agent 会把它当契约去实现，还会顺手发明一个中间人把它接上。指令里写"先实测/先读官方契约"比写"照这个结构做"更省事。
