# StepLedger — 测试策略

本文件定义"什么算验证完成"。（pytest 全过）。

## 核心原则

管线四阶段（collect → synthesize → render → display）的测试优先级：

1. **契约测试最重要** — 每个阶段的输出必须满足下一阶段的输入契约
2. **冒烟测试保底线** — 全管线端到端跑通 = 系统可用
3. **单模块测试按需加** — 逻辑复杂时才为单个模块写细粒度测试

## 测试分层

### Layer 1: 冒烟测试（最高优先级）

- `tests/test_pipeline.py` — 全管线端到端：stub 数据源 → 聚合 → stub AI → 控制台输出
- 每次提交必过，跑不通 = 不能合

### Layer 2: 契约测试

验证阶段间数据类型正确传递：

| 契约 | 验证什么 |
|------|----------|
| collect → synthesize | `collect()` 输出的每条记录符合 `RawTransaction` 结构 |
| synthesize → render | `synthesize()` 输出符合 `FinancialContext` 结构 |
| render → display | `render()` 输出符合 `Insight` 结构 |

### Layer 3: 单模块测试（按需）

随模块实现复杂度增长再补，不预设。典型场景：
- 聚合逻辑的边界条件（零交易、跨日、大额判定）
- 配置读取的默认值和类型转换

## Integration tests（依赖凭证，opt-in）

- 标记 `@pytest.mark.integration`，默认不跑
- CI 中通过 `pytest -m integration` 单独触发
- 需要真实 API key 的测试从 `.env` 读取

## 测试数据

- 固定 fixture 放 `tests/fixtures/`，用 JSON 格式
- 每个 fixture 文件对应一个场景（正常日、零收入日、大额支出日等）
- AI 输出不做精确匹配，只验结构完整性 + 必填字段非空

## 隐私验证（公开仓库强制）

- 发布前运行隐私扫描脚本
- 检查项：无真实 API key、无私人联系方式、无内部路径
- 零匹配才算通过
