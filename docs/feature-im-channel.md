# IM 渠道：只产待发消息，不主动推

> 对应需求：把每天的复盘送进 IM（微信 / 飞书 / Telegram 等）。
> 状态：已落地。

## 传输现实

很多 IM 机器人（尤其是个人微信的智能机器人）**只能回应用户消息，不能主动推送**：
定时任务那一轮没有入站消息，机器人发出的任何内容都到不了用户。

这不是本项目的限制，是传输层的限制。所以「IM 通道」在这里只能是
**产出 + 等待触发**，和 `pet` 渠道同构：

| | pet | im |
|---|---|---|
| 产出 | `pet_task.md` | `im_task.md` |
| 何时发送 | 宿主 agent 读简报后调 `pet_play.py` | 用户下次说话时补发 |
| 渠道自己联网吗 | 不联网（机械层在脚本里） | 不联网 |
| 清点时 | 跳过 | 跳过（`broadcast = True`） |

## 职责边界

`IMChannel` 只做两件事：

1. 把 `Judgment` 压成 **最多 4 行** 的人话（今日花费 / 本月还能花 / 近 7 天 / 一句建议）
2. 写一份 `archive/<日期>/im_task.md`，告诉宿主 agent 「发什么、图在哪、怎么标记已发」

它不做的：

- 不选时间：什么时候发由宿主决定（用户下一条消息）
- 不重算数字：全部来自 `judgment.facts` / `judgment.trend`
- 不转换图片：`trend.svg` 是矢量图，转 PNG 是宿主的活（见下）

## 补发协议

`im_task.md` 里写明了三步：

1. 用户下次说话时，把「正文」那几行原样作为回复发出去
2. 用宿主的 IM 发送能力（如 `dsh_im_return_file`）发同目录的 PNG
3. `touch im_task.md.sent` 标记已发，避免重复

宿主侧的巡检（每收到一条用户消息先跑）：

```bash
ls -1 archive/*/im_task.md 2>/dev/null | while read f; do
  [ -f "$f.sent" ] || echo "PENDING $f"
done
```

- 多期未补时只补最新一期，其余合并一句「还有 N 期没补」
- 全部已标记就不要提，正常回答用户当前问题

## 图：SVG 转 PNG

IM 客户端通常只收位图。`trend.svg` 是 W3C 矢量图，转一次即可：

```bash
sips -s format png archive/2026-11-04/trend.svg --out archive/2026-11-04/im.png   # macOS
# 或 rsvg-convert / inkscape / 任何 SVG 转换器
```

不把这个转换做进仓库：它要平台相关的转换器，属于宿主环境的事；
仓库只保证「同一个 `trend.svg` 是唯一图源」，避免图和数字打架。

## 什么时候该换成 webhook 渠道

如果宿主接的是**能主动推送**的通道（企业微信机器人 / Telegram Bot / 飞书 webhook），
就不要用本渠道——那应该是一个直接 POST 的 `webhook` 渠道：

- 由 cron 直接触发，不依赖用户先说话
- 配置只需一个 URL（放 `.env`，不进仓库）
- 仍然复用 `judgment.facts` 与 `trend.csv`，不重算

两者的传输能力不同，**不要混在一个渠道里**：一个是「待发」，一个是「已发」，
语义完全不同。

## 验收

| 需求 | 用例 |
|---|---|
| 产出可发送的短消息 | `test_body_is_short_and_speaks_facts` |
| 不联网 | `test_channel_is_broadcast_but_not_network` |
| 说明怎么发、怎么标记 | `test_writes_task_with_delivery_recipe` |
| 没图时只发文字 | `test_without_chart_says_text_only` |
| 管线里可选启用 | `test_pipeline_writes_im_task` |
| 清点不重复造待发 | `test_settlement_does_not_prepare_im` |
| 本月超支说清楚 | `test_month_over_is_stated` |

## 不在范围

- 主动推送（需要 webhook 型通道）
- 群聊 / 多接收人路由
- 富文本卡片、按钮回调
