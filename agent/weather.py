"""
agent/weather.py
================
Fetch current weather + a short forecast from Open-Meteo.

Open-Meteo needs NO API key, no sign-up, no credit card. Free for
non-commercial use. https://open-meteo.com

Default location is Waterloo, Ontario, Canada. Override in .env with:
    WEATHER_LATITUDE=43.4643
    WEATHER_LONGITUDE=-80.5204
    WEATHER_PLACE=Waterloo, ON
"""

import os
import requests

# Waterloo, Ontario, Canada
DEFAULT_LAT = 43.4643
DEFAULT_LON = -80.5204
DEFAULT_PLACE = "Waterloo, ON"

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> human description + emoji
# https://open-meteo.com/en/docs (WMO Weather interpretation codes)
WEATHER_CODES = {
    0:  ("Clear sky", "☀️"),
    1:  ("Mainly clear", "🌤️"),
    2:  ("Partly cloudy", "⛅"),
    3:  ("Overcast", "☁️"),
    45: ("Foggy", "🌫️"),
    48: ("Depositing rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"),
    53: ("Moderate drizzle", "🌦️"),
    55: ("Dense drizzle", "🌧️"),
    61: ("Slight rain", "🌦️"),
    63: ("Moderate rain", "🌧️"),
    65: ("Heavy rain", "🌧️"),
    66: ("Light freezing rain", "🌧️"),
    67: ("Heavy freezing rain", "🌧️"),
    71: ("Slight snow", "🌨️"),
    73: ("Moderate snow", "🌨️"),
    75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "🌨️"),
    80: ("Slight rain showers", "🌦️"),
    81: ("Moderate rain showers", "🌧️"),
    82: ("Violent rain showers", "⛈️"),
    85: ("Slight snow showers", "🌨️"),
    86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"),
    96: ("Thunderstorm w/ slight hail", "⛈️"),
    99: ("Thunderstorm w/ heavy hail", "⛈️"),
}


def _location():
    lat = os.environ.get("WEATHER_LATITUDE", "").strip()
    lon = os.environ.get("WEATHER_LONGITUDE", "").strip()
    place = os.environ.get("WEATHER_PLACE", "").strip() or DEFAULT_PLACE
    try:
        lat = float(lat) if lat else DEFAULT_LAT
        lon = float(lon) if lon else DEFAULT_LON
    except ValueError:
        lat, lon = DEFAULT_LAT, DEFAULT_LON
    return lat, lon, place


def describe(code):
    """Return (text, emoji) for a WMO weather code."""
    return WEATHER_CODES.get(code, ("Unknown", "❓"))


def fetch_weather():
    """
    Fetch current conditions + 3-day forecast for the configured location.

    Returns:
        {
            "success": bool,
            "place": "Waterloo, ON",
            "current": {
                "temp": 12.4, "feels_like": 10.1, "code": 2,
                "description": "Partly cloudy", "emoji": "⛅",
                "wind": 14.2, "humidity": 63
            },
            "forecast": [
                {"date": "2026-06-25", "max": 18.0, "min": 9.0,
                 "code": 3, "description": "Overcast", "emoji": "☁️"},
                ... (3 days)
            ],
            "error": str or None
        }
    """
    lat, lon, place = _location()
    try:
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code",
            "timezone": "auto",
            "forecast_days": 3,
        }
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=10)
        resp.raise_for_status()
        d = resp.json()

        cur = d.get("current", {})
        cur_code = cur.get("weather_code", 0)
        cur_text, cur_emoji = describe(cur_code)

        forecast = []
        daily = d.get("daily", {})
        dates = daily.get("time", [])
        maxs = daily.get("temperature_2m_max", [])
        mins = daily.get("temperature_2m_min", [])
        codes = daily.get("weather_code", [])
        for i in range(len(dates)):
            code = codes[i] if i < len(codes) else 0
            text, emoji = describe(code)
            forecast.append({
                "date": dates[i],
                "max": maxs[i] if i < len(maxs) else None,
                "min": mins[i] if i < len(mins) else None,
                "code": code,
                "description": text,
                "emoji": emoji,
            })

        return {
            "success": True,
            "place": place,
            "current": {
                "temp": cur.get("temperature_2m"),
                "feels_like": cur.get("apparent_temperature"),
                "code": cur_code,
                "description": cur_text,
                "emoji": cur_emoji,
                "wind": cur.get("wind_speed_10m"),
                "humidity": cur.get("relative_humidity_2m"),
            },
            "forecast": forecast,
            "error": None,
        }
    except Exception as e:
        return {"success": False, "place": place, "current": None,
                "forecast": [], "error": str(e)}


def weather_text_summary():
    """Plain-text weather summary for Wendy to fold into a briefing."""
    w = fetch_weather()
    if not w["success"]:
        return f"Could not fetch weather: {w['error']}"
    c = w["current"]
    lines = [
        f"{w['place']}: {c['temp']}°C (feels {c['feels_like']}°C), "
        f"{c['description']}, wind {c['wind']} km/h, humidity {c['humidity']}%."
    ]
    for f in w["forecast"]:
        lines.append(f"  {f['date']}: {f['min']}–{f['max']}°C, {f['description']}")
    return "\n".join(lines)
