# StepLedger — 测试策略

本文件定义"什么算验证完成"。（pytest 全过）。

## 核心原则

管线（collect → judge → render）的测试优先级：

1. **契约测试最重要** — 每一层的输出必须满足下一层的输入契约
2. **冒烟测试保底线** — 全管线端到端跑通 = 系统可用
3. **单模块测试按需加** — 逻辑复杂时才为单个模块写细粒度测试

## 测试分层

### Layer 1: 冒烟测试（最高优先级）

- `tests/test_pipeline.py` — 端到端：固定素材 fixture → stub 判断 → 控制台渲染 → 断言按日期归档
- 每次提交必过，跑不通 = 不能合

### Layer 2: 契约测试

验证层间数据正确传递：

| 契约 | 验证什么 |
|------|----------|
| collect → judge | 素材目录存在、至少一个文件可读、路径带当天日期 |
| judge → render | `Judgment` 的 `summary` / `advice` 非空，且不是纯数字罗列 |
| render → 用户 | 产物写入 `archive/YYYY-MM-DD/`，或控制台有非空输出 |

### Layer 3: 单模块测试（按需）

随模块实现复杂度增长再补，不预设。典型场景：
- 判断层边界条件（无素材、素材乱码、超长素材）
- 采集层落盘路径与重名处理
- 配置读取的默认值和类型转换

## 当前测试清单

```bash
.venv/bin/python -m pytest        # 默认跳过 integration
.venv/bin/python scripts/privacy_scan.py
```

| 文件 | 覆盖 |
|------|------|
| `tests/test_pipeline.py` | 端到端、前三行可读、judgment 契约、同日幂等、无素材、自然语言素材、降级、分层续跑 |
| `tests/test_collect.py` | 文本/文件/目录投递、哈希去重、不支持格式跳过 |
| `tests/test_judge.py` | stub 口味、空素材、响应解析、缺 key 失败 |
| `tests/test_render.py` | 报告首三行、进度条、里程碑历史、降级标注、缺档案 |
| `tests/test_profile.py` | 金额解析（万/k/逗号）、字段解析、模板创建 |
| `tests/test_privacy.py` | 仓库隐私扫描零匹配 |

## CI（GitHub Actions）

配置在 `.github/workflows/ci.yml`，触发条件：任意分支 push、PR、手动触发。

| Job | 内容 | 失败意味着 |
|-----|------|-----------|
| `pytest / Python 3.11–3.14` | `python -m pytest`（默认排除 integration） | 有测试没过 |
| `隐私扫描` | `python scripts/privacy_scan.py` | 仓库里混进了凭证 / 私人信息 / 本机路径 |
| `安装冒烟` | `pip install .` 后用 `step-ledger` 跑完整管线，断言归档产物存在 | 打包配置或入口坏了 |

CI 只用 `actions/checkout` + `actions/setup-python`，不跑 uv：流水线要验的是
「干净检出 + 纯 pytest」，本机的 uv 安装姿势不参与。integration 测试需要真实 key，不进 CI。

## Integration tests（依赖凭证，opt-in）

- 标记 `@pytest.mark.integration`，默认不跑
- CI 中通过 `pytest -m integration` 单独触发
- 需要真实 API key 的测试从 `.env` 读取

## 测试数据

- 固定素材 fixture 放 `tests/fixtures/`，按场景分目录（正常日、只有支出日、空素材日等）
- 素材用纯文本 / markdown，贴近真实输入
- AI 输出不做精确匹配，只验结构完整性 + 必填字段非空 + 不是空话套话

## 隐私验证（公开仓库强制）

- 发布前运行隐私扫描脚本
- 检查项：无真实 API key、无私人联系方式、无内部路径
- 零匹配才算通过
