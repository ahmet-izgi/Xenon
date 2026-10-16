"""REPL 命令套件在 pytest 下运行，让命令层进入 CI 与覆盖率报告。

历史问题：``evals/repl_tasks.yaml`` 只能手动通过 ``evals/runner.py`` 跑，
导致 ``xenon/repl/command_groups/*`` 在 Codecov 上大片空白（19%–70%）。
把套件接进 pytest 后：

* 每个 Python 版本、每次 CI 都会执行所有命令；
* 命令分发路径自动计入 ``--cov=xenon``；
* 任何 slash 命令回归会直接把构建打红，而不是等人工跑评测。
"""

from __future__ import annotations

from evals.runner import DEFAULT_REPL_TASKS_PATH, load_tasks, run_repl_eval


def test_repl_command_suite_tasks_all_pass(tmp_path):
    tasks = load_tasks(DEFAULT_REPL_TASKS_PATH)
    assert len(tasks) >= 4, "REPL command suite should not shrink to nothing"

    results = run_repl_eval(tasks, workdir=str(tmp_path))

    failures = [
        f"{item['task_id']}: {item.get('reason', '')} | "
        f"answer={str(item.get('answer', ''))[:80]}"
        for item in results
        if not item["success"]
    ]
    assert not failures, failures


def test_repl_command_suite_declares_unique_ids():
    tasks = load_tasks(DEFAULT_REPL_TASKS_PATH)
    ids = [task["id"] for task in tasks]
    assert len(ids) == len(set(ids)), f"duplicate task ids: {ids}"
