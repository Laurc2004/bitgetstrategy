# 实验记录

保留全部方向和负结果，不把同一数据上的反复选择解释为独立检验。

| 版本 | 参数尝试 | 数据状态 | 记录 |
|---|---:|---|---|
| 基差、配对与相对强弱 | 149 | 训练研究 | [全部尝试](../research_history/earlier149/all_trials.csv) |
| 现货趋势与突破 v1 | 4 | 60天训练 | [完整报告](../reports/prior/spot-trend-20260920/report.html) |
| 突破优化 v2 | 8 | 训练选择后固定一次历史留出 | [完整报告](../reports/v2/report.html) |
| 确认与退出 v3 | 12 | 已观察90天开发区间 | [完整报告](../reports/v3/report.html) |

共173次参数方案评估，其中包含作为对照重复运行的规则，不是173个独立策略或独立统计检验。高成本重放和持有基准不计为新的策略参数。v3沿用已观察历史区间，因此不能用于宣称新的样本外成绩。

## 重跑固定实验

```bash
python scripts/refine_spot_breakout.py --data data/raw --out runs/v3-full
python scripts/optimize_spot_trend.py --data data/raw --out runs/v2-full
```

旧结果保留运行时源码快照；研究结果按对应版本的协议和哈希解释。
