"""OSC-8 可点击路径工具测试，包括已修复的相对路径和重复格式化边界。"""

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
    assert cp._is_likely_path("main.rs")


def test_is_likely_path_rejects_prose_fragments():
    assert not cp._is_likely_path("hello")
    assert not cp._is_likely_path("a/b")
    assert not cp._is_likely_path("either/or")
    assert not cp._is_likely_path("yes/no/maybe")


def test_is_likely_path_accepts_existing_extensionless_relative_path(tmp_path, monkeypatch):
    target = tmp_path / "docs" / "guide" / "setup"
    target.parent.mkdir(parents=True)
    target.write_text("setup instructions", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cp._is_likely_path("docs/guide/setup")
    assert not cp._is_likely_path("docs/guide/missing")


# ── format_output_with_links ─────────────────────────────


def test_format_output_with_links_converts_prefixed_paths():
    out = cp.format_output_with_links("edit /home/u/main.py now")
    assert f"{ESC}]8;;file://" in out
    assert "/home/u/main.py" in out


def test_format_output_with_links_leaves_slash_separated_prose_untouched():
    text = "Choose yes/no/maybe"

    assert cp.format_output_with_links(text) == text


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
    """原已知限制现在应被修复：再次格式化保留原链接且不嵌套。"""

    once = cp.format_output_with_links("see /home/u/main.py")
    twice = cp.format_output_with_links(once)
    assert twice == once


def test_repeated_formatting_links_new_paths_after_existing_links():
    once = cp.format_output_with_links("see /home/u/main.py")
    combined = once + " and /home/u/other.py"

    formatted = cp.format_output_with_links(combined)

    assert formatted.startswith(once)
    assert "other.py" in formatted
    assert cp.format_output_with_links(formatted) == formatted


def test_parameterized_osc8_links_are_preserved_without_double_wrapping():
    link = f"{ESC}]8;id=1;file:///tmp/main.py{ESC}\\/tmp/main.py{ESC}]8;;{ESC}\\"

    assert cp.format_output_with_links(link) == link
    assert cp.format_output_with_links(cp.format_output_with_links(link)) == link


def test_malformed_osc8_sequences_do_not_break_path_formatting():
    malformed_links = (
        f"{ESC}]8;id=1",  # no separator between parameters and URI
        f"{ESC}]8;id=1;not-a-path",  # no string terminator
        f"{ESC}]8;;{ESC}\\",  # a closing marker without an opening link
        f"{ESC}]8;;file://not-a-path{ESC}\\label",  # no closing marker
    )

    for link in malformed_links:
        assert cp.format_output_with_links(link) == link


def test_windows_path_with_line_number_is_converted():
    win = "C:" + chr(92) + "Users" + chr(92) + "a" + chr(92) + "b.py:12"
    out = cp.format_output_with_links("see " + win)
    assert "#L12" in out
    assert not out.split(f"{ESC}\\", 1)[0].endswith(":12")


def test_windows_path_followed_by_sentence_period_is_linked_without_period():
    win = "C:" + chr(92) + "Users" + chr(92) + "a" + chr(92) + "b.py"
    out = cp.format_output_with_links("See " + win + ".")

    assert f"{ESC}]8;;file://" in out
    assert out.endswith(".")
    assert f"{win}{ESC}]8;;" in out


# ── 之前记录的限制 ───────────────────────────────────────


def test_known_limit_bare_relative_paths_are_not_linked():
    """原已知限制现在应被修复：docstring 示例转换并保留行号锚点。"""

    out = cp.format_output_with_links("See src/main.py:42 for details")
    assert f"{ESC}]8;;file://" in out
    assert "#L42" in out
    assert "src/main.py:42" in out


def test_known_limit_windows_path_followed_by_words_is_dropped():
    """原已知限制现在应被修复：后续普通文字不能被路径匹配吞掉。"""

    win = "C:" + chr(92) + "Users" + chr(92) + "a" + chr(92) + "b.py"
    out = cp.format_output_with_links("see " + win + " end")
    assert f"{ESC}]8;;file://" in out
    assert win in out
    assert out.endswith(" end")


def test_windows_path_with_spaces_followed_by_words_is_linked():
    win = "C:" + chr(92) + "Program Files" + chr(92) + "app.py"
    out = cp.format_output_with_links("see " + win + " end")
    assert f"{ESC}]8;;file://" in out
    assert win in out
    assert out.endswith(" end")
