# API 供应商与安全使用

## 总原则

优先使用宿主 Agent 已提供的地图、天气和搜索工具。只有需要机器可读数据且宿主没有等价能力时，使用 `scripts/provider_client.py`。所有输出遵循统一结构：`contract_version/provider/capability/retrieved_at/source_url/source_type/data`。

供应商结果要记录查询时间和来源。地图 POI 不是景点开放、票价或预约的一手证据；这些事实仍需景区、场馆、交通运营方或政府来源。

## 高德地图

支持国内场景：

```bash
python scripts/provider_client.py geocode --provider amap --query "龙门石窟" --city "洛阳"
python scripts/provider_client.py places --provider amap --keyword "博物馆" --city "洛阳"
python scripts/provider_client.py route --provider amap --origin "112.47,34.68" --destination "112.47,34.56" --mode transit --city "洛阳"
```

只从环境变量 `AMAP_API_KEY` 读取 Web 服务 Key。不要通过命令参数、JSON、日志或计划文件传递密钥。客户端输出的 `source_url` 会删除 Key。

实现依据：

- 地理编码：<https://lbs.amap.com/api/webservice/guide/api/georegeo/>
- POI 搜索：<https://lbs.amap.com/api/webservice/guide/api/search/>
- 路径规划：<https://lbs.amap.com/api/webservice/guide/api/direction>

不要混合来自不同供应商、不同坐标基准的数据后直接计算路线；保留供应商元数据，并用同一地图服务核验最终门到门路线。

## Open-Meteo

```bash
python scripts/provider_client.py weather --provider open-meteo --lat 34.62 --lon 112.45 --start-date 2026-08-10 --end-date 2026-08-12
```

客户端查询逐日天气码、最高/最低温、最大降水概率和最大风速，单次范围最多 16 天。超出可靠预报范围时不要把季节气候写成具体天气预报。

官方文档：<https://open-meteo.com/en/docs>

## Nominatim 公共服务

公共 Nominatim 只用于开发者主动决定的低频、单次地理编码，不能作为默认批量景点搜索器。命令必须明确接受使用政策并提供缓存目录：

```bash
python scripts/provider_client.py geocode --provider nominatim --query "Luoyang, China" --accept-nominatim-policy --cache-dir <cache-directory>
```

必须遵守：每秒最多一次请求、有效 User-Agent、缓存、署名、禁止自动补全、禁止系统性 POI 抓取。商业或高频使用应更换供应商或自建服务。

- 使用政策：<https://operations.osmfoundation.org/policies/nominatim/>
- Search API：<https://nominatim.org/release-docs/latest/api/Search/>

## 测试与降级

- 默认测试必须使用 Mock 响应，不消耗真实配额，也不需要密钥。
- 真实 API 冒烟测试必须显式启用，且不能在日志中打印请求密钥。
- API 不可用时保留结构化错误，退化为片区/坐标估算，并把状态标为 `estimated`。
- 供应商返回的精确时间仍会随交通、道路和算法变化；计划中写范围，并在出行前复核。
