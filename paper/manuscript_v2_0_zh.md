<!--
中文对照版说明
1. 本文档仅用于与英文投稿终稿对照阅读，不作为投稿文件。
2. 数值通过与英文终稿相同的 V2.0 机器值账本注入。
3. 图内文字保留英文，中文图题与正文按英文终稿顺序对应。
4. 参考文献保留英文原文，避免书目信息在翻译中产生偏差。
-->

# 平衡网络电动汽车灵活性估计的方向与时长依赖有效性

中文对照阅读版（非投稿件）

依据英文终稿 EV-FLEX-BIAS-V2.0 翻译；图表、数据与参考文献保持一致

## 摘要

平衡网络模型能够快速筛查电动汽车（electric vehicle，EV）灵活性，但其给出的报价在不平衡馈线中未必保持可交付，而且有效性可能随调节方向和服务持续时长变化。本文提出一种同输入适用性评估方法，将每个平衡模型报价映射为在完整多时段非线性三相验证下仍然可行的最大比例。各馈线—方向—时长组合单元的带拒判风险规则仅利用开发集折外预测进行选择，并在一次性留出集审核之前冻结。评估覆盖 IEEE13 馈线和一个 906 节点欧洲低压馈线上的 V1G 增充电、V1G/V2G 减功率调用，持续时长为 15、30 和 60 min。在留出集中，IEEE13 馈线 15 min 增功率和减功率调用的可交付比例中位数分别为 {{v2.core.holdout.ieee13.inc.15m.median_alpha_map}} 和 {{v2.core.holdout.ieee13.dec.15m.median_alpha_map}}，LV906 馈线对应数值分别为 {{v2.core.holdout.lv906.inc.15m.median_alpha_map}} 和 {{v2.core.holdout.lv906.dec.15m.median_alpha_map}}。12 个馈线—方向—时长组合单元中，仅有 2 个满足预先规定的最小样本量和 5% 假安全率判据。结果表明，平衡模型估计可用于快速筛查，但其适用性应在局部组合单元内验证，而不应由统一折减系数表示。

**关键词—**电动汽车，配电系统灵活性，不平衡网络，V1G，V2G，适用性评估。

## I. 引言

电动汽车聚合商可通过增加充电、减少充电以及车辆到电网（vehicle-to-grid，V2G）反送，为配电系统和电力系统层面的服务提供灵活性。然而，只有在整个请求服务区间内同时满足车辆能量约束和网络约束时，所申报的灵活性才具有可交付性。平衡网络近似适合快速筛查，但相别不对称以及与电气位置相关的电压或热稳定约束，可能使平衡模型在映射回非线性三相馈线时产生乐观估计。

现有聚合灵活性模型主要描述可行功率区域，或在能量和功率约束下调度插电式电动汽车群体 [1]–[4]。相关配电网研究显式考虑不平衡，并量化相别分配、充电控制或 V2G 参与对电网承载条件的影响 [5]–[7]。这些研究说明了可计算聚合模型的价值，也揭示了相别感知验证的重要性，但尚未回答平衡网络灵活性估计在特定馈线、调节方向和服务持续时长下何时可信。汇总平均误差不足以回答这一问题，因为实际风险具有明确方向性：平衡模型判定某次调用可行，但相同调用在三相验证下失败。

本文构建了一个针对平衡电动汽车灵活性估计的同输入适用性评估流程。平衡模型在完全相同的车辆状态、本地负荷、调用时刻和持续时长下先计算灵活性报价。随后，完整多时段非线性三相模型搜索该报价中可交付的最大比例，记为 \(\alpha_{\mathrm{map}}\)。分组合单元的逻辑回归风险模型仅使用可观测场景描述量，并在开发集上选择满足预设假安全约束时覆盖率最大的区域。所有模型和阈值均在留出集仅开启一次之前冻结。图 1 概括了从快速估计到经验证、可拒判适用性规则的完整流程。

本文的贡献有三点。第一，定义保持平衡模型报价运行含义的方向感知可交付性指标和假安全事件。第二，在两种结构不同的不平衡馈线上，针对多个服务持续时长评估 V1G 和 V2G 调用，并仅使用开发集对相别分配、电气位置、本地负荷、充电紧迫度和 V2G 参与率开展紧凑消融实验。第三，将模型开发与一次性留出集审核严格分离，分别报告验证通过、验证失败、样本不足和无规则等结果，而不是把每个已拟合组合单元都表述为有效结论。在正式留出集中，12 个馈线—方向—时长组合单元中仅 2 个满足预先规定的适用性规则，说明适用性结论应局部陈述，不能由汇总精度直接推断。

[FIGURE:fig1_framework_v2_0.png|图 1. 同输入评估和一次性验证流程。平衡模型报价经多时段非线性三相验证筛查；分组合单元的带拒判规则仅由开发集确定。]

## II. 同输入适用性评估

### A. 平衡模型报价与三相可交付性

对于每个场景 \(s\)、方向 \(d\) 和持续时长 \(T\)，平衡模型返回恒功率块灵活性报价 \(F_{\mathrm{bal}}(s,d,T)\)。增功率方向表示增加充电；减功率方向表示减少充电，并在参与车辆允许时包含 V2G 反送。平衡模型与三相模型使用完全相同的车辆到达、离开、荷电状态、充电功率限制、相别和位置分配、本地负荷轨迹、调用时刻及服务持续时长。这一同输入设计隔离了网络表示的影响，避免车辆可用性或调度假设变化造成混淆。

三相验证器在服务窗口的每个 15 min 时段内，搜索平衡模型报价中仍保持可行的最大比例，其输出为

[EQUATION:\alpha_{\mathrm{map}}(s,d,T) = F_3ph(s,d,T) / F_bal(s,d,T),   0 <= \alpha_{\mathrm{map}} <= 1.]

其中，\(\alpha_{\mathrm{map}}=1\) 表示完整平衡模型报价可交付，较小数值表示保留的可交付比例。当 \(\alpha_{\mathrm{map}}<0.95\) 时定义为假安全事件，即快速模型给出的报价在非线性三相验证后至少需要削减 5%。三相验证器采用 0.95–1.06 p.u. 母线电压范围、2% 最大电压不平衡因子限制，以及不超过额定值的线路和馈线负载限制。

### B. 多时段与嵌套持续时长闭合

可交付性在完整车辆和网络轨迹上验证，而不是仅检查单个时刻。中午至次日中午的时域内，模型约束车辆能量平衡、连接状态、充电或反送功率以及离站能量需求。每个场景—方向工作单元同时求解 15、30 和 60 min 调用。某一请求时长可采用同一时长或更长嵌套时长得到的物理可行调度，但仅在后者容量更大时使用；容量相同时选择最短来源时长。该闭合规则在不查看留出集结果的情况下，保证服务容量随持续时长非递增。

### C. 分组合单元的带拒判规则

适用性分别针对 2 个馈线、2 个方向和 3 个持续时长形成的 12 个组合单元建模。每个 L2 逻辑回归模型根据电动汽车铭牌功率与变压器容量比、本地负荷倍率、相不平衡指数、远端区域概率、充电紧迫度中位数、调用时刻的正弦和余弦编码以及主导相指示变量，预测假安全风险；减功率方向模型还使用实际 V2G 参与率。这些描述量在三相验证之前即可获得，因此可用于前瞻性筛查。

数值特征在每个训练折内标准化，主导相采用独热编码并以 a 相为参照。模型正则化参数从 \(C\in\{0.03,0.1,0.3,1,3,10,30\}\) 中选择，以五折分层折外 Brier 评分最小为准；并列时选择更小的 \(C\)。每个组合单元的风险阈值在开发集上最大化覆盖率，同时要求至少选中 20 个样本且经验假安全率不超过 5%。不存在合格阈值的组合单元保持无规则状态。留出集开启前，全部特征定义、模型系数和阈值均以哈希形式冻结。

## III. 实验方案

### A. 馈线、场景与质量门

实验采用 IEEE 13 节点馈线和一个 906 节点欧洲低压馈线，并保留其三相拓扑和分相负荷 [8], [9]。电动汽车出行与连接轨迹源自 2022 年美国全国家庭出行调查 [10]。每个中午至次日中午的场景分别在 19:00、00:00、02:00 和 06:00 发起持续 15、30 和 60 min 的调用。核心设计包含 256 个场景和 1,536 次方向—时长评估，其中 {{v2.sample.development_evaluations}} 次划入开发集，384 次封存为留出集。

开发集质量门接受 {{v2.sample.development_success}} / {{v2.sample.development_evaluations}} 次评估。其余 6 行来自 LV906 的同一个场景，覆盖两个方向和三个持续时长，状态均为明确的基准不可行，而非软件失败。因此，成对汇总使用 96 个 IEEE13 场景和 95 个 LV906 场景。紧凑机理实验另包含 {{v2.sample.ablation_evaluations}} 次仅开发集的 15 min 评估，完成数为 {{v2.sample.ablation_success}}。每个数值工作单元均在新的单线程进程中运行，并以原子方式写入带哈希审核的结果文件。

### B. 紧凑机理消融实验

消融实验在 19:00 和 02:00 围绕共同参照设置，每次仅改变一个因素。相别分配使用 1:1:1、2:1:1 和 4:1:1；远端区域概率、本地负荷倍率和充电紧迫度各设 3 个水平；减功率方向的 V2G 参与率设 4 个水平。每个水平预先分配 3 个种子，并在适用时轮换主导相。对比在馈线、调用时刻、方向和重复内成对进行。冻结的 95% 区间使用 10,000 次分层自助重采样，种子为 2026072001。由于每个基本对比仅包含 3 个成对重复，这些结果用于诊断机理，而不用于估计普适效应量。

### C. 一次性留出集审核

在代码、特征、模型、阈值、统计程序和论文数值生成方式全部冻结后，留出集仅开启一次。{{v2.sample.holdout_evaluations}} 次评估全部成功终止，成功数为 {{v2.sample.holdout_success}}。留出集开启后，不重新拟合模型、不重设阈值，也不替换任何场景编号或随机种子。方向对比使用 10,000 次按调用时刻分层的自助重采样，种子为 2026072002。正式适用性结论要求留出集中至少选中 20 个样本，且选中样本的观测假安全率不超过 5%。同时报告 Wilson 区间以展示不确定性，但不把该区间作为第二个调参判据。

## IV. 结果

### A. 平衡模型估计具有方向和馈线特异性

开发集结果表明，平衡模型估计经常偏乐观，但严重程度并不一致。在 15 min 时，IEEE13 和 LV906 增功率调用的 \(\alpha_{\mathrm{map}}\) 中位数分别为 {{v2.core.development.ieee13.inc.15m.median_alpha_map}} 和 {{v2.core.development.lv906.inc.15m.median_alpha_map}}，对应假安全率分别为 {{v2.core.development.ieee13.inc.15m.false_safe_rate}} 和 {{v2.core.development.lv906.inc.15m.false_safe_rate}}。IEEE13 减功率调用的中位数为 {{v2.core.development.ieee13.dec.15m.median_alpha_map}}，而 LV906 减功率调用仅保留 {{v2.core.development.lv906.dec.15m.median_alpha_map}}。因此，“增功率始终更困难”和“减功率始终安全”均不能跨馈线成立。

[FIGURE:fig2_alpha_map_v2_0.png|图 2. 开发集上平衡模型灵活性到非线性三相可交付性的映射。每个结果均对应特定馈线、方向、持续时长和调用时刻；\(\alpha_{\mathrm{map}}<0.95\) 定义为假安全。]

封存留出集保持了同样的异质性。在 15 min 时，IEEE13 增功率和减功率调用的中位数分别为 {{v2.core.holdout.ieee13.inc.15m.median_alpha_map}} 和 {{v2.core.holdout.ieee13.dec.15m.median_alpha_map}}；LV906 对应数值分别为 {{v2.core.holdout.lv906.inc.15m.median_alpha_map}} 和 {{v2.core.holdout.lv906.dec.15m.median_alpha_map}}。在 IEEE13 成对样本中，增功率减去减功率的 \(\alpha_{\mathrm{map}}\) 中位数差为 {{v2.holdout.directional.ieee13.15m.median_alpha_diff}}，95% 区间为 [{{v2.holdout.directional.ieee13.15m.alpha_ci_low}}, {{v2.holdout.directional.ieee13.15m.alpha_ci_high}}]。LV906 的 15 min 差值为 {{v2.holdout.directional.lv906.15m.median_alpha_diff}} [{{v2.holdout.directional.lv906.15m.alpha_ci_low}}, {{v2.holdout.directional.lv906.15m.alpha_ci_high}}]，区间跨越 0。IEEE13 在 30 和 60 min 的差值分别为 {{v2.holdout.directional.ieee13.30m.median_alpha_diff}} 和 {{v2.holdout.directional.ieee13.60m.median_alpha_diff}}，LV906 对应为 {{v2.holdout.directional.lv906.30m.median_alpha_diff}} 和 {{v2.holdout.directional.lv906.60m.median_alpha_diff}}。因此，持续时长是结论边界的一部分，而不仅是绘图参数。

### B. 相别分配与 V2G 参与率揭示作用机理

紧凑消融实验识别出平衡映射发生显著变化的条件。对于 19:00 的 IEEE13 增功率调用，相别比例由 2:1:1 变为 4:1:1 后，\(\alpha_{\mathrm{map}}\) 中位数降低 {{v2.ablation.a1_phase.ieee13.19_00.inc.4_1_1.alpha_contrast}}，95% 区间为 [{{v2.ablation.a1_phase.ieee13.19_00.inc.4_1_1.alpha_ci_low}}, {{v2.ablation.a1_phase.ieee13.19_00.inc.4_1_1.alpha_ci_high}}]。LV906 的对应差值为 {{v2.ablation.a1_phase.lv906.19_00.inc.4_1_1.alpha_contrast}} [{{v2.ablation.a1_phase.lv906.19_00.inc.4_1_1.alpha_ci_low}}, {{v2.ablation.a1_phase.lv906.19_00.inc.4_1_1.alpha_ci_high}}]。相比之下，对于 02:00 的 LV906 减功率调用，V2G 参与率由 0.5 提高至 1.0 后，\(\alpha_{\mathrm{map}}\) 增加 {{v2.ablation.a5_v2g.lv906.02_00.dec.1_0.alpha_contrast}} [{{v2.ablation.a5_v2g.lv906.02_00.dec.1_0.alpha_ci_low}}, {{v2.ablation.a5_v2g.lv906.02_00.dec.1_0.alpha_ci_high}}]。这些成对结果支持把相别集中和 V2G 可用性视为作用机理，但较小重复数和不同设置下效应符号的变化，不支持将其解释为普适因果效应量。

[FIGURE:fig5_ablation_v2_0.png|图 3. 15 min 条件下仅使用开发集的成对消融结果。各点表示高水平减去参照水平的 \(\alpha_{\mathrm{map}}\) 差值，区间为冻结的分层自助法 95% 区间。]

### C. 仅两个组合单元的适用性规则通过验证

[TABLE:applicability|表 I. 一次性留出集适用性结果。验证条件为选中 \(n\geq20\)，且假安全率 \(\leq5\%\)。]

仅 IEEE13 馈线 15 和 60 min 的减功率调用满足正式判据。15 min 规则从 32 个样本中选中 {{v2.holdout.applicability.ieee13.dec.15m.selected_n}} 个，其中出现 {{v2.holdout.applicability.ieee13.dec.15m.false_safe_n}} 个假安全结果，假安全率为 {{v2.holdout.applicability.ieee13.dec.15m.false_safe_rate}}，覆盖率为 {{v2.holdout.applicability.ieee13.dec.15m.coverage}}。60 min 规则选中 {{v2.holdout.applicability.ieee13.dec.60m.selected_n}} 个样本，假安全结果为 {{v2.holdout.applicability.ieee13.dec.60m.false_safe_n}} 个，覆盖率为 {{v2.holdout.applicability.ieee13.dec.60m.coverage}}。IEEE13 30 min 减功率单元因选中样本的假安全率为 {{v2.holdout.applicability.ieee13.dec.30m.false_safe_rate}} 而未通过。另有 3 个组合单元虽然在开发集上得到规则，但留出集样本量不足；6 个组合单元在开发集上没有合格规则。因此，验证通过的正式结论仅限于上述两个组合单元。

[FIGURE:fig6_holdout_v2_0.png|图 4. 冻结模型在留出集上的适用性结果。结果在不重新拟合、不重设阈值且不替换样本的条件下报告。]

## V. 实际意义与局限

平衡模型灵活性估计仍可作为快速的上层筛查信号，但不能解释为与馈线无关的保证。本文规则增加了一个拒判层：它要么识别出经局部验证的运行区域，要么拒绝给出适用性结论。该结构适用于聚合商在开展详细三相验证之前对快速报价进行筛查的工作流程，尤其适用于可能支持低碳运行的智能充电和 V2G 服务。

本研究证据存在四项边界。第一，仅覆盖两个基准馈线和基于一次出行调查构建的合成电动汽车群体，而非现场部署。第二，相别连接、负荷曲线和 V2G 参与率均为模型输入，遥测误差、通信故障、市场响应和电池退化不在研究范围内。第三，部分留出集组合单元选中样本过少，无法支撑正式结论；即使是验证通过的组合单元，Wilson 区间仍然较宽。第四，本文衡量的是灵活性可交付性，而不是排放、可再生能源弃电或碳减排。因此，结果仅说明平衡网络估计在既定方案下何处可靠，不构成统一折减系数，也不构成量化碳效益。

## VI. 结论

本文通过同输入、多时段非线性三相验证和冻结的分组合单元带拒判规则，评估平衡网络电动汽车灵活性报价的运行有效性。核心认识是，可交付性由馈线、调节方向和持续时长共同决定，汇总误差统计不能替代这一局部结构。开发集和机理消融证据表明，相别集中与 V2G 参与率变化会在特定设置下导致显著且方向不一的可交付性变化。在一次性留出集中，仅 IEEE13 馈线 15 和 60 min 的减功率调用满足预设适用性判据，其余组合单元分别表现为未通过、无规则或样本不足。这些结果支持保守的局部筛查，而不支持统一折减。下一步应将审核扩展至现场校准馈线、更大的独立留出集、不确定遥测条件以及灵活性—排放联合目标。

## 参考文献

[1] X. Chen, E. Dall’Anese, C. Zhao, and N. Li, “Aggregate power flexibility in unbalanced distribution systems,” IEEE Trans. Smart Grid, vol. 11, no. 1, pp. 258–269, Jan. 2020, doi: 10.1109/TSG.2019.2920991.

[2] F. Al Taha, T. L. Vincent, and E. Bitar, “An efficient method for quantifying the aggregate flexibility of plug-in electric vehicle populations,” IEEE Trans. Smart Grid, vol. 16, no. 4, pp. 3142–3154, Jul. 2025, doi: 10.1109/TSG.2024.3384871.

[3] D. Yan, C. Ma, and Y. Chen, “Distributed coordination of charging stations considering aggregate EV power flexibility,” IEEE Trans. Sustain. Energy, vol. 14, no. 1, pp. 356–370, Jan. 2023, doi: 10.1109/TSTE.2022.3213173.

[4] X. Shi, Y. Xu, Q. Guo, and H. Sun, “Optimal dispatch based on aggregated operation region of EV considering spatio-temporal distribution,” IEEE Trans. Sustain. Energy, vol. 13, no. 2, pp. 715–731, Apr. 2022, doi: 10.1109/TSTE.2021.3130547.

[5] A. Churkin, W. Kong, P. Mancarella, and E. A. Martínez Ceseña, “Quantifying phase unbalance and coordination impacts on distribution network flexibility,” arXiv:2408.06516, 2024.

[6] N. I. Nimalsiri, E. L. Ratnam, D. Smith, C. Mediwaththe, and S. Halgamuge, “A distributed coordination approach for the charge and discharge of electric vehicles in unbalanced distribution grids,” IEEE Trans. Ind. Informat., vol. 20, no. 3, pp. 3551–3562, Mar. 2024, doi: 10.1109/TII.2023.3310741.

[7] F. Verbist, N. K. Panda, P. P. Vergara, and P. Palensky, “Impact of dynamic tariffs for smart EV charging on LV distribution network operation,” in Proc. IEEE Power & Energy Soc. Gen. Meeting, 2023, pp. 1–5.

[8] Electric Power Research Institute, “OpenDSS: The Open Distribution System Simulator,” software and documentation. [Online]. Available: https://opendss.epri.com/

[9] IEEE PES AMPS Distribution System Analysis Subcommittee, “IEEE distribution test feeders.” [Online]. Available: https://cmte.ieee.org/pes-testfeeders/resources/

[10] S. Bricka, T. Reuscher, P. Schroeder, M. Fisher, J. Beard, and L. Sun, “Summary of travel trends: 2022 National Household Travel Survey,” U.S. Federal Highway Administration, Rep. FHWA-HPL-24-009, Jan. 2024.
