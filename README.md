# rToken Breakout Lab

**从突破信号到成交账本，一套可复现的 rToken 现货策略框架。**

[策略 dashboard](https://cunicle.github.io/bitgetstrategy/) · [GitHub](https://github.com/cunicle/bitgetstrategy) · [完整回测](https://cunicle.github.io/bitgetstrategy/reports/v3/report.html) · [自动测试](https://github.com/cunicle/bitgetstrategy/actions/workflows/tests.yml)

面向 rQQQ、rSPY、rAAPL、rTSLA，结合突破确认、波动仓位管理与通道退出。四资产共享现金账户，信号、成交、成本和风险指标均可追溯。

## 策略能力

| 模块 | 实现 |
|---|---|
| 突破确认 | 对照连续创新高与突破位确认，降低单根信号对决策的影响 |
| 仓位管理 | 单标的入场目标上限 20%，波动升高时缩仓；现货无杠杆 |
| 成交模型 | 下一分钟成交、买卖高低价、手续费、滑点与成交量约束 |
| 风险控制 | 通道退出、跟踪止损、账户回撤停止与买单超时 |
| 回测分析 | 逐笔账本、净值曲线、持有基准、成本压力与参数对照 |

## 最新回测 · v3

**90 天开发区间：2026-06-19 至 2026-09-17，初始资金 10,000 USDT。** 此区间已用于参数研究，下表是开发回测，不是新增样本外验证。

| 指标 | 基准成本 | 高成本 |
|---|---:|---:|
| 净利润 | **+150.33 USDT** | **+117.89 USDT** |
| 账户收益率 | +1.5033% | +1.1789% |
| 最大回撤 | -2.4499% | -2.5548% |
| 完整交易 | 12 | 12 |
| 手续费 | 40.92 USDT | 61.34 USDT |

基准成本每边手续费 10 bp、额外滑点 2 bp；高成本分别为 15 bp、5 bp。选定版本：`hold_level-exit18-stop8`。同区间基准、全部 12 组对照与逐笔成交见[报告](reports/v3/report.html)。

三个连续 30 天开发段净损益分别为 **+138.28 / +131.48 / −119.43 USDT**，收益存在阶段差异。同区间四资产等权持有为 −63.54 USDT，SPY 持有为 +140.83 USDT；策略与两项基准的平均持仓分别约为初始资金的 33.0%、39.7%、77.8%，风险暴露不同。

新版本尚待独立验证。上一冻结版本 v2 的 30 天历史留出为 **-0.3763%**，结果保留于[版本验证记录](docs/VALIDATION.md)。

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
