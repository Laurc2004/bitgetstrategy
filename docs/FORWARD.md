# v3 前向模拟与演示台

## 当前账户

本次前向账户从 [冻结协议](../configs/forward-v3-freeze.json) 的 `started_at` 开始，计划观察 7 天。固定使用 v3 `hold_level-exit18-stop8` 参数，初始现金 10,000 USDT。账户不继承开发回测的收益或持仓，不在观察期间重新选参数。

- [交互演示台](https://cunicle.github.io/bitgetstrategy/dashboard.html)：历史回放、逐笔成交、持仓和策略解释。
- [公开前向快照](../data/live.json)：带采集时间的发布快照，公开网页不连接本机账户，也不声称实时更新。
- 本机服务的 `/api/live` 每 10 秒被演示台读取；采集器每 60 秒请求一次公开行情。

## 数据与执行

数据来自 Bitget 官方 [v3 行情接口](https://www.bitget.com/docs/catalog/market/market-data)，仅访问 `GET /api/v3/market/candles` 和 `GET /api/v3/market/tickers`，`category=SPOT`。四个标的为 RQQQUSDT、RSPYUSDT、RAAPLUSDT、RTSLAUSDT。不使用交易密钥，不发送实盘订单。

启动时最多取前 10 个自然日的分钟数据进行指标预热。预热数据不产生前向订单或盈亏。只接受已完成、OHLC 一致、数值有限的分钟 K 线；同一分钟第一次观察到的完成值被保留，重复数据不重复成交，后续修订计入重观察差异。

策略调用冻结的四小时信号函数，沿用 20% 单标的入场目标上限、10 bp 每边手续费、2 bp 滑点、1% 分钟成交量约束、0.01 数量步长、5 USDT 最小买入金额、30 分钟买单超时、8% 跟踪止损和 10% 账户回撤停止。

前向执行按**实际接收时间**创建订单，只有开始时间晚于或等于订单创建时间的后续完整分钟才能成交。比接收时刻落后超过 120 秒的 K 线只更新估值，不触发信号或成交。这比历史回测中假设即时收到信号的“下一分钟成交”更严格，因此不能承诺前向成交与历史回测逐笔相同。账户持仓以完成分钟收盘估值；行情卡片显示的最新 ticker 不直接改写账户净值。

观察结束或人工停止时，不虚构清仓，也不执行历史回测的计划结束退出。未平仓头寸、旧价格估值、行情异常和账户停止状态均保留。尚未完成 rToken 数量单位、真实账户费用及完整可成交深度的实盘验证；当前是固定假设下的纸面账户。

## 本地启动

```bash
python -m pip install -r requirements-lock.txt
# 新账户；输出目录必须为空
python scripts/track_forward.py --out runs/forward-v3 --init --days 7
```

在另一个终端启动页面：

```bash
python scripts/serve_dashboard.py --account runs/forward-v3 --port 8766
```

访问 `http://127.0.0.1:8766/dashboard.html#live`。保持计算机和采集进程运行；关闭终端、休眠或断网可能造成采样缺口。程序不会伪造缺口内的交易。

```bash
# 请求停止：保留账户与持仓
python scripts/track_forward.py --out runs/forward-v3 --stop
# 正常停止后，如需继续同一账户，先删除该目录的 STOP 标记，再运行：
python scripts/track_forward.py --out runs/forward-v3
```

同一账户只允许一个采集进程。异常退出遗留 `runner.lock` 时，先确认其中 PID 已停止再移除锁。SQLite 在同一事务中保存行情、事件、净值和检查点；重启不重置现金或重复生成已处理分钟的成交。启动及每轮采集检查源代码哈希；代码或参数改变时停止该账户，必须使用冻结副本或另建版本。

## 产物与展示

| 文件 | 用途 |
|---|---|
| `protocol.json` / `frozen_source/` | 冻结时间、参数和代码副本 |
| `account.sqlite` | 行情、订单、成交、净值及账户检查点 |
| `raw/*.json.gz` | 带请求和接收时间的公开接口响应 |
| `rounds.jsonl` | 每轮处理量、数据异常及重复修订计数 |
| `dashboard.json` | 本机页面读取的原子状态快照 |
| `warmup.json` | 指标预热状态 |

`data/replay.json` 从固定 v3 历史账本构建，包含四小时观察点和每笔实际回测成交时刻。时间轴、现金、仓位和事件按所选时刻同步切换；最大回撤来自完整分钟净值，图形抽样不改变指标。

公开网页的前向模式显示**发布快照**并检查数据年龄，超过 3 分钟未更新会提示。它不是云端常驻交易服务。执行 `python scripts/publish_snapshot.py --account <账户目录>` 可准备下一份公开快照，再运行 `python scripts/refresh_manifest.py` 和 `python scripts/verify_artifacts.py`，按正常 Git 提交流程发布。

## 验证目标

先检查采集连续性、信号因果关系、费用记账和重启一致性，再观察完整交易及成本后表现。7 天观察期不保证产生交易，也不足以证明策略持续盈利；无信号时保留空仓，下一阶段使用新增数据评估，不根据本轮观察即时调参。
