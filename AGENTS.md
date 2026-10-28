# AGENTS.md — StepLedger 项目规则

## 这个项目是什么

StepLedger跬步账：把各方的收支素材收进来，由 AI 做一次有温度的**定性**判断（最近花销总结 + 理财建议），再渲染成一眼能看懂的东西，最后攒成 100 万编年史。管线：采集 → 判断 → 渲染。完整设计见 `docs/prd.md` 和 `docs/rfc.md`。

**设计取向：定性，不定量。** 不做精确对账、不做预算管控；判断仅供参考，但必须有温度、说人话。

**最终形态：一个 agent 的 skill。** 项目以 skill 交付（`SKILL.md` + 配套脚本/模块），对外接口是 skill 触发 + 自然语言输入，不是独立 CLI。**调度归宿主 agent**（它负责每天调用），`scripts/` + cron 只是没有常驻 agent 时的兜底；两种入口必须走同一条管线，产物一致。


## 项目结构

- `docs/` — prd / rfc / test / working（持久文档）
- `.github/workflows/` — CI 门禁（pytest 矩阵 / 隐私扫描 / 安装冒烟）
- `src/step_ledger/` — 可复用 Python 模块
- `scripts/` — 供 agent / cron 调用的执行入口
- `tests/` — unit（offline）/ integration（opt-in）
- `skills/` — 本项目的根 skill 文件（公开技术实现）
- `materials/` `archive/` — 运行时产物（gitignored）

## 硬约束

- **公开仓库。** 私有联系人/路由/凭证/内部路径不进仓库。凭证走 `.env`（gitignored）+ `.env.example`（fake 占位）。发布前跑隐私扫描，零匹配才算过。

## 工作要求

1. 有意义的改动后更新 `docs/working.md`（`## Changelog` 当天一节 + `## Lessons Learned`）。
2. 小步提交，不要把脚手架、实现、验证塞进一个 commit。
3. Python 环境：激活 workspace 根 `.venv`，依赖用 `uv pip install`。需要隔离时在本项目建独立 `.venv`。
4. daily prompt 是必须归档的中间产物，和输出一起存当天日期目录。
5. 大道至简，摒弃复杂设计以及冗余实现。