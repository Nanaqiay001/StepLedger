# StepLedger — Working Log

## Changelog

### 2026-10-28
- **DeepSeek Harness (DSH) 桌宠渲染层集成（`dsh-pet` 重构为纯提示词渠道）**：
  - 恪守“渲染层只负责呈现，不做 AI 推理，不调用 LLM API”的架构原则；
  - 重构 `DshPetChannel`：移除 LLM API 调用与规则匹配逻辑，专注于将 `Judgment` 组装为包含 `pet_say` 工具调用指令的提示词文件；
  - 导出产物：生成 `archive/YYYY-MM-DD/dsh_prompt.md` 供 dsh / Agent 消费，以及 `pet.md` 归档文件；
  - 可观测性提升：在 `pipeline.py` 的渲染异常处理中记录详细异常类型与 Traceback 堆栈；
  - 在 `src/step_ledger/pipeline.py` 中注册 `dsh-pet` 渠道，无任何 API Key 依赖；
  - 更新文档 (`docs/dsh_pet_feature.md`) 与测试套件 (`tests/test_dsh_pet.py`)，全量测试无缝通过。
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

- 职责分离原则：渲染层仅负责呈现与结构化提示词生成，解耦 LLM 推理与具体 UI/桌宠驱动逻辑，保持渲染渠道纯粹、离线可靠且零网络成本。
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
