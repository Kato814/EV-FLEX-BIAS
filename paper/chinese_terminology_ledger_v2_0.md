# EV-FLEX-BIAS-V2.0 中文术语表

| 英文术语 | 中文规范译法 | 使用说明 |
|---|---|---|
| balanced-network model | 平衡网络模型 | 指快速聚合网络估计模型 |
| unbalanced distribution network / feeder | 不平衡配电网 / 不平衡馈线 | feeder 按具体语境译为“馈线” |
| EV aggregator | 电动汽车聚合商 | 首次出现写全称 |
| flexibility offer | 灵活性报价 | 指平衡模型给出的服务功率 |
| deliverability | 可交付性 | 指完整服务时段内满足车辆与网络约束的能力 |
| deliverability mapping fraction, \(\alpha_{\mathrm{map}}\) | 可交付比例 \(\alpha_{\mathrm{map}}\) | 保留数学符号 |
| increasing direction | 增功率方向 | 表示增加充电功率 |
| decreasing direction | 减功率方向 | 表示减少充电或允许时进行 V2G 反送 |
| same-input assessment | 同输入评估 | 两个模型使用完全相同的车辆和网络输入 |
| nonlinear three-phase verification | 非线性三相验证 | 作为物理参考模型 |
| false-safe event | 假安全事件 | 平衡模型给出报价，但三相验证需削减至少 5% |
| applicability assessment | 适用性评估 | 评估平衡估计在特定组合单元内是否可采用 |
| cell-specific | 分组合单元 | 组合单元由馈线、方向和持续时长共同定义 |
| abstaining rule | 带拒判机制的规则 | 不满足开发集条件时不输出适用性结论 |
| development set | 开发集 | 用于模型与阈值选择 |
| sealed holdout | 封存留出集 | 冻结后仅开启一次 |
| out-of-fold prediction | 折外预测 | 五折分层交叉验证所得预测 |
| false-safe rate | 假安全率 | 选中样本中的假安全事件比例 |
| phase allocation | 相别分配 | 指车辆在三相上的分配比例 |
| far-zone probability | 远端区域概率 | 指车辆接入馈线远端区域的概率 |
| charging urgency | 充电紧迫度 | 指满足离站能量需求的自然紧迫程度 |
| V2G participation | V2G 参与率 | 保留 V2G 缩写 |
| Wilson interval | Wilson 区间 | 报告二项比例的不确定性 |
| Brier score | Brier 评分 | 用于选择风险模型正则化强度 |
| refit / rethreshold / replacement | 重新拟合 / 重设阈值 / 替换 | 留出集开启后均禁止 |

翻译约束：数值、单位、数学符号、图表顺序、参考文献编号及结论边界与英文终稿保持一致；不得因中文表达而增强因果性、普适性或碳减排主张。
