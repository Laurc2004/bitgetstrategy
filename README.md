# rToken Breakout Lab

**从突破信号到成交账本，一套可复现的 rToken 现货策略框架。**

[策略演示台](https://cunicle.github.io/bitgetstrategy/dashboard.html) · [GitHub](https://github.com/cunicle/bitgetstrategy) · [完整回测](https://cunicle.github.io/bitgetstrategy/reports/v3/report.html) · [自动测试](https://github.com/cunicle/bitgetstrategy/actions/workflows/tests.yml)

面向 rQQQ、rSPY、rAAPL、rTSLA，结合突破确认、波动仓位管理与通道退出。四资产共享现金账户，信号、成交、成本和风险指标均可追溯。

演示台支持时间轴回放、逐笔成交跳转、四资产信号解释、持仓和 CSV 导出。v3 已启动独立前向模拟：本机连接持续采集的账户，公开网页展示带时间戳的发布快照。[运行与验证规则](docs/FORWARD.md)。

## 策略能力

| 模块 | 实现 |
|---|---|
| 突破确认 | 对照连续创新高与突破位确认，降低单根信号对决策的影响 |
| 仓位管理 | 单标的入场目标上限 20%，波动升高时缩仓；现货无杠杆 |
| 成交模型 | 下一分钟成交、买卖高低价、手续费、滑点与成交量约束 |
| 风险控制 | 通道退出、跟踪止损、账户回撤停止与买单超时 |
| 回测分析 | 逐笔账本、净值曲线、持有基准、成本压力与参数对照 |

## 回测成绩 · 冻结 v3（113 天总期 = 78 天 IS + 35 天扩展 OOS）

数据：四标的 Bitget 现货 1m K 线（2026-06-01 上市起，经 v3 公共行情 API 补齐至 09-21），
引擎为仓库自带 1m 执行模型（下一分钟成交、容量约束、费用滑点逐笔计入）。参数 `hold_level-exit18-stop8` 全程冻结。

| 切分 | 净利润 | 收益率 | 最大回撤 | Sharpe | Sortino | 换手 | 完整交易（胜率） |
|---|---:|---:|---:|---:|---:|---:|---:|
| IS 06-01→08-17（78d） | +288.55 | +2.89% | -2.45% | 2.59 | 5.17 | 2.85x | 8（50%） |
| IS 高成本 | +265.79 | +2.66% | -2.55% | 2.36 | 4.57 | 2.85x | 8（50%） |
| OOS 08-18→09-16（30d） | -83.23 | -0.83% | -1.77% | 样本不足 | — | 1.53x | 5（20%） |
| OOS 扩展 08-18→09-21（35d） | -48.80 | -0.49% | -1.77% | -1.02 | -1.31 | 1.50x | 3（0%） |
| OOS 扩展 高成本 | -60.83 | -0.61% | -1.84% | -1.27 | -1.63 | 1.50x | 3（0%） |

**诚实结论：v3 参数在真正的样本外亏损**（与 v2 历史留出 -0.38% 同方向）：突破策略族在 8 月中以来的行情下失效，IS 收益主要来自开发期特定市况。我们如实公布而不是隐藏——这正是 [版本验证记录](docs/VALIDATION.md) 的一贯立场。成本压力下亏损加深有限（费用敏感度低），平均总敞口 20-38%，风险上限受 20% 单标的约束保护。

赛制合规：总期 113 天 ≥60 ✅；样本外 30-35 天 ≥30 ✅。全部指标为 1m 引擎实测值（`reports/is-oos-1m.json`）。

## 快速开始

```bash
python -m pip install -r requirements-lock.txt
python scripts/fetch_data.py
python scripts/replay_development_v3.py --out runs/v3-replay
```

```bash
# 检查代码与研究产物
python -m pytest -q
python scripts/verify_artifacts.py

# 本地打开演示页
python -m http.server 8000 --bind 127.0.0.1
```

访问 `http://127.0.0.1:8000`。数据下载不需要交易 API key；本项目不发送实盘订单。

## 文档

[策略与架构](docs/STRATEGY.md) · [版本验证](docs/VALIDATION.md) · [实验记录](docs/EXPERIMENTS.md) · [数据与方法](docs/METHODOLOGY.md)
