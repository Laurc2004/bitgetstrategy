# v3 策略与架构

当前版本：`hold_level-exit18-stop8`；确认方式：守住原突破价；固定参数：[development-v3.json](../configs/development-v3.json)。

## 决策流程

1. 将分钟行情转换为已完成的四小时桶；至少60个成交量非零分钟、桶末最后报价不超过5分钟，滚动窗口至少75%的桶有效。
2. 首次突破过去18根的高点，阈值排除当前根。`fresh_highs` 要求连续两根都突破各自历史高点；`hold_level` 检验第二根是否仍高于第一根突破时的历史阈值。
3. 根据历史波动缩小单标的最高20%的入场目标；四个标的共用10000USDT现金，不加杠杆。
4. 按下一完整分钟的高低价加滑点、手续费和1%记录成交量约束成交，买入目标30分钟到期。
5. 跌破 18 根退出通道，或从持仓后高点回撤 8% 时发出后续退出；账户回撤停止阈值10%。缺口可能导致实际损失超过止损阈值。

## 工程结构

- `src/basis_lab/trend_research.py`：因果信号、共享现金执行和报告。
- `src/basis_lab/portfolio.py`：持仓成本与已实现收益记账。
- `scripts/refine_spot_breakout.py`：预先声明的12组开发对照与基准。
- `scripts/replay_development_v3.py`：复现选定v3开发结果，固定参数不再筛选。
- `scripts/replay_frozen.py`：保留v2冻结训练与历史留出的独立复现入口。
- `reports/v3/`：本轮全部结果；`reports/v2/`：上一冻结版本与历史留出。

本轮比较了确认方式、退出通道和止损宽度，未提高仓位上限、放宽成交量或降低手续费。选择规则先写入[protocol.json](../reports/v3/protocol.json)，完整12组结果均保留。
