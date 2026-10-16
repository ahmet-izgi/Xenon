"""WeatherTool 离线测试。

该模块此前 0% 覆盖：这里全部走 mock HTTP / mock subprocess，不打真实网络。
"""

from __future__ import annotations

import json
import subprocess

import httpx
import pytest

from xenon.utils import weather


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self  # type: ignore[arg-type]
            )

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        self.calls.append((url, headers or {}))
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _payload(temp_c: int = 22, desc: str = "Sunny") -> dict:
    return {
        "current_condition": [
            {
                "temp_C": str(temp_c),
                "FeelsLikeC": str(temp_c + 1),
                "humidity": "40",
                "windspeedKmph": "12",
                "winddir16Point": "N",
                "visibility": "10",
                "uvIndex": "3",
                "precipMM": "0.0",
                "pressure": "1012",
                "weatherDesc": [{"value": desc}],
            }
        ],
        "weather": [
            {
                "maxtempC": str(temp_c + 3),
                "mintempC": str(temp_c - 3),
                "astronomy": [{"sunrise": "06:00 AM", "sunset": "06:30 PM"}],
            }
        ],
    }


# ── 城市解析 ──────────────────────────────────────────────


def test_resolve_city_maps_chinese_trims_and_passes_english():
    assert weather._resolve_city("北京") == "Beijing"
    assert weather._resolve_city(" 上海 ") == "Shanghai"
    assert weather._resolve_city("Berlin") == "Berlin"
    # 未知中文名原样返回（wttr.in 对部分中文可识别）
    assert weather._resolve_city("未知城") == "未知城"


# ── 主路径：HTTP 客户端 ───────────────────────────────────


def test_get_weather_parses_payload_and_builds_url(monkeypatch):
    client = _FakeClient(response=_FakeResponse(_payload(temp_c=22, desc="Sunny")))
    monkeypatch.setattr(weather, "_create_http_client", lambda **kwargs: client)

    info = weather.get_weather("北京")

    assert info["city"] == "北京"
    assert info["resolved_city"] == "Beijing"
    assert info["temperature"] == "22°C"
    assert info["description"] == "晴天"  # 英文描述经映射表转中文
    assert info["max_temp"] == "25°C"
    assert info["min_temp"] == "19°C"
    assert info["sunrise"] == "06:00 AM"
    assert info["via_fallback"] is False

    (url, headers), = client.calls
    assert url == "https://wttr.in/Beijing?format=j1&lang=zh"
    assert headers["Accept-Language"].startswith("zh-CN")


def test_get_weather_sanitises_lang_whitelist(monkeypatch):
    client = _FakeClient(response=_FakeResponse(_payload()))
    monkeypatch.setattr(weather, "_create_http_client", lambda **kwargs: client)

    weather.get_weather("Beijing", lang="../../etc")

    (url, _), = client.calls
    assert url.endswith("?format=j1&lang=zh")


def test_get_weather_url_encodes_unknown_city(monkeypatch):
    client = _FakeClient(response=_FakeResponse(_payload()))
    monkeypatch.setattr(weather, "_create_http_client", lambda **kwargs: client)

    weather.get_weather("未知 城")

    (url, _), = client.calls
    assert "未知 城" not in url
    assert "%E6%9C%AA%E7%9F%A5%20%E5%9F%8E" in url


@pytest.mark.parametrize(
    "error",
    [
        httpx.TimeoutException("timeout"),
        httpx.HTTPStatusError(
            "500",
            request=httpx.Request("GET", "https://wttr.in/x"),
            response=httpx.Response(500, request=httpx.Request("GET", "https://wttr.in/x")),
        ),
        RuntimeError("boom"),
    ],
)
def test_get_weather_falls_back_to_curl_on_failure(monkeypatch, error):
    client = _FakeClient(error=error)
    monkeypatch.setattr(weather, "_create_http_client", lambda **kwargs: client)

    calls: list[tuple] = []

    def fake_curl(url: str, city: str, resolved: str, lang: str) -> dict:
        calls.append((url, city, resolved, lang))
        return {"city": city, "via_fallback": True}

    monkeypatch.setattr(weather, "_get_weather_via_curl", fake_curl)

    info = weather.get_weather("北京")

    assert info == {"city": "北京", "via_fallback": True}
    assert calls == [("https://wttr.in/Beijing?format=j1&lang=zh", "北京", "Beijing", "zh")]


# ── 解析与展示 ────────────────────────────────────────────


def test_parse_wttr_json_prefers_lang_specific_description():
    data = _payload(desc="Sunny")
    data["current_condition"][0]["lang_zh"] = [{"value": "多云"}]

    info = weather._parse_wttr_json(data, "北京", "Beijing", "zh")

    assert info["description"] == "多云"


def test_parse_wttr_json_survives_empty_payload():
    info = weather._parse_wttr_json({}, "X", "X", "zh")

    assert "error" not in info
    assert info["temperature"].endswith("°C")
    assert info["humidity"].endswith("%")


@pytest.mark.parametrize(
    ("temp_c", "expected_item"),
    [
        (35, "短袖T恤"),
        (30, "短袖T恤"),
        (25, "短袖T恤"),
        (20, "长袖衬衫"),
        (15, "薄毛衣/卫衣"),
        (10, "毛衣"),
        (5, "厚毛衣"),
        (0, "保暖内衣"),
        (-5, "加厚保暖内衣"),
    ],
)
def test_clothing_items_thresholds(temp_c, expected_item):
    assert expected_item in weather._get_clothing_items(temp_c)


def test_clothing_advice_has_label_for_extreme_cold():
    assert "极寒天气" in weather._get_clothing_advice(-40)
    assert "酷暑天气" in weather._get_clothing_advice(40)


def test_format_weather_report_renders_sections():
    info = weather._parse_wttr_json(_payload(), "北京", "Beijing", "zh")

    report = weather.format_weather_report(info)

    assert "北京" in report
    assert "穿衣建议" in report
    assert "| 🌡️ 当前温度 |" in report
    assert info["clothing_items"][0] in report


def test_format_weather_report_renders_error():
    assert weather.format_weather_report({"error": "curl 请求超时"}).startswith("❌ 查询失败")


# ── curl 降级路径 ─────────────────────────────────────────


def test_curl_fallback_parses_stdout_and_marks_flag(monkeypatch):
    completed = subprocess.CompletedProcess(
        args=["curl"], returncode=0, stdout=json.dumps(_payload()), stderr=""
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed)

    info = weather._get_weather_via_curl("https://x", "北京", "Beijing", "zh")

    assert info["via_fallback"] is True
    assert info["temperature"] == "22°C"


def test_curl_fallback_reports_nonzero_exit(monkeypatch):
    completed = subprocess.CompletedProcess(args=["curl"], returncode=7, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed)

    info = weather._get_weather_via_curl("https://x", "北京", "Beijing", "zh")

    assert "curl 请求失败" in info["error"]


def test_curl_fallback_reports_bad_json_and_timeout(monkeypatch):
    bad = subprocess.CompletedProcess(args=["curl"], returncode=0, stdout="not json", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: bad)
    assert "格式异常" in weather._get_weather_via_curl("u", "c", "c", "zh")["error"]

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="curl", timeout=20)

    monkeypatch.setattr(subprocess, "run", timeout)
    assert "超时" in weather._get_weather_via_curl("u", "c", "c", "zh")["error"]


def test_curl_fallback_reports_unexpected_exception(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no curl binary")

    monkeypatch.setattr(subprocess, "run", boom)
    assert "失败" in weather._get_weather_via_curl("u", "c", "c", "zh")["error"]


# ── 工具封装 ──────────────────────────────────────────────


def test_weather_tool_execute_wraps_report(monkeypatch):
    host = ["via mock"]
    monkeypatch.setattr(
        weather,
        "get_weather",
        lambda city="Beijing", lang="zh": weather._parse_wttr_json(
            _payload(desc=host[0]), city, city, lang
        ),
    )

    result = weather.WeatherTool().execute("北京")

    assert result["weather_info"]["city"] == "北京"
    assert "穿衣建议" in result["report"]
