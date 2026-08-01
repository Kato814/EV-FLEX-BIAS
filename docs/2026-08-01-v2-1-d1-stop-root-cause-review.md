# V2.1-D1 `STOP_IMPLEMENTATION` 根因与学术证据复核

## 1. 复核结论

- 总体判定：`Needs revision`。当前 D1 不能用于机制判断，但停止门槛按冻结规则正确生效。
- 生产代码身份：`dcc05bd543f024cb786d0740727aefa3aac7563a`。
- 冻结 pilot 来源身份：`e1740f912a351b1822b5ee019f9e4f05b6b71c6f`。
- 实际终端：pair 01 为 `STOP_IMPLEMENTATION`，失败规则为 `PRE_AUDIT_IMPLEMENTATION_INVALID`，`sequence_index=null`。
- 实际覆盖：1/12 个终端 pair，0/72 条目标审计；pair 02--12 未运行。
- 旧 pilot 决策继续保持 `NO_GO_REASSESS_BROAD_TOPIC`；正式 V2.1 未授权、未启动。

## 2. 精确技术根因

停止并不是负荷倍率、场景索引或物理约束值漂移，而是 D1 校验器与冻结 pilot 的审计适配器版本契约不一致。

冻结 `src/evflex/pilot.py` 实际定义并输出：

```text
adapter_schema  = evflex.pilot.network-audit
adapter_version = 2
```

D1 生产校验器 `src/evflex/mechanism_diagnostic.py` 却硬编码要求：

```text
adapter_schema  = EV-FLEX-BIAS-PILOT-NETWORK-AUDIT
adapter_version = 1.0
```

该校验器把 `load_scale`、schema、version、feeder 和 model 放在同一个条件分支中，并统一抛出“raw audit load-scale identity differs from the reconstructed case”。因此终端错误文字只说明这个复合条件失败，不能据此断定 `load_scale` 本身错误。

对 pair 01 的 bad 成员执行只读、内存内的真实基线审计后，96 个时段的逐项不一致计数为：

| 校验项 | 不一致数/96 |
|---|---:|
| 时段与原始记录身份 | 0 |
| 记录中的 `load_scale` | 0 |
| 审计上下文中的 `load_scale` | 0 |
| feeder | 0 |
| model | 0 |
| 五项正式约束及 `line_thermal_in_scope` | 0 |
| `adapter_schema` | 96 |
| `adapter_version` | 96 |

首时段三处负荷倍率均为 `0.6063894`；没有发现负荷倍率的数值或索引差异。由此可把根因限定为 schema/version 契约错误，置信度为高。

## 3. 为什么测试通过但真实运行停止

测试夹具同样写入了错误的 `EV-FLEX-BIAS-PILOT-NETWORK-AUDIT` 和字符串 `1.0`，因此测试验证的是 D1 校验器与合成夹具彼此一致，而不是 D1 校验器与冻结 pilot 真实输出一致。现有测试也没有执行“真实 runtime 产生一个基线审计上下文，再交给 D1 身份校验”的最小集成检查。

这是一个测试替身与生产接口同时漂移的实现缺陷。它不修改或否定冻结 pilot 的物理计算，也不说明 LV906 或 IEEE13 的网络行为发生了变化。

## 4. 学术证据复核

### 可以确认

1. 停止门槛按预冻结规则在第一个矛盾处生效，后续 pair 没有被扩大执行。
2. 当前 D1 实现与冻结 pilot 的版本契约不兼容。
3. 旧 pilot 的 `NO_GO_REASSESS_BROAD_TOPIC` 仍是当前有效的机器决策。
4. 正式 V2.1 没有被启动，归档 pilot 证据没有被覆盖。

### 不能确认

1. 不能判断 LV906 的首个失效物理约束族，因为没有形成任何目标审计行或物理见证。
2. 不能判断机制是共同候选还是场景异质，也不能开展约束数量匹配分析。
3. 不能据此支持或否定“固定 EV 轨迹在不进行三相重新优化时的网络适用域与失效机制”这一收窄研究方向。
4. 不能把本次实现停止解释为物理不可行、研究方向失败、全部场景通过或会议录用证据。

因此，当前 D1 的科学状态是“未获得机制证据”，而不是“发现了某种机制”或“证明研究问题不成立”。

## 5. 后续整改边界

本次 pair 01 终端及四份生成报告必须保持不可变，不得通过修改代码后覆盖重跑。建议另行冻结 D1-R 修复协议，至少包括：

1. 使用新的协议版本和独立输出目录，保留本次 STOP 作为失败历史。
2. 在新配置中冻结正确的 schema `evflex.pilot.network-audit` 和整数 version `2`；冻结 pilot 文件哈希仍作为来源完整性条件。
3. 先写真实接口回归测试，证明旧校验要求失败、修复后通过；同时把 scale、schema、version、feeder、model 的失败代码拆开，避免误导诊断。
4. 在生产前增加一个真实 runtime 的最小基线集成预检；继续限制为单进程、单 worker、六个数值线程变量均为 1。
5. 修复后重新冻结代码身份，再从新的空目录执行 12-pair D1-R；仍不得启动正式 V2.1。

本记录只提出整改方案，不实施修复、不重跑 D1，也不改变正式 V2.1 的冻结状态。
