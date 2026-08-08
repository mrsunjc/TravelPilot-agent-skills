#!/usr/bin/env python3
"""Render a validated final-plan JSON as a portable SVG itinerary card."""

import argparse
import base64
import json
import mimetypes
import sys
from html import escape
from pathlib import Path


class VisualizerError(ValueError):
    """Raised when a plan cannot be rendered safely."""


KIND_LABELS = {
    "attraction": "景点",
    "meal": "用餐",
    "rest": "休息",
    "hotel": "住宿",
    "hub": "交通枢纽",
    "other": "其他",
}

KIND_COLORS = {
    "attraction": "#2563eb",
    "meal": "#ea580c",
    "rest": "#7c3aed",
    "hotel": "#0891b2",
    "hub": "#475569",
    "other": "#16a34a",
}

INTENSITY_LABELS = {
    "light": "轻松游",
    "normal": "正常游",
    "commando": "高强度游",
}

MODE_LABELS = {
    "walk": "步行",
    "walking": "步行",
    "metro": "地铁",
    "subway": "地铁",
    "bus": "公交",
    "transit": "公共交通",
    "taxi": "出租车",
    "ride_hailing": "网约车",
    "car": "驾车",
    "drive": "驾车",
    "bike": "骑行",
    "cycling": "骑行",
    "rail": "铁路",
    "train": "火车",
    "flight": "飞机",
}


def _as_text(value):
    if value is None:
        return ""
    return str(value)


def _e(value):
    return escape(_as_text(value), quote=True)


def _truncate(value, limit):
    text = _as_text(value).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def _load_plan(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualizerError("Cannot read final plan: %s" % exc)
    if not isinstance(payload, dict):
        raise VisualizerError("Final plan must be a JSON object")
    if not _as_text(payload.get("destination")).strip():
        raise VisualizerError("Final plan has no destination")
    itinerary = payload.get("itinerary")
    if not isinstance(itinerary, list) or not itinerary:
        raise VisualizerError("Final plan has no itinerary days")
    return payload


def _cover_data_uri(path):
    if not path:
        return None
    cover = Path(path)
    if not cover.is_file():
        raise VisualizerError("Cover image does not exist: %s" % cover)
    mime = mimetypes.guess_type(str(cover))[0]
    if mime not in ("image/png", "image/jpeg", "image/webp"):
        raise VisualizerError("Cover image must be PNG, JPEG, or WebP")
    encoded = base64.b64encode(cover.read_bytes()).decode("ascii")
    return "data:%s;base64,%s" % (mime, encoded)


def _leg_between(day, previous_id, current_id):
    for leg in day.get("legs") or []:
        if isinstance(leg, dict) and leg.get("from") == previous_id and leg.get("to") == current_id:
            return leg
    return None


def _leg_label(leg):
    if not isinstance(leg, dict):
        return "交通方式待核验"
    parts = []
    if leg.get("mode"):
        mode = _as_text(leg["mode"])
        parts.append(MODE_LABELS.get(mode.lower(), mode))
    if leg.get("minutes") is not None:
        parts.append("%s 分钟" % leg["minutes"])
    if leg.get("distance_km") is not None:
        parts.append("%s km" % leg["distance_km"])
    label = " · ".join(parts) if parts else "交通待核验"
    if not leg.get("verified"):
        label += "（估算）"
    return label


def _weather_line(plan):
    values = []
    for item in (plan.get("weather") or [])[:4]:
        if not isinstance(item, dict):
            continue
        text = _as_text(item.get("date") or "日期待定")
        if item.get("temp_min_c") is not None and item.get("temp_max_c") is not None:
            text += " %s–%s°C" % (item["temp_min_c"], item["temp_max_c"])
        if item.get("precipitation_probability") is not None:
            text += " 降雨%s%%" % item["precipitation_probability"]
        values.append(text)
    return "；".join(values) if values else "未提供具体日期，未生成逐日天气"


def _budget_line(plan):
    budget = plan.get("budget") or {}
    total = budget.get("total") or {}
    if total.get("min") is None or total.get("max") is None:
        return "预算待估算"
    currency = _as_text(budget.get("currency") or "CNY")
    travelers = budget.get("travelers")
    suffix = " / %s 人" % travelers if travelers else ""
    return "%s %s–%s%s" % (currency, total["min"], total["max"], suffix)


def build_cover_prompt(plan):
    destination = _truncate(plan.get("destination"), 40)
    attractions = []
    for item in plan.get("attractions") or []:
        if not isinstance(item, dict) or item.get("priority") == "optional":
            continue
        name = _as_text(item.get("name")).strip()
        if name and name not in attractions:
            attractions.append(name)
        if len(attractions) == 5:
            break
    zones = []
    for day in plan.get("itinerary") or []:
        for zone in day.get("zone_focus") or []:
            zone = _as_text(zone).strip()
            if zone and zone not in zones:
                zones.append(zone)
    return "\n".join(
        [
            "Use case: ads-marketing",
            "Asset type: travel itinerary cover illustration",
            "Primary request: 为%s旅行计划生成一张具有当地辨识度的横版封面插画。" % destination,
            "Landmarks: %s" % ("、".join(attractions) if attractions else "使用可靠且具有代表性的当地城市景观"),
            "Route areas: %s" % ("、".join(zones[:5]) if zones else "不绘制具体路线"),
            "Style/medium: 清晰、现代、温暖的旅行编辑插画，真实空间感，不过度卡通。",
            "Composition/framing: 16:9 横版，主体集中在中部和右侧，保留左侧安全留白。",
            "Text (verbatim): no text",
            "Constraints: 只生成装饰性封面，不绘制时间、门票、天气、地图标注或交通数据；不得虚构官方标志。",
            "Avoid: 文字、水印、二维码、品牌 Logo、错误汉字、密集信息图表。",
        ]
    )


def render_svg(plan, title=None, cover_image=None):
    destination = _as_text(plan.get("destination")).strip()
    days = plan.get("itinerary") or []
    if not destination or not days:
        raise VisualizerError("Destination and itinerary are required")

    width = 1200
    header_height = 250
    day_heights = []
    for day in days:
        stops = day.get("stops") if isinstance(day, dict) else []
        day_heights.append(112 + max(1, len(stops or [])) * 86)
    footer_height = 250
    height = header_height + 30 + sum(day_heights) + 28 * max(0, len(days) - 1) + footer_height + 54
    cover_uri = _cover_data_uri(cover_image)

    out = []
    add = out.append
    add('<?xml version="1.0" encoding="UTF-8"?>')
    add('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="%s旅行行程信息图">' % (width, height, width, height, _e(destination)))
    add("<defs>")
    add('<linearGradient id="page" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f8fafc"/><stop offset="1" stop-color="#eef2ff"/></linearGradient>')
    add('<linearGradient id="hero" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0f172a"/><stop offset="1" stop-color="#1d4ed8"/></linearGradient>')
    add('<filter id="shadow" x="-10%" y="-10%" width="120%" height="130%"><feDropShadow dx="0" dy="8" stdDeviation="12" flood-color="#0f172a" flood-opacity="0.10"/></filter>')
    add('<clipPath id="heroClip"><rect x="36" y="30" width="1128" height="200" rx="28"/></clipPath>')
    add('<style>text{font-family:"Noto Sans SC","Microsoft YaHei","PingFang SC",Arial,sans-serif}.muted{fill:#64748b}.small{font-size:16px}.label{font-size:15px;font-weight:700}.body{font-size:19px}.title{font-size:44px;font-weight:800}.daytitle{font-size:28px;font-weight:800}</style>')
    add("</defs>")
    add('<rect width="1200" height="%d" fill="url(#page)"/>' % height)

    add('<rect x="36" y="30" width="1128" height="200" rx="28" fill="url(#hero)" filter="url(#shadow)"/>')
    if cover_uri:
        add('<image href="%s" x="36" y="30" width="1128" height="200" preserveAspectRatio="xMidYMid slice" clip-path="url(#heroClip)"/>' % cover_uri)
        add('<rect x="36" y="30" width="1128" height="200" rx="28" fill="#0f172a" opacity="0.62"/>')
    trip = plan.get("trip") or {}
    rendered_title = title or "%s · %s日旅行计划" % (destination, trip.get("days") or len(days))
    add('<text x="82" y="103" class="title" fill="#ffffff">%s</text>' % _e(_truncate(rendered_title, 32)))
    add('<text x="84" y="142" font-size="19" fill="#dbeafe">按地理片区组织 · 交通衔接 · 预算与风险提示</text>')
    intensity = INTENSITY_LABELS.get(trip.get("intensity"), _as_text(trip.get("intensity") or "强度待定"))
    party = trip.get("party") or {}
    chips = ["%s 天" % (trip.get("days") or len(days)), intensity]
    if party.get("size"):
        chips.append("%s 人" % party["size"])
    chips.append(_budget_line(plan))
    chip_x = 82
    for chip in chips:
        chip_width = max(88, min(260, 34 + len(_as_text(chip)) * 18))
        add('<rect x="%d" y="170" width="%d" height="34" rx="17" fill="#ffffff" opacity="0.17"/>' % (chip_x, chip_width))
        add('<text x="%d" y="193" font-size="15" font-weight="700" fill="#ffffff">%s</text>' % (chip_x + 17, _e(_truncate(chip, 18))))
        chip_x += chip_width + 12

    y = header_height + 30
    for index, day in enumerate(days):
        if not isinstance(day, dict):
            continue
        card_height = day_heights[index]
        stops = day.get("stops") or []
        zones = " / ".join(_as_text(item) for item in (day.get("zone_focus") or [])) or "片区待定"
        date_text = _as_text(day.get("date") or "日期待定")
        add('<rect x="48" y="%d" width="1104" height="%d" rx="24" fill="#ffffff" filter="url(#shadow)"/>' % (y, card_height))
        add('<rect x="48" y="%d" width="12" height="%d" rx="6" fill="#2563eb"/>' % (y, card_height))
        add('<text x="84" y="%d" class="daytitle" fill="#0f172a">Day %s</text>' % (y + 43, _e(day.get("day") or index + 1)))
        add('<text x="210" y="%d" class="body muted">%s · %s</text>' % (y + 42, _e(date_text), _e(_truncate(zones, 38))))
        if stops:
            line_start = y + 94
            line_end = y + 94 + (len(stops) - 1) * 86
            add('<line x1="104" y1="%d" x2="104" y2="%d" stroke="#cbd5e1" stroke-width="4" stroke-linecap="round"/>' % (line_start, line_end))
        for stop_index, stop in enumerate(stops):
            if not isinstance(stop, dict):
                continue
            stop_y = y + 94 + stop_index * 86
            kind = stop.get("kind") or "other"
            color = KIND_COLORS.get(kind, KIND_COLORS["other"])
            if stop_index:
                previous = stops[stop_index - 1]
                leg = _leg_between(day, previous.get("id"), stop.get("id")) if isinstance(previous, dict) else None
                add('<text x="130" y="%d" class="small muted">↓ %s</text>' % (stop_y - 27, _e(_truncate(_leg_label(leg), 60))))
            add('<circle cx="104" cy="%d" r="13" fill="%s" stroke="#ffffff" stroke-width="5"/>' % (stop_y, color))
            time_text = "%s–%s" % (_as_text(stop.get("arrival_time") or "--:--"), _as_text(stop.get("departure_time") or "--:--"))
            add('<text x="132" y="%d" font-size="18" font-weight="700" fill="#334155">%s</text>' % (stop_y + 6, _e(time_text)))
            add('<text x="315" y="%d" font-size="21" font-weight="750" fill="#0f172a">%s</text>' % (stop_y + 6, _e(_truncate(stop.get("name") or "未命名地点", 28))))
            add('<rect x="790" y="%d" width="112" height="30" rx="15" fill="%s" opacity="0.12"/>' % (stop_y - 18, color))
            add('<text x="846" y="%d" text-anchor="middle" class="label" fill="%s">%s</text>' % (stop_y + 3, color, _e(KIND_LABELS.get(kind, "其他"))))
            add('<text x="930" y="%d" class="small muted">%s</text>' % (stop_y + 5, _e(_truncate(stop.get("zone") or "片区待定", 16))))
        y += card_height + 28

    footer_y = y
    add('<rect x="48" y="%d" width="1104" height="210" rx="24" fill="#0f172a"/>' % footer_y)
    lodging = (plan.get("lodging_recommendations") or [{}])[0]
    lodging_area = lodging.get("area") if isinstance(lodging, dict) else None
    claims = [item for item in (plan.get("claims") or []) if isinstance(item, dict)]
    unverified = sum(1 for item in claims if item.get("status") == "unverified")
    estimated = sum(1 for item in claims if item.get("status") == "estimated")
    add('<text x="82" y="%d" font-size="24" font-weight="800" fill="#ffffff">行前摘要</text>' % (footer_y + 42))
    add('<text x="82" y="%d" class="body" fill="#e2e8f0">住宿区域：%s</text>' % (footer_y + 80, _e(_truncate(lodging_area or "待推荐", 42))))
    add('<text x="82" y="%d" class="body" fill="#e2e8f0">预算范围：%s</text>' % (footer_y + 116, _e(_budget_line(plan))))
    add('<text x="82" y="%d" class="body" fill="#e2e8f0">天气：%s</text>' % (footer_y + 152, _e(_truncate(_weather_line(plan), 65))))
    add('<text x="82" y="%d" class="small" fill="#fbbf24">动态信息状态：%s 项估算，%s 项待核验；出发前复查开放、预约、天气和交通。</text>' % (footer_y + 184, estimated, unverified))
    add('<text x="600" y="%d" text-anchor="middle" font-size="14" fill="#64748b">此图为行程视觉摘要；精确事实、来源与备用方案以完整旅行计划为准。</text>' % (height - 22))
    add("</svg>")
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="Final-plan JSON")
    parser.add_argument("--output", "-o", required=True, help="Output SVG path")
    parser.add_argument("--title", help="Optional title override")
    parser.add_argument("--cover-image", help="Optional PNG/JPEG/WebP cover generated by the host")
    parser.add_argument("--prompt-output", help="Optional path for a host-neutral AI cover prompt")
    args = parser.parse_args(argv)
    try:
        plan = _load_plan(args.plan)
        rendered = render_svg(plan, title=args.title, cover_image=args.cover_image)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        if args.prompt_output:
            prompt_path = Path(args.prompt_output)
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(build_cover_prompt(plan) + "\n", encoding="utf-8")
    except (OSError, VisualizerError) as exc:
        print("Visualizer error: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps({"output": str(output.resolve()), "prompt_output": str(Path(args.prompt_output).resolve()) if args.prompt_output else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
