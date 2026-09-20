# rToken Breakout Lab

Bitget AI Base Camp Hackathon S2 · Alpha Factory · **rToken 因子策略**（拟提交）。

以 rQQQ、rSPY、rAAPL、rTSLA 现货为固定研究池，研究突破确认、波动缩仓和退出纪律。目标用户是希望检验小规模 rToken 趋势策略的量化开发者。没有接入实盘下单。

**结果状态：已完成60天训练＋30天历史留出；严格稳定性检查：未通过。** 历史留出非完全未接触的盲测，不能据此保证未来收益。优化前全部153组尝试及本轮8组记录保留。

| 区间 | 净利润 USDT | 收益率 | 最大回撤 | Sharpe | 完整交易 |
|---|---:|---:|---:|---:|---:|
| 60天训练 | +81.2037 | +0.8120% | -1.3959% | 1.4241 | 5 |
| 训练高成本 | +65.9526 | +0.6595% | -1.4585% | 1.1453 | 5 |
| 30天历史留出 | -37.6348 | -0.3763% | -1.2013% | -0.9736 | 3 |
| 留出高成本 | -46.4077 | -0.4641% | -1.2293% | -1.1846 | 3 |

两个区间分别从10,000USDT开始，未拼成连续90天实盘收益。基准、成本、逐笔交易、缺失数据及选择偏差见[完整报告](reports/v2/report.html)。

## 三分钟评审入口

1. 打开 [可离线访问的证据演示](index.html)，查看训练、历史留出和成本压力。
2. 打开 [冻结规则](configs/frozen.json)、[选择记录](reports/v2/selection.json)和[留出成交报告](reports/v2/holdout/report.html)。
3. 按下方步骤下载四个公开数据文件，复现冻结结果；输入哈希不符会停止。

在线 Demo 需要发布 GitHub Pages 后填写链接；本地 index.html 和 localhost 不是评委公网地址。

## 快速开始

```bash
python -m venv .venv
# 激活虚拟环境后（Windows: .venv\Scripts\activate）
python -m pip install -r requirements-lock.txt
python scripts/verify_artifacts.py
python -m pytest -q
python scripts/fetch_data.py
python scripts/replay_frozen.py --out runs/frozen-replay
```

已知复现环境：Python3.13，pandas3.0.5，numpy2.5.2。其他支持版本需自行验证数值一致性。数据下载约47MB，无需交易 API key；数据不随仓库重分发。

本地查看网页：`python -m http.server 8000 --bind 127.0.0.1`，访问 `http://127.0.0.1:8000`。

重新运行全部固定优化（不追加参数）：

```bash
python scripts/optimize_spot_trend.py --data data/raw --out runs/optimization-replay
```

## 冻结策略

最终版本 `breakout-exit6-stop4-confirm2`，完整参数见 [JSON](configs/frozen.json)。仅在完整四小时桶上判断；突破过去18根的高点，根据冻结的连续确认根数入场；跌破退出通道或触发跟踪止损后发出退出。每个标的入场目标不超过账户权益20%，历史波动上升时缩仓，四标的共享现金，不加杠杆。

手续费默认每边10bp、滑点2bp；高成本每边15bp、滑点5bp。订单在下一完整分钟按买入高价／卖出低价加滑点成交，每分钟至多使用记录成交量1%。止损不是保证成交价。研究终点前24小时预定清仓，未成交余仓绝不虚构退出。

## 数据与研究诚信

- 训练：2026-06-19至2026-08-18；历史留出：2026-08-18至2026-09-17，UTC。
- 团队另一项目研究休市信息定价，本项目研究现货趋势／突破，代码和提交材料独立；行情来源共享并明确致谢。
- [固定数据来源](data/sources.json)：队友公开仓库提交 `93f1b3ed1deab19f272f67345880bbc82984e44e`。未发现数据重分发许可证，因此只提供下载与核验脚本，不复制其策略代码或原始数据。
- 四小时数据质量过滤、仓位、止损、缺口估值等说明见[方法文档](docs/METHODOLOGY.md)。原始token单位、历史规格与公司行动尚未独立认证。
- 选择在本轮结果和留出计算前分阶段冻结。严格筛选未通过时，仍按预声明规则挑一个版本做诊断性留出，明确显示失败状态；不会看留出换赢家。
- [前149组汇总](research_history/earlier149/all_trials.csv)、[前四组现货实验](reports/prior/spot-trend-20260920/report.html)、[本轮全部8组](reports/v2/results.csv)可查。
- 大模型用于辅助代码、测试、研究和报告整理；运行时交易信号来自确定性规则，没有虚构 AI 自主决策。

## 提交材料

[表单六段说明](docs/SUBMISSION.md) · [提交检查表](docs/SUBMISSION_CHECKLIST.md) · [X帖草稿](docs/X_POST_DRAFT.md) · [发布步骤](docs/PUBLISH.md) · [第三方来源](THIRD_PARTY_NOTICES.md)。

源码版权与许可见 [COPYRIGHT.md](COPYRIGHT.md)。尚未选择开放源代码许可证；公开可读不等同于授予第三方再分发许可。
