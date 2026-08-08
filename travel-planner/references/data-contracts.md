# 结构化数据与证据契约

## 四个核心契约

| 文件 | 用途 |
|---|---|
| `schemas/route-input.schema.json` | 路线优化器的候选景点、锚点与交通矩阵 |
| `schemas/final-plan.schema.json` | 最终计划、每日时间线、证据、预算、天气与返程 |
| `schemas/handoff.schema.json` | 多 Agent 或跨模型交接 |
| `schemas/quality-policy.json` | 证据时效、强度、天气、预算与返程阈值 |

使用 `scripts/validate_schema.py` 做基础结构检查；使用 `scripts/validate_plan.py` 做跨字段语义检查。JSON Schema 通过不代表计划可交付。

## 声明与证据

动态事实放在 `claims[]`，不要只散落在自然语言：

```json
{
  "id": "claim-ticket-1",
  "subject_id": "attraction-1",
  "type": "ticket_price",
  "value": {"currency": "CNY", "adult": 60},
  "status": "verified",
  "as_of": "2026-08-07T08:00:00Z",
  "method": null,
  "evidence_ids": ["source-official-1"]
}
```

证据放在 `evidence[]`，其 `supports[]` 同时记录声明 ID 和声明值的规范化 SHA-256：

```json
{
  "claim_id": "claim-ticket-1",
  "value_digest": "sha256:<64 lowercase hex characters>"
}
```

摘要用于检测“研究后又修改了声明”的不一致，不能证明网页内容本身真实。生成摘要前必须实际打开来源并提取对应事实；禁止为了让检查通过而对未经核验的内容重新计算摘要。

状态含义：

- `verified`：来源已打开，值与来源一致，且通过权威性和时效检查。
- `estimated`：有明确估算方法，但不是实时事实；`method` 必填。
- `unverified`：当前无法核验；最终输出必须醒目标记待复核。

## 最终计划

`final-plan.schema.json` 要求计划包含：旅行参数、用户约束、景点、逐日站点与路段、声明、证据、住宿区域、预算、备用方案和审计上下文。给出具体日期且处于可靠预报范围时增加 `weather[]`；提供返程信息时增加 `audit_context.return_plan`。

站点时间使用目的地当地时间 `HH:MM`。日期使用 `YYYY-MM-DD`。证据访问和声明核验时间使用带时区的 ISO 8601 时间。

## 交接契约

交接文件必须包含角色、任务、载荷、假设、未解决问题、已解决问题、证据 ID 和 `content_digest`。摘要覆盖除自身以外的整个交接对象。

验证多份交接时按时间和父子顺序传入。检查器会阻止：摘要不一致、父级缺失、角色不连续、未解决问题静默丢失、证据无声明消失。

## 隐私

结构化计划和交接文件不得含 API Key、Token、Cookie、证件号、银行卡、预订验证码或无关个人资料。需要保留的真实预订凭据应存入用户自己的受保护工具，而不是本 Skill。
