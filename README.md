# Travel Planner Agent Skill

一个面向 Codex、Claude、Gemini 及其他支持 Agent Skills 工作流的智能旅行规划 Skill。用户只需输入目的地和旅行天数，即可获得按地理片区组织、尽量少折返，并包含交通、住宿区域、餐饮、预算、天气、备用方案和可视化行程图的旅行计划。

当前版本：`v2.1.0`

> 本项目不是热门景点罗列器。它先研究开放条件、地理位置和交通关系，再生成可执行日程，并通过确定性质量门阻止不可靠方案。

## 1. 项目简介

Travel Planner 将旅行调研、空间分组、路线编排、证据管理、质量检查和可视化输出封装为一个可移植的 Agent Skill。即使用户只输入“洛阳，3天”，Agent 也会采用明确的默认假设直接生成初版，而不是强制追问。

`travel-planner/` 是可安装的 Skill 运行目录；仓库外层的 `tests/`、`evals/`、`tools/`、`release/` 和 CI 用于研发、回归和发布，不会增加普通旅行请求的上下文负担。

项目不内置全国完整景点数据库，也不代替官方票务系统。开放、票价、预约、天气和临时关闭等动态事实需要通过宿主工具或配置的 API 实时核验。

## 2. 主要功能

- 仅输入目的地和天数即可生成 Day 1、Day 2 等完整行程。
- 搜索景点并分成必去、推荐、可选。
- 按城东、城西、老城、郊区等自然片区聚类，减少折返。
- 规划步行、公交、地铁、打车等交通方式和时间范围。
- 推荐住宿区域、特色美食和顺路用餐区域。
- 查询门票、开放时间、预约、临时关闭和近期天气。
- 支持老人、儿童、情侣、朋友和不同游玩强度。
- 估算住宿、餐饮、市内交通、门票、大交通和机动预算。
- 提供雨天、闭馆、恶劣天气和提前返程备用方案。
- 保存用户明确要求保留的计划与愿望清单。
- 通过 Schema、声明—证据绑定、路线、预算、强度和返程质量门检查计划。
- 生成 SVG 行程信息图，并可嵌入宿主 Agent 生成的 AI 城市封面。

## 3. 使用示例

最小输入：

```text
使用 $travel-planner 帮我规划洛阳三天行程。
```

完整约束：

```text
使用 $travel-planner 规划 2026 年 10 月 2 日开始的西安四日游，
两名成年人带一个 8 岁儿童，正常强度，一定要去兵马俑，
第二天不安排太多步行，最后生成一张行程信息图。
```

修改计划：

```text
删除第二天的某某景点，增加一个室内亲子项目，并重新检查路线。
```

## 4. 安装方法

要求 Python 3.9 或更高版本。核心功能仅使用 Python 标准库，无需安装额外依赖。

```bash
git clone https://github.com/<YOUR_USERNAME>/travel-planner-skill.git
cd travel-planner-skill
```

安装到 Codex：

```powershell
Copy-Item -Recurse -Force .\travel-planner "$env:USERPROFILE\.codex\skills\travel-planner"
```

macOS / Linux：

```bash
cp -R ./travel-planner ~/.codex/skills/travel-planner
```

其他 Agent 只需能够读取 `SKILL.md`、按需读取 `references/` 并执行 Python 脚本。`agents/openai.yaml` 是 Codex/OpenAI 的可选界面元数据，其他平台可以忽略。

国内地图能力可选使用高德 Web 服务，密钥只能由宿主安全设置为 `AMAP_API_KEY`，不得写入仓库、命令、计划或日志。Open-Meteo 天气接口不需要 API Key。

## 5. 目录结构

```text
travel-planner-skill/
├── README.md
├── VERSION
├── pyproject.toml
├── travel-planner/       # 可安装 Skill
│   ├── SKILL.md
│   ├── agents/
│   ├── references/
│   ├── schemas/
│   ├── scripts/
│   └── tests/
├── tests/                # 仓库级测试
├── evals/                # Gold 与 held-out 评测集
├── tools/                # 评测工具
├── release/              # 发布构建与一致性检查
└── .github/workflows/    # GitHub Actions
```

## 6. 使用说明

验证最终结构化计划：

```bash
python travel-planner/scripts/validate_plan.py final-plan.json
```

生成 SVG 行程信息图：

```bash
python travel-planner/scripts/travel_visualizer.py final-plan.json \
  --output trip-overview.svg \
  --prompt-output cover-prompt.txt
```

嵌入宿主生成的 PNG、JPEG 或 WebP 城市封面：

```bash
python travel-planner/scripts/travel_visualizer.py final-plan.json \
  --cover-image destination-cover.png \
  --output trip-overview.svg
```

运行测试和评测：

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s travel-planner/tests -v
python tools/run_evals.py evals/gold/cases.json
python tools/run_evals.py evals/heldout/cases.json
```

构建安装包：

```bash
python release/build_release.py --root . --output travel-planner-skill-v2.1.0.zip
python release/check_release.py --root . --archive travel-planner-skill-v2.1.0.zip
```

## 7. 未来计划

- 扩大全国城市和县级目的地评测集，建立可量化覆盖率。
- 增加山岳、海岛、边境、乡村、亲子和无障碍场景。
- 接入更多合规地图和公共交通数据源。
- 增加官方公告、临时闭馆和预约政策的多来源交叉核验。
- 完善酒店区域评分、多人交通成本和分档预算模型。
- 在 SVG 基础上增加 HTML、PDF、PNG 和日历格式导出。
- 完善多语言和境外旅行规划规则。

## 8. 许可证与致谢

当前恢复后的仓库标选择 MIT License 2.0。公开代码自动获得自由复制、修改和再分发授权。

感谢高德开放平台、Open-Meteo、OpenStreetMap Nominatim、Python 与 JSON Schema 生态，以及推动 Agent Skills 互操作的工具与社区。外部服务仍受各自使用条款约束。
