"""本地 hooks：配置解析、四个事件语义、执行器接线。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from xenon.engine.context import AgentContext
from xenon.hooks.runner import HookRunner
from xenon.nodes import tool_executor as te_mod
from xenon.nodes.tool_executor import ToolExecutor


@pytest.fixture(autouse=True)
def _enable_hooks_for_this_module(monkeypatch):
    """conftest 全局禁用 hooks，本模块需要显式恢复。"""

    monkeypatch.delenv("XENON_HOOKS", raising=False)


def _write_hook(tmp_path: Path, name: str, script: str) -> Path:
    hook = tmp_path / name
    hook.write_text(script, encoding="utf-8")
    if name.endswith(".sh") and sys.platform != "win32":
        hook.chmod(0o755)
    return hook


def _cfg(tmp_path: Path, hooks: dict) -> Path:
    import yaml

    cfg = tmp_path / "hooks.yaml"
    cfg.write_text(yaml.safe_dump({"hooks": hooks}), encoding="utf-8")
    return cfg


def test_malformed_config_is_tolerated(tmp_path):
    (tmp_path / "hooks.yaml").write_text(":::not-yaml", encoding="utf-8")
    runner = HookRunner(user_dir=tmp_path / "hooks.yaml")
    assert runner.run("PreToolUse", "write_file", {}) .blocked is False


def test_pretooluse_allow_and_block(tmp_path):
    allow = tmp_path / "allow.py"
    allow.write_text("import sys; sys.exit(0)", encoding="utf-8")
    block = tmp_path / "block.py"
    block.write_text(
        'import sys; sys.stderr.write("policy says no"); sys.exit(2)',
        encoding="utf-8",
    )
    runner = HookRunner(
        user_dir=_cfg(
            tmp_path,
            {
                "PreToolUse": [
                    {"match": "write_file", "command": f'"{sys.executable}" "{block}"'},
                    {"match": "read_file", "command": f'"{sys.executable}" "{allow}"'},
                ]
            },
        )
    )
    assert runner.run("PreToolUse", "read_file", {}).blocked is False
    outcome = runner.run("PreToolUse", "write_file", {})
    assert outcome.blocked is True
    assert "policy says no" in outcome.message


def test_hook_receives_json_on_stdin(tmp_path):
    marker = tmp_path / "payload.json"
    hook = tmp_path / "capture.py"
    hook.write_text(
        f"import sys, json; json.dump(json.load(sys.stdin), open(r'{marker}', 'w', encoding='utf-8'))",
        encoding="utf-8",
    )
    runner = HookRunner(
        user_dir=_cfg(
            tmp_path,
            {"PostToolUse": [{"match": "*", "command": f'"{sys.executable}" "{hook}"'}]},
        ),
        session_id="s1",
    )
    runner.run("PostToolUse", "write_file", {"file_path": "a.py"})

    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["event"] == "PostToolUse"
    assert payload["tool_name"] == "write_file"
    assert payload["tool_input"] == {"file_path": "a.py"}
    assert payload["session_id"] == "s1"


def test_stop_hook_exit_zero_requests_stop(tmp_path):
    stop = tmp_path / "stop.py"
    stop.write_text("import sys; sys.exit(0)", encoding="utf-8")
    runner = HookRunner(
        user_dir=_cfg(tmp_path, {"Stop": [{"match": "*", "command": f'"{sys.executable}" "{stop}"'}]})
    )
    assert runner.run("Stop", "", {}).stop is True


def test_env_disable(tmp_path):
    import os

    os.environ["XENON_HOOKS"] = "0"
    try:
        runner = HookRunner(user_dir=_cfg(tmp_path, {"Stop": [{"match": "*", "command": "true"}]}))
        assert runner.run("Stop", "", {}).stop is False
    finally:
        os.environ.pop("XENON_HOOKS", None)


class _FakeNode:
    script: list = []

    def __init__(self, name, action_type=None, **params):
        self.action_type = action_type

    @staticmethod
    def normalize_params(p):
        return p

    def execute(self, context):
        if not _FakeNode.script:
            return {"success": True, "content": "default"}
        return _FakeNode.script.pop(0)


def test_executor_blocks_on_pretooluse_exit_2(monkeypatch, tmp_path):
    monkeypatch.setattr(te_mod, "ToolNode", _FakeNode)
    _FakeNode.script = [{"success": True, "content": "ran"}]

    block = tmp_path / "block.py"
    block.write_text("import sys; sys.exit(2)", encoding="utf-8")
    runner = HookRunner(
        user_dir=_cfg(
            tmp_path,
            {"PreToolUse": [{"match": "command", "command": f'"{sys.executable}" "{block}"'}]},
        )
    )

    ctx = AgentContext({"_execution_level": 3})
    result = ToolExecutor(retry_attempts=1, hooks=runner).execute(
        "command", {"command": "echo hi"}, ctx, tools={"command": {}}
    )

    assert result.success is False
    assert "hook 阻断" in result.observation
    assert _FakeNode.script  # 工具体没有执行


def test_project_hooks_require_explicit_trust(tmp_path, monkeypatch):
    """H-5：项目 hooks 未信任前不加载；/trust-hooks 后生效。"""

    monkeypatch.delenv("XENON_HOOKS", raising=False)
    monkeypatch.setenv("XENON_HOOKS_TRUST_STORE", str(tmp_path / "trusted.json"))
    import sys as _sys

    block = tmp_path / "block.py"
    block.write_text(
        'import sys; sys.stderr.write("policy says no"); sys.exit(2)',
        encoding="utf-8",
    )
    proj = _cfg(
        tmp_path,
        {"PreToolUse": [{"match": "write_file", "command": f'"{_sys.executable}" "{block}"'}]},
    )
    runner = HookRunner(project_dir=proj)
    assert runner.project_hooks_pending is True
    # 未信任：hook 未加载，不阻断
    assert runner.run("PreToolUse", "write_file", {}).blocked is False
    # 显式信任后：hook 加载，exit 2 阻断
    assert runner.trust_project_hooks() is True
    assert runner.project_hooks_pending is False
    assert runner.run("PreToolUse", "write_file", {}).blocked is True


def test_project_hooks_content_change_requires_retrust(tmp_path, monkeypatch):
    """指纹绑定内容：文件改了要重新信任。"""

    monkeypatch.delenv("XENON_HOOKS", raising=False)
    monkeypatch.setenv("XENON_HOOKS_TRUST_STORE", str(tmp_path / "trusted.json"))
    proj = _cfg(tmp_path, {"PreToolUse": []})
    runner = HookRunner(project_dir=proj)
    assert runner.trust_project_hooks() is True
    proj.write_text("hooks: {PreToolUse: []}\n", encoding="utf-8")
    runner.reload()
    assert runner.project_hooks_pending is True


def test_pretooluse_timeout_is_fail_closed(tmp_path):
    """H-5：PreToolUse 超时不能当成“同意”——fail-closed 阻断。"""

    import sys as _sys

    slow = tmp_path / "slow.py"
    slow.write_text("import time; time.sleep(5)", encoding="utf-8")
    runner = HookRunner(
        user_dir=_cfg(
            tmp_path,
            {
                "PreToolUse": [
                    {"match": "*", "command": f'"{_sys.executable}" "{slow}"'}
                ]
            },
        ),
        timeout=0.2,
    )
    outcome = runner.run("PreToolUse", "write_file", {})
    assert outcome.blocked is True
    assert "超时" in outcome.message
