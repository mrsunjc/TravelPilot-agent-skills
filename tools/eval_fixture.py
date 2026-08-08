"""Synthetic final-plan fixture and deterministic mutations for offline evaluation."""

import copy
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
QUALITY_ROOT = REPO_ROOT / "travel-planner" / "scripts"
if str(QUALITY_ROOT) not in sys.path:
    sys.path.insert(0, str(QUALITY_ROOT))

from travel_quality.common import value_digest


def valid_plan():
    claims = [
        {"id": "c-open", "subject_id": "museum", "type": "opening_hours", "value": {"weekdays": [1], "open": "09:00", "close": "17:00", "last_entry": "16:00"}, "status": "verified", "as_of": "2026-08-08T07:30:00Z", "method": None, "evidence_ids": ["e-official"]},
        {"id": "c-ticket", "subject_id": "museum", "type": "ticket_price", "value": {"currency": "CNY", "adult": 60}, "status": "verified", "as_of": "2026-08-08T07:30:00Z", "method": None, "evidence_ids": ["e-official"]},
        {"id": "c-reservation", "subject_id": "museum", "type": "reservation", "value": {"required": True, "channel": "official"}, "status": "verified", "as_of": "2026-08-08T07:30:00Z", "method": None, "evidence_ids": ["e-official"]},
        {"id": "c-closure", "subject_id": "museum", "type": "closure_status", "value": {"status": "open", "closed_dates": []}, "status": "verified", "as_of": "2026-08-08T07:30:00Z", "method": None, "evidence_ids": ["e-official"]},
        {"id": "c-weather", "subject_id": "2026-08-10", "type": "weather", "value": {"date": "2026-08-10", "precipitation_probability": 20, "wind_speed_kmh": 15, "temp_min_c": 22, "temp_max_c": 30}, "status": "verified", "as_of": "2026-08-08T07:40:00Z", "method": None, "evidence_ids": ["e-weather"]},
        {"id": "c-route", "subject_id": "hotel-to-museum", "type": "transport", "value": {"from": "hotel", "to": "museum-stop", "mode": "metro", "minutes": 20, "distance_km": 5.0}, "status": "verified", "as_of": "2026-08-08T07:45:00Z", "method": None, "evidence_ids": ["e-route"]},
        {"id": "c-emergency", "subject_id": "central-hospital", "type": "emergency", "value": {"name": "评测城中心医院", "phone": "12345"}, "status": "verified", "as_of": "2026-08-08T07:50:00Z", "method": None, "evidence_ids": ["e-emergency"]},
    ]
    claim_index = {item["id"]: item for item in claims}

    def support(claim_id):
        return {"claim_id": claim_id, "value_digest": value_digest(claim_index[claim_id]["value"])}

    return {
        "schema_version": "2.0",
        "plan_id": "eval-valid-001",
        "destination": "评测城",
        "generated_at": "2026-08-08T08:00:00Z",
        "trip": {"days": 1, "start_date": "2026-08-10", "intensity": "normal", "party": {"size": 2, "types": ["adult"]}},
        "user_constraints": {"must_go": ["museum"], "exclude": []},
        "attractions": [{"id": "museum", "name": "评测博物馆", "zone": "城中", "priority": "must", "duration_minutes": 120, "outdoor": False, "opening_windows": [{"weekdays": [1], "open": "09:00", "close": "17:00", "last_entry": "16:00"}], "closed_dates": [], "reservation": {"required": True, "status": "booked", "deadline": "2026-08-09T12:00:00Z"}, "claim_ids": ["c-open", "c-ticket", "c-reservation", "c-closure"]}],
        "itinerary": [{
            "day": 1,
            "date": "2026-08-10",
            "zone_focus": ["城中"],
            "stops": [
                {"id": "hotel", "name": "城中住宿区", "kind": "hotel", "zone": "城中", "arrival_time": "08:30", "departure_time": "09:00", "duration_minutes": 30},
                {"id": "museum-stop", "name": "评测博物馆", "kind": "attraction", "attraction_id": "museum", "zone": "城中", "arrival_time": "09:20", "departure_time": "11:20", "duration_minutes": 120, "reservation_status": "booked", "backup_ids": ["backup-rain"]},
                {"id": "lunch", "name": "城中午餐区", "kind": "meal", "zone": "城中", "arrival_time": "11:30", "departure_time": "12:30", "duration_minutes": 60},
                {"id": "hub", "name": "评测城站", "kind": "hub", "zone": "城中", "arrival_time": "15:00", "departure_time": "15:10", "duration_minutes": 10}
            ],
            "legs": [
                {"from": "hotel", "to": "museum-stop", "minutes": 20, "distance_km": 5.0, "mode": "metro", "cost": 3, "currency": "CNY", "verified": True, "evidence_ids": ["e-route"]},
                {"from": "museum-stop", "to": "lunch", "minutes": 10, "distance_km": 0.8, "mode": "walk", "cost": 0, "currency": "CNY", "verified": True, "evidence_ids": ["e-route"]},
                {"from": "lunch", "to": "hub", "minutes": 30, "distance_km": 7.0, "mode": "metro", "cost": 4, "currency": "CNY", "verified": True, "evidence_ids": ["e-route"]}
            ],
            "backup_ids": ["backup-rain"]
        }],
        "claims": claims,
        "evidence": [
            {"id": "e-official", "url": "https://official.example/museum/visitor-information", "title": "评测博物馆参观信息", "publisher": "评测博物馆", "source_type": "official", "accessed_at": "2026-08-08T07:30:00Z", "published_at": "2026-08-01T00:00:00Z", "supports": [support("c-open"), support("c-ticket"), support("c-reservation"), support("c-closure")]},
            {"id": "e-weather", "url": "https://weather.example/forecast/assessment-city", "title": "评测城逐日天气", "publisher": "评测气象服务", "source_type": "weather_api", "accessed_at": "2026-08-08T07:40:00Z", "published_at": None, "supports": [support("c-weather")]},
            {"id": "e-route", "url": "https://maps.example/route/hotel-to-museum", "title": "城中住宿区至评测博物馆路线", "publisher": "评测地图服务", "source_type": "map", "accessed_at": "2026-08-08T07:45:00Z", "published_at": None, "supports": [support("c-route")]},
            {"id": "e-emergency", "url": "https://government.example/emergency/assessment-city", "title": "评测城应急信息", "publisher": "评测城政府", "source_type": "government", "accessed_at": "2026-08-08T07:50:00Z", "published_at": "2026-08-01T00:00:00Z", "supports": [support("c-emergency")]}
        ],
        "lodging_recommendations": [{"area": "城中地铁沿线", "why": "连接景点和车站方便", "tradeoffs": "热门日期价格可能较高", "claim_ids": []}],
        "weather": [{"date": "2026-08-10", "weather_code": 2, "temp_min_c": 22, "temp_max_c": 30, "precipitation_probability": 20, "wind_speed_kmh": 15, "evidence_ids": ["e-weather"]}],
        "budget": {"currency": "CNY", "travelers": 2, "nights": 1, "categories": [
            {"name": "lodging", "min": 300, "max": 400, "status": "estimated", "evidence_ids": []},
            {"name": "food", "min": 150, "max": 250, "status": "estimated", "evidence_ids": []},
            {"name": "local_transport", "min": 100, "max": 150, "status": "estimated", "evidence_ids": ["e-route"]},
            {"name": "tickets", "min": 120, "max": 120, "status": "verified", "evidence_ids": ["e-official"]},
            {"name": "intercity_transport", "min": 0, "max": 0, "status": "unverified", "evidence_ids": []},
            {"name": "contingency", "min": 67, "max": 92, "status": "estimated", "evidence_ids": []}
        ], "total": {"min": 737, "max": 1012}},
        "backups": [{"id": "backup-rain", "trigger": "暴雨、闭馆或交通中断", "replacement_for": ["museum"], "zone": "城中", "action": "改去同片区室内展馆并重新运行质量门"}],
        "emergency": [{"type": "medical", "name": "评测城中心医院", "phone": "12345", "address": "评测城中心路1号", "evidence_ids": ["e-emergency"]}],
        "audit_context": {"assumptions": ["使用合成评测城市，不代表真实旅行信息"], "return_plan": {"departure_time": "18:00", "transport_kind": "rail", "hub_id": "hub", "final_activity_end": "14:30", "final_leg_minutes": 30, "luggage_pickup_minutes": 20, "required_buffer_minutes": 60}}
    }


def mutate(plan, mutation):
    result = copy.deepcopy(plan)
    if mutation == "valid":
        return result
    if mutation == "missing_evidence":
        result["claims"][0]["evidence_ids"] = []
    elif mutation == "budget_mismatch":
        result["budget"]["total"]["min"] += 50
    elif mutation == "excluded_scheduled":
        result["user_constraints"]["exclude"] = ["museum"]
    elif mutation == "overlap":
        result["itinerary"][0]["stops"][2]["arrival_time"] = "11:00"
    elif mutation == "reservation_unknown":
        result["attractions"][0]["reservation"]["status"] = "unknown"
        result["itinerary"][0]["stops"][1]["reservation_status"] = "unknown"
    elif mutation == "route_missing":
        result["itinerary"][0]["legs"].pop(1)
    elif mutation == "community_authority":
        result["evidence"][0]["source_type"] = "community"
    elif mutation == "stale_closure":
        result["evidence"][0]["accessed_at"] = "2026-07-01T07:30:00Z"
    elif mutation == "sensitive_field":
        result["passport_number"] = "***"
    elif mutation == "return_buffer":
        result["audit_context"]["return_plan"]["final_activity_end"] = "17:30"
    else:
        raise ValueError("Unknown mutation: %s" % mutation)
    return result
