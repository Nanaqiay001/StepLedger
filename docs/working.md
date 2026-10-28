# StepLedger — Working Log

## Changelog

### 2026-10-28

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
