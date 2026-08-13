# EV-FLEX-BIAS R3 最小补充实验预注册设计
日期：2026-08-13

## 1. 实验角色

R3 定义为 **post-hoc mechanism supplement（事后机制补充实验）**，不是独立验证、不是 blind holdout，也不用于重新调 PHiCTE。

R3 的触发依据已经由 R2 boundary-witness diagnostic 预先确定：

- R2 中共有 56 个 scientifically eligible、active、15-min 且 `alpha_fixed < 1` 的 case；
- 56/56 的边界均可复现；
- 50/56 的 first-boundary witness 属于 voltage/VUF；
- LV906 的 42/42 个 limited cases 均为 voltage boundary；
- 当前 bus-time-preserving phase tie-break 在 LV906 缺少有效的跨空间调节自由度。

因此 R3 只回答一个窄问题：

> 在保持对外 feeder-time aggregate trajectory 不变的前提下，允许 EV 在车辆/母线间重新分配后，R2 中 fixed-schedule transferability loss 有多少能够被一个冻结的、网络引导的构造式 repair 恢复？

## 2. 不允许改变的内容

R3 不改变：

- R2 的 56 个目标 case；
- 原始 baseline 和 balanced schedule；
- IEEE13 / LV906 feeder 数据；
- 车辆参数、相别、可用时段、SOC/能量目标、V2G 预算；
- 正式网络约束：
  - 0.95 <= V <= 1.06 p.u.
  - VUF <= 2%
  - transformer loading <= 1.0 p.u.
  - feeder loading <= 1.0 p.u.
  - line thermal 仍不在正式约束集内；
- OpenDSS 作为最终 nonlinear truth audit。

R3 不得根据结果删除 case、换 feeder、改网络限值或重新调 PHiCTE。

## 3. 外部承诺保持定义

设：

- `u0_i,t`：baseline EV schedule；
- `uB_i,t`：原 balanced schedule；
- `alpha`：待检验的 aggregate transfer factor。

原 fixed ray 为：

`u_fixed_i,t(alpha) = u0_i,t + alpha * (uB_i,t - u0_i,t)`。

定义其 feeder-time aggregate trajectory：

`P_ray_t(alpha) = sum_i u_fixed_i,t(alpha)`。

R3 repair schedule `uR_i,t(alpha)` 必须满足：

`sum_i uR_i,t(alpha) = P_ray_t(alpha)`，对全部 96 个时段成立。

因此 R3 不允许通过降低外部 offer、改变 rebound 的 feeder aggregate trajectory 或转移服务时段来“制造”成功。

允许改变的是同一 aggregate trajectory 在不同 EV、bus 和固定 phase connection 之间的内部实现方式。

## 4. 车辆约束

每个 repair candidate 必须继续满足原 trajectory LP 的全部车辆约束，包括：

- arrival / departure availability；
- charge/discharge power limits；
- V1G/V2G mode restriction；
- SOC reserve / capacity；
- exact departure energy；
- V2G discharge-energy budget；
- no simultaneous charge/discharge；
- schedule identity。

这些约束不放松。

## 5. 构造式 spatial repair oracle

R3 不求解完整 nonlinear three-phase OPF。采用“constraint-generation spatial repair”作为构造式、可核验的 lower-bound oracle。

### Step 0 — 初始 candidate

在给定 `alpha` 下，先求一个满足车辆约束和 96-slot feeder aggregate equality 的 trajectory，目标为尽可能接近 `u_fixed(alpha)`。

若无任何 spatial target，这个问题应允许原 `u_fixed(alpha)` 本身作为可行车辆解。

### Step 1 — 完整 nonlinear audit

使用和 R2 完全相同的 corrected three-phase OpenDSS audit 对 96 个时段进行检查。

若全部正式网络约束通过，则该 `alpha` 被记为 **verified repaired feasible**。

### Step 2 — 定位首次物理失败时段

如果失败且不存在 numerical/convergence failure，取 first physical-failure slot `s`。

不根据 constraint class 人工选择不同策略；voltage、VUF、transformer、feeder 统一走同一程序。

### Step 3 — 构造该时段的 spatial target

在时段 `s`，使用现有 three-phase point optimizer：

1. 从同一 baseline group injection 出发；
2. 使用 finite-difference sensitivity 构造线性候选；
3. 按 inc/dec 方向寻找满足车辆瞬时上下界的 spatial group vector；
4. 对候选进行 nonlinear network evaluation；
5. 若线性候选不满足 nonlinear constraints，则沿 baseline→candidate 路径二分回退到 nonlinear-feasible point。

然后将该 nonlinear-feasible bus-phase group injection 按所需 aggregate magnitude 缩放/插值为同一 `P_ray_s(alpha)` 的 spatial target。

若 pointwise feasible headroom 小于所需 aggregate commitment，则该 `alpha` 在本 oracle 下判定失败。

### Step 4 — 加入固定 spatial target 后重解 trajectory

将 slot `s` 的 bus-phase injection 作为 equality target 加入 trajectory LP，同时继续保持：

- 全 96-slot feeder aggregate trajectory；
- 全车辆约束；
- 之前已经加入的 spatial targets。

重新求解后再次执行完整 nonlinear audit。

### Step 5 — constraint generation

若另一个时段首次失败，则对新时段重复 Step 2–4。

每个 slot 最多加入一次；因此理论上最多 96 次迭代，不设置根据结果选择的小型人为迭代上限。

任何 trajectory LP infeasible、pointwise headroom不足、numerical invalid 或不能复现正式约束的情况都保留为失败结果。

## 6. R3 的 transferability 指标

R3 不把结果称为真正的 three-phase optimal transferability。

定义：

`alpha_SR` = 冻结 spatial-repair procedure 实际找到并通过完整 nonlinear 96-slot audit 的最高搜索 factor。

它是 **verified achieved factor / lower bound**，不是全局最优 supremum。

主要增益：

`Delta alpha_SR = alpha_SR - alpha_fixed`。

同时报告：

- full rescue：`alpha_SR >= 0.99`；
- material repair：`Delta alpha_SR >= 0.05`；
- positive repair：`Delta alpha_SR > 0.01`；
- mean / median `Delta alpha_SR`；
- feeder-stratified；
- direction-stratified；
- boundary-class-stratified；
- 每个 repaired case 使用的 spatial-target slot 数；
- repair 后新的 first-boundary class（若仍失败）。

## 7. alpha 搜索

为控制计算量，同时避免把结果写成“精确最优”：

1. 先测试 `alpha=1`；
2. 若成功，直接记 `alpha_SR=1`；
3. 若失败，在 `[alpha_fixed, 1]` 上进行固定容差 0.01 的二分搜索；
4. 最终对 `alpha_SR` 和其上方一个搜索点分别保留 full audit 结果；
5. 如果出现明显 non-monotone verified outcomes，则不继续把二分结果解释为 boundary，只报告最高 verified sampled factor，并标记 non-monotone。

## 8. Primary target set

R3 primary target set 固定为 boundary-witness 已经识别出的全部 56 个 limited 15-min R2 cases。

不只挑 LV906，也不只挑 voltage case。

原因：

- LV906 是最明确的 voltage-dominated feeder；
- IEEE13 提供 transformer/VUF/voltage 混合机制；
- 全部 56 case 可防止事后挑选“容易 repair”的样本。

## 9. 预先冻结的结果解释规则

### 情形 A：明显恢复

若大量 case 出现 `Delta alpha_SR >= 0.05`，尤其 LV906 voltage cases：

可支持：
> fixed-schedule loss 中存在可由 commitment-preserving spatial redispatch 恢复的部分。

不可写：
> proposed repair is globally optimal / universally effective。

### 情形 B：局部恢复

若只在特定 feeder / direction / boundary class 有明显恢复：

按机制异质性报告，不合并成普遍有效结论。

### 情形 C：几乎不恢复

若大多数 case `Delta alpha_SR < 0.05`：

保留负结果，主论文回到：
> fixed-schedule transferability characterization + physical boundary mechanisms + limits of simple/post-schedule coordination。

不得为了增强结果继续修改约束、筛选 case 或反复发明新 heuristic。

## 10. 与当前 bus-time repair 的区别

当前 phase tie-break 强制保持每个 bus、每个时段的 aggregate EV schedule，只能在同一 bus 内部重新分配车辆。

R3 放松内部 preservation level 到 feeder-time aggregate equality，因此允许跨 bus/vehicle 的空间 redispatch，但仍保持对外 96-slot aggregate trajectory。

因此两者回答的问题不同：

- `alpha_fixed`：原 exact schedule 能迁移多少；
- 当前 `alpha_bus_repair`：只在 bus 内重排时能恢复多少；
- `alpha_SR`：保持外部 feeder trajectory、允许空间 redispatch时，冻结构造式 oracle 实际能恢复多少。

三者共同用于 transferability-loss decomposition，而不是把 R3 包装成新的通用 OPF。
