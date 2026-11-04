# 判断层扩展：把「算」交给秘书的计算器

> 状态：**已落地**（2026-11-04，PR1–PR5）。对应 issue #13。
> 取代此前「独立第四层 facts」的提案（已删除）。
> `docs/rfc.md` 的「各层职责」「层间契约」「实现备注」已同步。

## 决定：不加层

管线仍然三层：

```
collect → judge → render
```

变化全部发生在判断层内部。判断层从一个「转发素材给模型」的薄壳，变成一个有前置步骤的秘书：

```
judge = 观察（LLM） → 计算（代码） → 统计历史趋势（代码） → 说话（LLM）
```

这个顺序就是秘书的工作方式：**先查账，再算账，再翻旧账，最后说一句人话。**

## 为什么不是加一层

- **事实不是独立的生产者，是判断的前置输入。** 它是一个动作（查今天余额），不是一条业务线。给它开一层、一个 stage、一个目录、一个 ctx，成本远超收益。
- **加了层，渲染还得从两个地方取数**：`Judgment`（话）和 `facts`（数）。三层模型里 `Judgment` 一次就能把话说全，渠道不用知道事实是从哪来的。
- **三层语义本来就对**：收素材 / 想事情 / 给人看。加一层就意味着「想事情」被拆成了两半，而拆开的两半共享同一个状态（余额序列），反而要重新约定谁先谁后。
- 项目规则是「大道至简，摒弃复杂设计以及冗余实现」。上一版四层方案引入 `facts/` 包、`--stage facts`、`RenderContext` 全换、旧归档兼容层——**四个新接口换一个「渲染不读 archive」**，不划算。

## 判断层内部结构

```
judge/
├── secretary.py     # 编排：观察 → 计算 → 趋势 → 说话（唯一入口）
├── observe.py       # LLM 抽取：素材 → Observation（含原文摘录）
├── facts.py         # 纯函数：Observation + History + Profile → Facts
├── history.py       # 只读 archive，且只接受 <= 当天
├── prompt.py        # 两段 prompt 与响应解析
├── base.py          # BaseProvider：observe() + judge()
└── providers/       # openai_compatible / stub
```

数据类型（`Observation` / `Facts` / `TrendSummary`）仍住在 `shared/types.py`——它们跨层
（judge → render），按现有约定属于层间契约；`judge/` 里只放读取与计算。

`pipeline` 只调一个函数：

```python
judgment = secretary.run(materials_dir, profile, date, provider=provider)   # -> Judgment
```

`BaseProvider` 从「一个 judge()」变成「两个能力」：

```python
class BaseProvider(ABC):
    def observe(self, materials_text: str, date: str) -> Observation: ...  # 只读数字，不评价
    def speak(self, profile, materials_text, facts, trend, date) -> tuple[str, str]: ...  # 只写字
```

方法不叫 `judge()` 是为了避开层名：`judge` 是层，`observe` / `speak` 是它在模型侧的两个动作。

`StubProvider` 两个都实现（确定性，无网络），所以降级路径和正常路径走同一套结构。

## 判断层现在的四件事

### 1. 观察（LLM）

从当天素材里读出**卡内余额**，并且必须附带**原文摘录**：

```json
{
  "balance": {
    "value": 12800,
    "as_of": "2026-11-04",
    "excerpt": "于08月14日网上支付支取人民币9.53元,交易后余额12800.00【中国银行】"
  },
  "anomalies": ["另有一条验证码短信，已忽略"]
}
```

不用正则、不写格式假设：换银行、换措辞、手写素材都不用改代码。这是 LLM 该干的活。

### 2. 计算（代码）

`facts.py` 是纯函数，输入全部显式，输出 `Facts`：

```python
def compute(*, day: str, profile: Profile, observation: Observation,
            history: History, backfilled: bool = False) -> Facts: ...
```

```json
{
  "date": "2026-11-04",
  "backfilled": false,
  "balance": {"value": 12800, "as_of": "2026-11-04", "confidence": "ok"},
  "goal": {
    "target": 1000000, "savings": 200000, "savings_source": "profile",
    "distance": 800000, "percent": 0.2,
    "deadline": "2030-12", "months": 50, "per_month": 16000
  },
  "month": {
    "key": "2026-11", "baseline_date": "2026-10-31", "baseline": 19200,
    "partial": false, "spent": 6400, "spent_as_of": "2026-11-04",
    "income": 20000, "saving": 13000, "spendable": 7000,
    "left": 600, "short": false
  },
  "pace": {"days": 30, "index": 4, "quota": 233, "allowed": 933,
           "today": 100, "left": -67, "over": true, "tomorrow": 214}
}
```

`backfilled` 标记「这一天的 `goal.savings` 是补跑时手填档案的当前值，不是当日快照」，
报告里据此加一句「（档案值）」，不声称它是当天的数。

`spent_as_of` 是新增的诚实字段：当天没读到余额时，`spent` 取「上一个有余额的日子」并注明是哪天，
报告照实说「已花 ¥6,400（截至 11-03）」，**不写 0，也不假装是今天**。
若「上一个有余额的日子」早于 `baseline_date`（整个月都没有余额），则 `spent: null`、`partial: true`。

### 3. 统计历史趋势（代码）

这是这次要补的能力。秘书不该只看今天：

```python
@dataclass(frozen=True)
class TrendSummary:
    days: list[DayPoint]          # 近 14 天：日期、当天花销、额度、是否超
    week_spent: int | None        # 近 7 天
    prev_week_spent: int | None   # 前 7 天，用来算环比
    over_days: int                # 近 7 天里有几天超了
    balance_low: int | None       # 近 14 天最低余额（风险提示用）
    progress: list[ProgressPoint] # 进度历史（milestones.md 用）
```

全部由 `history` 的余额序列推出，纯代码。它同时喂给两个地方：秘书的 prompt（说话有依据）
和渲染层（趋势图 + 里程碑直接用，不用再扫 `archive/`）。
`progress` 在旧归档上从 `meta.progress` 降级读取，保证 8 天历史不断档。

### 4. 说话（LLM）

prompt 里带上已经算好的事实，模型只负责措辞：

```
## 已经算好的事实（权威，不可改，也不许自己重算）
- 本月可花 ¥7,000，已花 ¥6,400，还能花 ¥600
- 今天额度 ¥233，今天花了 ¥100，累计超了 ¥67；明天额度 ¥214
- 近 7 天花了 ¥1,850，比前 7 天多 ¥320，有 2 天超了
- 目标 100 万，还差 80 万，剩 50 个月，每月要存 16,000
```

于是「明天匀回来」这种话**第一次有可能出现**——它有了依据。而 prompt 同时明确：
数字只能用上面给的，禁止自己加总。

两段 prompt 都归档进当天的 `prompt.md`（`## 观察` / `## 说话` 两节），保持「daily prompt
必须归档」这条约束，不新增文件。

## Judgment 的形状

```python
@dataclass
class Judgment:
    summary: str                 # 模型写
    advice: str                  # 模型写
    facts: Facts                 # 代码写，唯一权威
    trend: TrendSummary          # 代码写
    observation: Observation     # 模型写（原始观测，供审计与复算）
    prompt: str = ""
    degraded: bool = False
    runtime: dict[str, Any] = field(default_factory=dict)  # provider/model/usage/skipped/degraded_reason
```

`meta` 这个名字消失。运行信息进 `runtime`，事实进 `facts`，两者不再共用一个命名空间。
`judgment.json` 就是历史的唯一载体——`history` 读它，不另设状态库。

`runtime` 的键固定为：`provider` / `model` / `usage` / `material_count` / `skipped` /
`degraded_reason` / `profile_created` / `steps`（`{"observe": "ok|stub|failed", "speak": ...}`）。
`profile_created` 和 `material_count` 是「这次运行发生了什么」，不是事实，所以留在 runtime。

### 渲染层的入参

`Judgment` 之外只剩三样东西，全部由 pipeline 组装，**不含 archive 根路径**：

```python
@dataclass
class RenderContext:
    out_dir: Path                                     # 只用于写今天的产物
    echo: bool = True
    recent_said: list[str] = field(default_factory=list)  # 桌宠专用，读的是它自己的 pet_said.md
```

渠道签名从 `render(judgment, ctx)` 不变，但 `ctx` 从 6 个字段缩到 3 个：
日期在 `facts.date`、目标在 `facts.goal`、趋势在 `trend`、进度在 `trend.progress`。
渠道再想算一个数，手上已经没有原材料了。

## 三条规则

| 规则 | 内容 | 保证方式 |
|---|---|---|
| **只有判断层读 archive** | 渲染渠道只拿 `Judgment`，不再 `glob` 历史 | 渠道只拿到 `out_dir`（写用）；守卫测试禁止 `render/` import 历史读取、也禁止对 `archive/` 做 `iterdir` / `json.load` |
| **只有代码算钱** | `facts.py` 是唯一做金额运算的地方 | 模型只产「观测」（一个数 + 原文），不产「结论」；`parse_balance` 删除 |
| **只有代码写数** | `Judgment.facts` 只由 `compute()` 赋值 | 模型可以「看错」，但不能「改数」；它的意见只能进 `observation.anomalies` |

## 观测的可信度：用「原文可寻址」代替「模型自我校验」

「这个数合理吗」没有判据，让模型再判断一次只会引入第二个不可靠源。但有一条**确定性**的检查：

1. `excerpt` 必须能在当天素材原文里找到（做空白/全半角归一后做子串匹配）
2. `value` 必须能从 `excerpt` 里读出来（去掉千分位后子串匹配）

两条都过 → `confidence: ok`；任一条不过 → `confidence: suspect`，报告标「余额待确认」。
不需要任何格式相关的正则，也不可能误伤正确数据，还能写进测试。

代价是多一次极小的模型调用（只回一个 JSON）。换来的是：`facts` 完全确定、可复现、可回放，
而且 cron 路径不需要 agent 也能算出来——**两入口产物一致**这条硬约束保住了。

## 降级矩阵

| 情形 | 观察 | 事实 | 话 | 报告 |
|---|---|---|---|---|
| 一切正常 | 余额 + 摘录 | 全量 | 模型 | 全量 |
| 素材里没有余额 | `null` | 已花取上一个有余额的日子 + `spent_as_of` | 模型 | 标「截至 X」 |
| 摘录对不上原文 | 标 `suspect` | 照算，`balance.confidence: suspect` | 模型 | 标「余额待确认」 |
| 模型不可用 | 无观测 | 只用历史 | stub | 标降级 |
| 当天 0 份素材 | 不调模型 | 只用历史 | stub | 「今天没有记录」 |
| 历史无月初基线 | — | `partial: true` | 模型 | 标「X 起算」 |

注意第二行和第四行：**降级路径现在也有权威数字**。今天 stub 写的话里一个金额都没有，
因为它拿不到；改造后它至少有目标、已花和额度。

## 补跑语义

`history` 的每个方法都带 `upto=day`，`compute()` 拿不到「今天」这个概念：

```python
class History:
    def __init__(self, archive_root: Path, *, day: str): ...                 # 只读 <= day
    def last_balance_before(self, day: str) -> tuple[str, int] | None: ...   # 严格 <
    def balances_in(self, start: str, end: str) -> dict[str, int]: ...
    def progress_in(self, start: str, end: str) -> list[ProgressPoint]: ...
```

规则：

- **`History` 排除当天自身**：今天的余额只能来自 `observation`，不能来自今天已经写过的
  `judgment.json`。否则同一天重跑会拿自己上一轮的结果当历史，`facts` 就不再是纯函数
- `--stage judge --date 过去` 按那天能拿到的数据算（余额取 ≤ 那天，基线取那天之前最后一个）
- `--stage render` **不读未来**，但它可以触发重算（见下节）

### 重算为准

**不冻结。** `judgment.json` 是缓存，事实随时可以从权威输入重算，重算的结果就是最新结果。
这要求重算的单位是「一整天的判断」，不能只重算一半：

| 动作 | 结果 |
|---|---|
| `--stage judge` / `--stage all` | 观察 → 事实 → 说话，**整份覆盖**，不存在一半新一半旧 |
| `--stage render` | 只排版；发现 `materials/profile.md` 比当天 `judgment.json` 新时，**先重算这一天**再排版，并在 `render.log` 记一行 |
| `--date 过去` | 余额只用 ≤ 那天，但额度与进度按**当前档案**算 |
| `--rebuild` | 全量：逐天重跑所有归档日（每天一次模型调用），显式修复用 |

两条不变量仍然成立：

1. **一天之内自洽**：`facts` 和 `summary` / `advice` 一定来自同一次运行。这也是为什么
   `--stage render` 要升级成重算，而不是「刷新一个数」
2. **不读未来**：`compute(day)` 只拿得到 `≤ day` 的余额。重算只会让旧数字更新，
   不会让历史的某一天看见之后发生的事

代价是明确的：改了档案之后重算历史日，那天的额度/进度会和当初的报告不同。这是
「以重算为准」换来的，属于已接受的误差范围；补跑时 `backfilled: true` 标明「数字按当前档案算」。

于是「补跑 10-20」不会再出现四类时空错乱：进度快照被今天的存款覆盖、额度用今天的缺口推算、
趋势图画出未来、简报读到未来的 `pet_said.md`。

`pet_said.md` 是例外：它是渠道自己的呈现记忆（由 `pet_play.py` 写），渠道读它自己的产物
不算跨层读状态，保留。

## 误差从哪来

每天唯一会漂的是**手填存款**（`每月需存 = 缺口 ÷ 剩余月数` 依赖它）。取一组保守数字：
目标 100 万、存款 20 万、剩 50 个月 → `每月需存 16,000`；月收入 20,000、公积金 3,000 →
`可花 7,000`；`日额度 233`。

- 某天多存 3,000 → 每月需存 +60 → **日额度 −2 元**
- 用一个月前（差 6,000）的存款算历史额度 → **日额度 −4 元**

而 `已花`、`今天花了`、`明日额度` 全是当天的余额差，**零误差**。
所以「允许误差」的边界很清楚：日额度可能差几块，已花一分不差。

另一处差异：重算历史日时按**当前档案**算额度与进度，所以同一天在不同时间重算可能差几块。
这是「重算为准」的直接后果，也是它比「冻结旧值」简单的地方——不需要维护任何计划历史。

## 删掉什么

| 删除 | 原因 |
|---|---|
| `render/monthly.py` 整个文件 | 算术搬进 `judge/facts.py` |
| `render/trend.py::balances` | 余额序列改由 `history` 统计、`Judgment.trend` 携带（`to_svg` / `write` 留下，只吃传进来的点） |
| `judge/prompt.py::parse_balance` | 模型不再产出金额 |
| `pipeline._with_judged_savings` | 存款兜底改由 `facts` 处理，并标明口径（卡内余额 ≠ 总存款） |
| `pipeline._stamp_progress` | 进度成为 `facts.goal` 的一部分 |
| `console._history`、`console._month_line`、`console._pace_line`、`pet._rhythm` | 结论由 `Judgment` 携带，渠道只排版 |
| `Judgment.meta` | 拆成 `facts` / `trend` / `runtime` |

## 落地顺序（已全部落地）

| PR | 内容 | 验收 |
|---|---|---|
| 1 | `shared/types.py` 的 Facts 契约 + `judge/facts.py` + `judge/history.py`（纯函数，无 LLM） | 单测覆盖基线、缺口、超支、余额缺失、`<= day` 边界 |
| 2 | `judge/observe.py` + 摘录核验 + `BaseProvider.observe()` | 摘录对不上时 `confidence: suspect`；无余额时不编 |
| 3 | `secretary.py` 接线 + `Judgment` 新形状 + `runtime` + 旧 `meta` 兼容读取 | 旧 8 天归档仍能出报告；降级路径有数字 |
| 4 | prompt 吃事实 + stub 读事实 + 删 `parse_balance` | advice 能说出「明天匀回来」 |
| 5 | render 瘦身 + `--stage render` 自动重算 + `--rebuild` + 补跑回归测试 | 渠道不再 import 任何历史读取；补跑不改今天；改档案后重跑 render 会整份重算 |

## 测试影响

现有 109 项在 PR 1–4 期间保持全绿（PR 1 只新增文件，不改已有路径）。PR 5 动两处：

- `tests/test_monthly.py` 整体迁到 `tests/test_facts.py`（`render/monthly.py` 删除）
- `tests/test_pipeline.py::test_render_stage_refreshes_progress_snapshot` **基本保留**：
  「改档案后重跑 render 会刷新快照」仍然成立，只是刷新走的是完整重算，断言再加一条
  「重算后 summary 与 facts 同源」

新增测试集中在三块：`facts` 的纯函数边界（基线缺失、`<= day` 截断、余额空档）、
`observe` 的摘录核验（命中 / 编造 / 小数点错位）、补跑的整条链路（补跑历史不改今天）。

## 被否决的方案

| 方案 | 否决原因 |
|---|---|
| 正则抽取余额 | 换银行/换措辞就要改代码，素材来源本来是「各方」 |
| LLM 主导计算、调 CLI 出数 | 入参由模型概率性给出，传错日期会得到「自洽的错答案」，且 cron 路径无 agent |
| 计算完让 LLM 校验「是否合理」 | 「合理」没有判据：漏报真错、误报正确；校验该是字符串等式，不该是判断题 |
| 独立第四层 `facts/` | 多一个新包、一个新 stage、一套新 ctx、一层兼容，收益只是「渲染不读 archive」 |
| 一次调用 + 事实滞后一天 | 「今天花了多少」挪到第二天，正好砍掉产品最想说的那句 |
| 冻结月计划 / 只重算一半 | 冻结是旧值优先，和「重算为准」冲突；只重算一半会出现「报告说 A、建议按 B」 |
| 把事实塞进 `Judgment.meta` 维持现状 | 事实与运行信息继续共用命名空间，`meta` 契约永远说不清 |
