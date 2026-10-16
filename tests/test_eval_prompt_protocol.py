"""SWE-bench 任务提示词协议：默认不得向 Agent 泄露评测元数据。

背景：v0.8.3（commit 891a863）起适配器把 FAIL_TO_PASS 测试名注入 prompt，
2026-10-16 协议审计确认为泄漏（标准 SWE-bench 协议只给 issue 描述）。
现默认关闭；``XENON_EVAL_FAIL_HINT=1`` 保留旧口径以复现历史对照。
"""

from __future__ import annotations

import pytest

try:
    from evals.swebench_xenon import _prompt
except ModuleNotFoundError as exc:  # pragma: no cover - 取决于可选依赖
    if "datasets" in str(exc):
        pytest.skip("requires datasets (SWE-bench harness)", allow_module_level=True)
    raise


_INSTANCE = {
    "instance_id": "owner__repo-1234",
    "problem_statement": "Fix the frobnicator offset bug.",
    "FAIL_TO_PASS": [
        "tests/test_frob.py::test_offset",
        "tests/test_frob.py::test_negative",
        "tests/test_frob.py::test_roundtrip",
        "tests/test_frob.py::test_extra",
    ],
    "PASS_TO_PASS": ["tests/test_ok.py::test_baseline"],
    "test_patch": (
        "diff --git a/tests/test_frob.py b/tests/test_frob.py\n"
        "+def test_offset():\n+    assert True\n"
    ),
}


def test_prompt_hides_eval_metadata_by_default(monkeypatch):
    monkeypatch.delenv("XENON_EVAL_FAIL_HINT", raising=False)

    prompt = _prompt(_INSTANCE)

    assert _INSTANCE["problem_statement"] in prompt
    assert "test_offset" not in prompt
    assert "FAIL_TO_PASS" not in prompt
    assert "PASS_TO_PASS" not in prompt
    assert "test_patch" not in prompt


@pytest.mark.parametrize("value", ["0", "false", "off", ""])
def test_prompt_hint_disabled_values(monkeypatch, value):
    monkeypatch.setenv("XENON_EVAL_FAIL_HINT", value)

    assert "test_offset" not in _prompt(_INSTANCE)


def test_prompt_legacy_fail_hint_is_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("XENON_EVAL_FAIL_HINT", "1")

    prompt = _prompt(_INSTANCE)

    # 只取前 3 个测试名；第四项不应出现
    assert "test_offset" in prompt
    assert "test_negative" in prompt
    assert "test_roundtrip" in prompt
    assert "test_extra" not in prompt
    # 即便开启提示，也不得泄露 test_patch / PASS_TO_PASS
    assert "test_patch" not in prompt
    assert "PASS_TO_PASS" not in prompt
