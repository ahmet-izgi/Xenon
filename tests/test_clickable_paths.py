"""OSC-8 可点击路径工具测试（此前 0% 覆盖）。

测试按**当前实现行为**编写；两处已知限制用显式用例钉住，便于将来修复时
翻转：模块 docstring 声称 ``src/main.py:42`` 会被自动转换，但实际只转换
``/``、``./``、``~/`` 前缀路径与 Windows 盘符路径；Windows 路径后跟
``空格+单词``时会被正则吞掉而放弃转换。
"""

from __future__ import annotations

from xenon.repl import clickable_paths as cp

ESC = "\033"


# ── make_clickable ───────────────────────────────────────


def test_make_clickable_wraps_path_in_osc8():
    link = cp.make_clickable("src/main.py")
    assert link.startswith(f"{ESC}]8;;file://")
    assert link.endswith(f"{ESC}]8;;{ESC}\\")
    assert "src/main.py" in link
    assert "#L" not in link


def test_make_clickable_adds_line_anchor_and_custom_display():
    link = cp.make_clickable("src/main.py", line=42, display="main.py")
    assert "#L42" in link
    assert link.index("main.py") > link.index("file://")


def test_make_clickable_url_encodes_special_characters():
    link = cp.make_clickable("dir with space/a b.py")
    assert "%20" in link
    assert "dir with space/a b.py" in link  # 显示文本保持原样


# ── 路径判定 ─────────────────────────────────────────────


def test_is_likely_path_accepts_absolute_home_relative_and_code_files():
    assert cp._is_likely_path("/tmp/x.py")
    assert cp._is_likely_path("~/notes.txt")
    assert cp._is_likely_path("./src/app.py")
    assert cp._is_likely_path("../sibling/app.py")
    assert cp._is_likely_path("docs/guide/setup")
    assert cp._is_likely_path("main.rs")


def test_is_likely_path_rejects_prose_fragments():
    assert not cp._is_likely_path("hello")
    assert not cp._is_likely_path("a/b")
    assert not cp._is_likely_path("either/or")


# ── format_output_with_links ─────────────────────────────


def test_format_output_with_links_converts_prefixed_paths():
    out = cp.format_output_with_links("edit /home/u/main.py now")
    assert f"{ESC}]8;;file://" in out
    assert "/home/u/main.py" in out


def test_format_output_with_links_parses_line_number_for_unix_paths():
    out = cp.format_output_with_links("see /home/u/main.py:42")
    assert "#L42" in out
    # 行号保留在链接内（display 为原始 path）
    assert "/home/u/main.py:42" in out


def test_format_output_with_links_converts_dot_relative_and_home():
    for raw in ("./src/main.py", "~/notes.txt"):
        out = cp.format_output_with_links(f"look at {raw} please")
        assert f"{ESC}]8;;file://" in out, raw


def test_format_output_with_links_keeps_code_blocks_untouched():
    text = "before /abs/before.py\n```\n/abs/inside.py\n```\nafter /abs/after.py"
    out = cp.format_output_with_links(text)
    inside = [line for line in out.splitlines() if "inside.py" in line][0]
    assert ESC not in inside
    assert ESC in out  # 代码块外的路径照常转换


def test_format_output_with_links_empty_text_is_returned_as_is():
    assert cp.format_output_with_links("") == ""


def test_known_limit_repeated_formatting_double_wraps():
    """对已格式化文本再跑一次会重复包链接（实现未做幂等保护）。"""

    once = cp.format_output_with_links("see /home/u/main.py")
    twice = cp.format_output_with_links(once)
    assert twice != once


def test_windows_path_with_line_number_is_converted():
    win = "C:" + chr(92) + "Users" + chr(92) + "a" + chr(92) + "b.py:12"
    out = cp.format_output_with_links("see " + win)
    assert f"{ESC}]8;;file://" in out


# ── 已知限制（修复后应翻转这两个用例）─────────────────────


def test_known_limit_bare_relative_paths_are_not_linked():
    """docstring 的例子 ``src/main.py:42`` 实际不转换（正则要求 / ./ ~/ 前缀）。"""

    out = cp.format_output_with_links("See src/main.py:42 for details")
    assert ESC not in out


def test_known_limit_windows_path_followed_by_words_is_dropped():
    """Windows 分支的字符类包含空格，会吞掉后续单词导致判定为非路径。"""

    win = "C:" + chr(92) + "Users" + chr(92) + "a" + chr(92) + "b.py"
    out = cp.format_output_with_links("see " + win + " end")
    assert ESC not in out
