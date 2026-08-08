#!/usr/bin/env python3
"""Provider-neutral CLI for geocoding, place search, routes, and weather."""

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ProviderError(ValueError):
    """Raised for safe, user-facing provider failures."""


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _number(value, name):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ProviderError("%s must be numeric" % name)


def _coordinate(value):
    parts = str(value).split(",")
    if len(parts) != 2:
        raise ProviderError("Coordinates must use lon,lat")
    lon = _number(parts[0], "longitude")
    lat = _number(parts[1], "latitude")
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ProviderError("Coordinates are outside valid ranges")
    return "%.6f,%.6f" % (lon, lat)


def _safe_url(endpoint, params):
    safe = {key: value for key, value in params.items() if key.lower() not in ("key", "apikey", "token", "signature", "sig")}
    return endpoint + "?" + urlencode(safe, doseq=True)


def _request_json(endpoint, params, user_agent, timeout=20, transport=None):
    safe_url = _safe_url(endpoint, params)
    if transport is not None:
        payload = transport(endpoint, dict(params), {"User-Agent": user_agent})
        if not isinstance(payload, (dict, list)):
            raise ProviderError("Mock/provider transport returned non-JSON data")
        return payload, safe_url
    url = endpoint + "?" + urlencode(params, doseq=True)
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
    except HTTPError as exc:
        raise ProviderError("Provider returned HTTP %s for %s" % (exc.code, safe_url))
    except URLError as exc:
        raise ProviderError("Provider request failed for %s: %s" % (safe_url, exc.reason))
    try:
        return json.loads(data.decode("utf-8")), safe_url
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderError("Provider returned invalid JSON for %s" % safe_url)


def _amap_key(env=None):
    environment = env if env is not None else os.environ
    key = environment.get("AMAP_API_KEY")
    if not key:
        raise ProviderError("AMAP_API_KEY is required in the environment")
    return key


def _amap_ok(payload):
    if not isinstance(payload, dict) or str(payload.get("status")) != "1":
        info = payload.get("info") if isinstance(payload, dict) else "invalid response"
        code = payload.get("infocode") if isinstance(payload, dict) else None
        raise ProviderError("Amap request failed: %s%s" % (info, " (%s)" % code if code else ""))


def amap_geocode(query, city=None, env=None, transport=None):
    endpoint = "https://restapi.amap.com/v3/geocode/geo"
    params = {"key": _amap_key(env), "address": query, "output": "JSON"}
    if city:
        params["city"] = city
    payload, source_url = _request_json(endpoint, params, "travel-planner-skill/2.0", transport=transport)
    _amap_ok(payload)
    results = []
    for item in payload.get("geocodes") or []:
        location = str(item.get("location") or "").split(",")
        if len(location) != 2:
            continue
        results.append(
            {
                "name": item.get("formatted_address") or query,
                "lon": _number(location[0], "longitude"),
                "lat": _number(location[1], "latitude"),
                "country": item.get("country"),
                "province": item.get("province"),
                "city": item.get("city"),
                "district": item.get("district"),
                "adcode": item.get("adcode"),
                "match_level": item.get("level"),
            }
        )
    return _normalized("amap", "geocode", source_url, results, "map")


def amap_places(keyword, city=None, types=None, limit=20, env=None, transport=None):
    endpoint = "https://restapi.amap.com/v3/place/text"
    limit = max(1, min(int(limit), 25))
    params = {"key": _amap_key(env), "keywords": keyword, "offset": limit, "page": 1, "extensions": "all", "output": "JSON"}
    if city:
        params.update({"city": city, "citylimit": "true"})
    if types:
        params["types"] = types
    payload, source_url = _request_json(endpoint, params, "travel-planner-skill/2.0", transport=transport)
    _amap_ok(payload)
    results = []
    for item in payload.get("pois") or []:
        location = str(item.get("location") or "").split(",")
        results.append(
            {
                "provider_id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "typecode": item.get("typecode"),
                "address": item.get("address"),
                "province": item.get("pname"),
                "city": item.get("cityname"),
                "district": item.get("adname"),
                "lon": _number(location[0], "longitude") if len(location) == 2 else None,
                "lat": _number(location[1], "latitude") if len(location) == 2 else None,
            }
        )
    return _normalized("amap", "places", source_url, results, "map")


def amap_route(origin, destination, mode, city=None, destination_city=None, travel_date=None, travel_time=None, env=None, transport=None):
    origin_text = _coordinate(origin)
    destination_text = _coordinate(destination)
    endpoints = {
        "walking": "https://restapi.amap.com/v3/direction/walking",
        "driving": "https://restapi.amap.com/v3/direction/driving",
        "transit": "https://restapi.amap.com/v3/direction/transit/integrated",
    }
    if mode not in endpoints:
        raise ProviderError("Amap route mode must be walking, driving, or transit")
    if mode == "transit" and not city:
        raise ProviderError("Transit routing requires --city")
    params = {"key": _amap_key(env), "origin": origin_text, "destination": destination_text, "output": "JSON"}
    if mode == "transit":
        params.update({"city": city, "extensions": "base", "strategy": 0})
        if destination_city:
            params["cityd"] = destination_city
        if travel_date:
            params["date"] = travel_date
        if travel_time:
            params["time"] = travel_time
    payload, source_url = _request_json(endpoints[mode], params, "travel-planner-skill/2.0", transport=transport)
    _amap_ok(payload)
    route = payload.get("route") or {}
    candidates = route.get("transits") if mode == "transit" else route.get("paths")
    candidates = candidates or []
    results = []
    for candidate in candidates[:3]:
        distance_m = _optional_float(candidate.get("distance"))
        duration_s = _optional_float(candidate.get("duration"))
        result = {
            "mode": mode,
            "distance_km": round(distance_m / 1000.0, 3) if distance_m is not None else None,
            "minutes": int(round(duration_s / 60.0)) if duration_s is not None else None,
            "cost": _optional_float(candidate.get("cost") or candidate.get("tolls")),
            "walking_distance_km": None,
            "transfers": None,
        }
        if mode == "transit":
            walking_m = _optional_float(candidate.get("walking_distance"))
            result["walking_distance_km"] = round(walking_m / 1000.0, 3) if walking_m is not None else None
            segments = candidate.get("segments") or []
            transit_segments = sum(1 for segment in segments if isinstance(segment, dict) and (segment.get("bus") or {}).get("buslines"))
            result["transfers"] = max(0, transit_segments - 1)
        results.append(result)
    return _normalized("amap", "route", source_url, results, "map")


def _optional_float(value):
    if value in (None, "", []):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def open_meteo_weather(lat, lon, start_date, end_date, transport=None):
    latitude = _number(lat, "latitude")
    longitude = _number(lon, "longitude")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ProviderError("Weather coordinates are outside valid ranges")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        raise ProviderError("Weather dates must use YYYY-MM-DD")
    if end < start or (end - start).days > 15:
        raise ProviderError("Weather date range must be 1 to 16 days")
    endpoint = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
        "timezone": "auto",
    }
    payload, source_url = _request_json(endpoint, params, "travel-planner-skill/2.0", transport=transport)
    daily = payload.get("daily") if isinstance(payload, dict) else None
    if not isinstance(daily, dict):
        raise ProviderError("Open-Meteo response has no daily forecast")
    dates = daily.get("time") or []
    results = []
    for index, day_text in enumerate(dates):
        results.append(
            {
                "date": day_text,
                "weather_code": _list_value(daily, "weather_code", index),
                "temp_max_c": _list_value(daily, "temperature_2m_max", index),
                "temp_min_c": _list_value(daily, "temperature_2m_min", index),
                "precipitation_probability": _list_value(daily, "precipitation_probability_max", index),
                "wind_speed_kmh": _list_value(daily, "wind_speed_10m_max", index),
            }
        )
    normalized = _normalized("open-meteo", "weather", source_url, results, "weather_api")
    normalized["timezone"] = payload.get("timezone")
    return normalized


def _list_value(mapping, key, index):
    values = mapping.get(key) or []
    return values[index] if index < len(values) else None


def nominatim_geocode(query, countrycodes=None, limit=5, accept_policy=False, cache_dir=None, user_agent=None, transport=None):
    if not accept_policy:
        raise ProviderError("Nominatim public service requires explicit acceptance of its usage policy")
    if not cache_dir:
        raise ProviderError("Nominatim requests require a cache directory")
    endpoint = "https://nominatim.openstreetmap.org/search"
    limit = max(1, min(int(limit), 10))
    params = {"q": query, "format": "jsonv2", "limit": limit, "addressdetails": 1}
    if countrycodes:
        params["countrycodes"] = countrycodes
    agent = user_agent or os.environ.get("TRAVEL_PLANNER_USER_AGENT") or "travel-planner-skill/2.0"
    safe_url = _safe_url(endpoint, params)
    cache_path = Path(cache_dir).expanduser().resolve() / (hashlib.sha256(safe_url.encode("utf-8")).hexdigest() + ".json")
    if cache_path.exists():
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        cached = True
    else:
        payload, safe_url = _request_json(endpoint, params, agent, transport=transport)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        cached = False
    results = []
    for item in payload if isinstance(payload, list) else []:
        results.append(
            {
                "provider_id": "%s:%s" % (item.get("osm_type"), item.get("osm_id")),
                "name": item.get("display_name"),
                "lat": _number(item.get("lat"), "latitude"),
                "lon": _number(item.get("lon"), "longitude"),
                "category": item.get("category"),
                "type": item.get("type"),
                "importance": item.get("importance"),
            }
        )
    normalized = _normalized("nominatim", "geocode", safe_url, results, "map")
    normalized.update({"cached": cached, "attribution": "© OpenStreetMap contributors, ODbL", "usage_policy": "https://operations.osmfoundation.org/policies/nominatim/"})
    return normalized


def _normalized(provider, capability, source_url, data, source_type):
    return {
        "contract_version": "2.0",
        "provider": provider,
        "capability": capability,
        "retrieved_at": _now(),
        "source_url": source_url,
        "source_type": source_type,
        "data": data,
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", "-o")
    subparsers = parser.add_subparsers(dest="command", required=True)

    geocode = subparsers.add_parser("geocode")
    geocode.add_argument("--provider", choices=["amap", "nominatim"], required=True)
    geocode.add_argument("--query", required=True)
    geocode.add_argument("--city")
    geocode.add_argument("--countrycodes")
    geocode.add_argument("--limit", type=int, default=5)
    geocode.add_argument("--cache-dir")
    geocode.add_argument("--accept-nominatim-policy", action="store_true")

    places = subparsers.add_parser("places")
    places.add_argument("--provider", choices=["amap"], required=True)
    places.add_argument("--keyword", required=True)
    places.add_argument("--city")
    places.add_argument("--types")
    places.add_argument("--limit", type=int, default=20)

    route = subparsers.add_parser("route")
    route.add_argument("--provider", choices=["amap"], required=True)
    route.add_argument("--origin", required=True)
    route.add_argument("--destination", required=True)
    route.add_argument("--mode", choices=["walking", "driving", "transit"], required=True)
    route.add_argument("--city")
    route.add_argument("--destination-city")
    route.add_argument("--date")
    route.add_argument("--time")

    weather = subparsers.add_parser("weather")
    weather.add_argument("--provider", choices=["open-meteo"], required=True)
    weather.add_argument("--lat", required=True)
    weather.add_argument("--lon", required=True)
    weather.add_argument("--start-date", required=True)
    weather.add_argument("--end-date", required=True)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "geocode" and args.provider == "amap":
            result = amap_geocode(args.query, args.city)
        elif args.command == "geocode":
            result = nominatim_geocode(args.query, args.countrycodes, args.limit, args.accept_nominatim_policy, args.cache_dir)
        elif args.command == "places":
            result = amap_places(args.keyword, args.city, args.types, args.limit)
        elif args.command == "route":
            result = amap_route(args.origin, args.destination, args.mode, args.city, args.destination_city, args.date, args.time)
        elif args.command == "weather":
            result = open_meteo_weather(args.lat, args.lon, args.start_date, args.end_date)
        else:
            raise ProviderError("Unsupported provider operation")
    except (ProviderError, OSError, json.JSONDecodeError) as exc:
        print("Provider error: %s" % exc, file=sys.stderr)
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())

