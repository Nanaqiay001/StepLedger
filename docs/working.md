# StepLedger — Working Log

## Changelog

### 2026-11-04
- **设计文档：判断层扩展为「秘书」（草案 v2，待讨论）**。新增 `docs/feature-judge-secretary.md`：
  管线仍是三层，判断层内部变成 `观察（LLM）→ 计算（代码）→ 统计趋势（代码）→ 说话（LLM）`。
  「本月已花 / 今日额度 / 明天该多少」仍由代码算，但算在判断层里，`Judgment.facts` 携带，
  渲染层不再 `glob` 历史。三条规则：只有判断层读 `archive/`、只有 `facts.py` 算钱、
  只有代码写数（模型可以看错，不能改数）。观测靠「正文摘录必须能在素材里找到」做机械核验，
  不用正则、也不让模型当裁判。补跑不变量：`history` 只接受 `<= 当天`
- **废弃上一版四层提案**（`collect → facts → judge → render`）：多一个新包、一个新 stage、
  一套新 ctx 和一层兼容，收益只是「渲染不读 archive」，违背大道至简，文档已删除
- **报告增加当月累计 + 本月可花**：`render/monthly.py` 用「月初前最后一个余额 − 当前余额」
  算本月已花；可花不是手填预算，而是倒推出来的：
  `月收入 − (每月需存 − 公积金月缴存) = 本月最多能花`，再减已花得到「还能花」，
  为负就写「已超 ¥X」——目的就是别出现资金缺口
- 自动转存按支出算（用户确认的口径），不再在行里挂「含自动转存」的免责说明
- **每日节奏也进报告**：把本月可花摊到每一天，`累计允许 = 可花 × 第几天 ÷ 当月天数`、
  `结余 = 累计允许 − 已花`；超了就让明天降到 `(可花 − 已花) ÷ 剩余天数` 匀回来，
  本月额度用完则直接说「已超」。报告多一行：
  `今日额度 ¥103（30 天均摊）｜今天花了 ¥85｜结余 ¥88，明天照 ¥106`
- **这些数字一律由代码算，不交给模型**：额度、超没超、明天该多少都是确定性算术，
  模型只负责把它说成人话（简报里给的是算好的数，它不改数）。钱上的四舍五入交给 LLM 等于埋雷
- 测试 109 项全过（新增 3 项：日额度与明日额度、超支与额度用完、单日净流出）
- 不逐条加总短信的「支取」：笔笔攒有时单独成条、有时并进余额差，重复推送还会把同一笔算两遍；
  余额差是干净的，代价是它含自动转存出去的那部分，所以口径写清楚、不假装是纯消费
- 月初没有余额快照时（比如那天没跑管线），标注「X 起算」，不硬凑一个基线
- 隐私扫描改成只看 `git ls-files` 的产物：本地临时目录（图表工具生成物、浏览器 profile）本来
  就不会进仓库，扫它们只会让 `pytest` 莫名其妙变红
- 测试 106 项全过（新增 7 项：跨月基线、缺基线、可花倒推、缺收入不瞎算、超支标记、报告行、扫描范围）

### 2026-11-02
- **口径修正：那笔固定小额是「笔笔攒」，不是订阅**。判断层把每天重复出现的同额小额读成
  "反复扣费"，10-31 甚至建议"先停掉"——方向正好相反：那是自动存钱工具，每花一笔就转一笔到
  余额宝，是存钱动作。短信只写「支取」，模型推不出用途，口径必须由档案提供
- 新增档案字段 `约定：`（`materials/profile.md` 里一行一条），`build_prompt` 把它单列成
  「我的约定（按我的口径解读，别自己推断）」段落；没有约定时 prompt 与原来逐字一致。
  偏好继续管语气，约定管"这笔钱怎么算"
- 实测：档案里写清那笔小额「算存钱不算花销」，prompt 里原样出现，判断不再把它当花销
- 测试 84 项全过（新增 2 个 prompt 用例）
- **约定升级为可解析**：`约定：键 = 值` 进 `Profile.agreements`，纯文字约定进 `Profile.notes`；
  两者都进 prompt，但只有结构化的能被代码用。第一个结构化约定是 `目标日期 = YYYY-MM`：
  报告和 prompt 会给出「还剩 N 个月、每月要存多少（不计收益）」
- 于是每天那句话可以对着节奏说，而不是只说"最近怎么样"；`目标日期` 缺失或已过期时整段不出现，
  老档案的输出一个字节都不变
- 顺手做了隐私清理：仓库里的示例流水换成通用的假数字（真实金额只留在 gitignored 的
  `materials/profile.md` 里）；测试用 100 万 / 20 万这种量级示例
- 测试 89 项全过（新增 5 项：约定拆分、目标倒推、两个缺省、报告与 prompt 的日期行）
- **余额趋势图**：渲染层新增 `render/trend.py`，把各日 `judgment.json` 的 `meta.balance` 拼成序列，
  落 `trend.svg`（W3C 矢量图）+ `trend.csv`；自然日补空、缺口断开，当天没读到余额就不算数据点
- 先写了字符画版本，虽然能用但换台机器字体一动就歪；改成标准 SVG 后坐标是精确值，
  也能直接在浏览器/预览器里看，CSV 还能丢进任何表格工具重画。不引图表库：matplotlib 要装
  几十 MB 和中文字体，CI 上装字体是新的挂点
- 只画卡内余额、不画"每天花了多少"：从短信拆支出会撞上笔笔攒（有时单独成条、有时并进余额差），
  硬算时对时错；余额差是干净的，也不受存款口径改动影响
- 测试 97 项全过（新增 8 项：缺口、补空、窗口裁剪、断开不连线、CSV 两列、空数据）
- **验证码不再出海**：采集把银行短信整条落盘，其中混着一次性验证码；当晚那条就随 prompt
  发给了模型。现在 `read_materials` 在发出去之前逐行摘掉 `验证码 / 校验码 / 动态码 / 切勿…告知`
  这类行——素材原样留在盘上，只是不离开本机
- 删掉未入库的 `docs/feature-judge-history.md` 草案（含真实余额快照，且功能未决定要做）
- 测试 99 项全过（新增 2 项：口令行摘除、盘上原文保留）

### 2026-10-30
- **设计文档：判断层历史回望（草案，待讨论）**。新增 `docs/feature-judge-history.md`：
  判断层读 `archive/*/judgment.json`，按近三天 / 近一周 / 编年史三层拼进 prompt，
  把判断单位从「今天」换成「最近」，缓解 21:00 半日快照被写成全天结论；
  只动 judge + prompt，不改管线顺序 / collect / render。
  核心边界写清楚：历史能改口径，不能补 21:00 后的交易；不让模型填精确报表，
  数字由管线给、模型只负责叙述；补数据另议
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
- **事故复盘：11:39 那次运行对着测试素材写了总结**。iCloud 里没有 `20261030.txt`，`FolderAdapter`
  按日期匹配到 0 份（报 `中银纪录: 没有 2026-10-30 的素材`，但没打到终端），当天唯一素材是前一天
  手动试投的一份测试文本（`manual-<哈希>.md`），于是那几句演示用的流水被当成真账汇报给用户
- 修三处：① 空素材不调模型——`_judge` 在 0 份素材时直接走 stub 模板并标 `meta.provider = "none"`，
  不再把空 prompt 发给模型；② `main()` 普通输出打一行采集小结（`采集：共 0 份素材；中银纪录: 没有 …`），
  `--json` 时 stdout 仍只有 JSON；③ 删掉那份测试素材，并把「手动投递一律用假日期 + 临时 root」写进 Lessons
- 顺带清掉 `archive/2026-10-30/` 里那份基于假数据生成的 `pet_task.md`，重跑后当天的 `judgment.json`
  变成诚实的「今天没有记录」，桌宠静默（`render.log` 记 `今天没有素材，跳过播报`）
- **已知缺口（明确不修）**：10-29 有 3 笔（132.40 / 16.00 / 25.20）但那天没跑过管线，
  采集只认当天日期、不补历史，所以这三笔不入账本；补账方案需动 `run()` 编排，先不做

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

- **定时任务里的「当天素材」往往只是「截至运行时刻的素材」**。判断层若把快照当全天，
  就会用半天的数据下全天的结论；先改口径（最近三天 / 一周），再谈补数据。历史回望能让
  单日截断不主导结论，但补不出 21:00 之后真实发生的交易——这两件事要分开说。
- 脚手架、实现、验证应分步提交，不要一次塞太多。
- 层的边界最好落在"文件"上：素材异构、来源不固定，内存强类型会逼着过早统一格式。
- 先定口味再定结构：定性还是定量决定了要不要分类报表、预算阈值这些模块。
- **「顺手算一下」会慢慢长出一个没名字的层**。余额趋势、当月累计、可花倒推、每日节奏，
  每次都是在渲染层加十几行，因为那里手边正好有 `archive_dir`；四个 PR 之后渲染层就多出了
  一个事实层。判断标准：如果这个数**算错就是 bug、且判断层也想看**，它就不属于排版层；
  但「不属于排版层」不等于「要单独开一层」——它属于**想看它的那一层**，所以进判断层。
  另一个判据：**只要一个数字会被模型拿来说话，就不该排在模型后面算。**
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
- **LLM 管线里最贵的错误是「0 输入却有输出」**。采集空手而归时，模型不会说"我没料"，它会写出一段
  听起来很合理的总结。所以采集层必须自证（打印"共 N 份素材 + 跳过了什么"），空输入必须短路到模板，
  两件事都要有测试盯住，否则错误会一路穿过判断、渲染，最后以"有温度的口吻"送到用户面前。
- **测试素材绝不能落进真实日期目录**。`materials/<日期>/` 的设计含义就是"那天的真相"，代码无法区分
  测试和真实数据——只能靠不写进去。手动投递一律 `--date 2026-01-01 --root /tmp/xxx`，别用今天。
- **别让 agent 用"没看见"来兜底**。这次不是模型错、不是采集错，是跑完没人看采集报告就写了结论。
  凡是有"静默跳过"的路径（0 素材、渠道未配置、匹配不到文件），都要在正常输出里留一行，别只写进 log。
- **「支取」不等于「花销」**。代扣、自动转存、充值、笔笔攒都长得像支出，短信里只有金额和"支取"两个字，
  模型只能照着"花了钱"去解读，而且会越说越自信（"像是同一种小额扣费反复在走"）。用户的口径（这笔钱
  算什么）必须能写进档案并进 prompt——语气偏好和事实约定分开，别都塞进「偏好」。
- 记住这条教训的实践形式：**给用户留一个能一句话改口径的入口**，比事后纠正模型的推断便宜得多。
