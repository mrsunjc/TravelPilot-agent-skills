# 确定性质量门

## 执行

```bash
python scripts/validate_plan.py final_plan.json --output quality-report.json
python scripts/validate_plan.py final_plan.json --strict
```

普通模式允许少量可解释警告；严格模式要求零警告。无论哪种模式，任何 `error` 都会阻止通过。

## 检查类别

- `SCHEMA_*`：字段、类型、日期、时间和枚举。
- `SECURITY_*`：密钥、令牌、证件和其他敏感字段。
- `EVIDENCE_*`：来源存在性、双向绑定、值摘要、权威性、时效、声明冲突和动态事实覆盖。
- `CONSTRAINT_*`：必去、排除和未知景点约束。
- `SCHEDULE_*` / `RESERVATION_*`：重叠、时长、开放窗口、闭馆、预约、吃饭。
- `ROUTE_*`：相邻站缺少交通段、时间不足、跨区折返、估算路段和证据。
- `INTENSITY_*`：景点数、游览和交通时间超限。
- `WEATHER_*` / `BACKUP_*`：恶劣天气与同片区替代方案。
- `BUDGET_*`：分类、区间、总计和机动金。
- `RETURN_*`：枢纽、取行李、末段交通和返程缓冲。
- `EMERGENCY_*` / `LODGING_*` / `PARTY_*`：实用信息、住宿与特殊同行人。

## 评分

初始 100 分，每个错误扣 12 分、警告扣 3 分，最低通过分由 `quality-policy.json` 控制，当前为 80。通过还要求零错误；高分不能抵消关键错误。

评分用于版本比较，不用于掩盖发现项。最终输出应公开错误已经修复、警告仍存在哪些，以及估算路段占比。

## 证据时效

不同事实使用不同最大时效：天气和临时关闭最短，票价、开放、预约和交通次之。阈值位于 `quality-policy.json`，变更时必须增加测试与评测案例。

来源过期不一定代表事实错误，但意味着不能继续标为可靠的实时核验结果。应重新查询或降级为 `unverified`。

## 不能机器证明的部分

质量门无法证明景点“好不好玩”、用户一定喜欢、来源网页本身没有发布错误，也无法替代旅行当天的实时判断。它负责拦截结构性、时间性、证据性和约束性错误；体验判断仍由 Agent 解释，关键动态信息仍要临近出发复核。

## 评测

仓库级 `evals/gold` 保存公开标准案例，`evals/heldout` 保存测试时不应暴露给被测 Agent 的案例。标准答案是必须满足/禁止违反的约束，不是固定文案或唯一行程。

运行：

```bash
python tools/run_evals.py evals/gold/cases.json
python tools/run_evals.py evals/heldout/cases.json
```

评测报告记录期望命中率、检测召回率、有效案例误报代码数和平均质量分。真实运行记录只能保存脱敏指标和发现代码，不保存用户完整计划或凭据。
