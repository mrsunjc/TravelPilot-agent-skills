# 计划与愿望清单持久化

## 原则

- 只有用户明确要求保存，或已明确开启长期旅行档案时才写入。
- 数据目录必须在 Skill 安装目录之外，通过 `--root` 或 `TRAVEL_PLANNER_DATA_DIR` 指定。
- 默认保存结构化 JSON，便于不同 Agent 读取；不要依赖 Codex、Claude 或其他厂商的私有会话格式。
- 不保存 API key、令牌、Cookie、证件号、护照、身份证、银行卡、预订验证码或无关个人信息。
- 若计划含必须保留的敏感预订资料，应建议用户放在其密码管理器/受保护旅行应用中，而不是本工具。

## 命令

```bash
python scripts/plan_store.py --root <data-directory> save --plan <plan.json>
python scripts/plan_store.py --root <data-directory> list-plans
python scripts/plan_store.py --root <data-directory> wishlist-add --destination "目的地" --note "可选备注"
python scripts/plan_store.py --root <data-directory> wishlist-list
python scripts/plan_store.py --root <data-directory> wishlist-remove --destination "目的地"
```

也可以由宿主安全设置环境变量：

```text
TRAVEL_PLANNER_DATA_DIR=<data-directory>
```

不要为了演示而读取或输出其他环境变量。

## 文件布局

```text
<data-directory>/
  plans/
    <timestamp>-<destination>.json
  wishlist.json
```

保存计划时脚本会生成稳定元数据并原子写入。`wishlist-remove` 是显式删除操作，只有用户明确要求移除对应目的地时才执行。
