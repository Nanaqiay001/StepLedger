# AGENTS.md — StepLedger 项目规则

## 这个项目是什么

StepLedger跬步账：每天通过收支记录采集，由 AI 每日解读收支是否偏离目标，让你每天离小目标近一点，最后赞成100万编年史。完整设计见 `docs/prd.md` 和 `docs/rfc.md`。


## 项目结构

- `docs/` — prd / rfc / test / working（持久文档）
- `src/step_ledger/` — 可复用 Python 模块
- `scripts/` — 面向人和 cron 的可执行入口
- `tests/` — unit（offline）/ integration（opt-in）
- `skills/` — 本项目的根 skill 文件（公开技术实现）

## 硬约束

- **公开仓库。** 私有联系人/路由/凭证/内部路径不进仓库。凭证走 `.env`（gitignored）+ `.env.example`（fake 占位）。发布前跑隐私扫描，零匹配才算过。

## 工作要求

1. 有意义的改动后更新 `docs/working.md`（`## Changelog` 当天一节 + `## Lessons Learned`）。
2. 小步提交，不要把脚手架、实现、验证塞进一个 commit。
3. Python 环境：激活 workspace 根 `.venv`，依赖用 `uv pip install`。需要隔离时在本项目建独立 `.venv`。
4. daily prompt 是必须归档的中间产物，和输出一起存当天日期目录。
5. 大道至简，摒弃复杂设计以及冗余实现。