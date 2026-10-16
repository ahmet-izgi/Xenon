"""抽样契约测试：分层配额、确定性、留出集排除。

`evals/swebench_select.py` 是可复现子集分数的根基：任何子集结果都必须能由
seed + 数据集内容精确重建；留出集必须与已调优过的样本零重叠，否则对比
测的是"谁见过这套题"而不是框架能力。
"""

from __future__ import annotations

from collections import Counter

from evals import swebench_select

_POOL = [
    {"instance_id": f"{repo.replace('/', '__')}-{i:02d}", "repo": repo}
    for repo, count in {"a/a": 10, "b/b": 5, "c/c": 3, "d/d": 2}.items()
    for i in range(count)
]


def test_selection_is_deterministic():
    assert swebench_select.select(_POOL, 8, 42) == swebench_select.select(_POOL, 8, 42)


def test_selection_is_stratified_proportionally():
    picked = set(swebench_select.select(_POOL, 8, 42)["instance_ids"])
    repos = Counter(row["repo"] for row in _POOL if row["instance_id"] in picked)
    # 20 例池：a/a 占一半 → 8 席给 4；b/b 5/20 → 2；最大余数把剩余 2 席给 c/d
    assert repos == Counter({"a/a": 4, "b/b": 2, "c/c": 1, "d/d": 1})


def test_calibration_subset_is_part_of_selection():
    result = swebench_select.select(_POOL, 8, 42, calibration_size=3)
    assert set(result["calibration_ids"]) <= set(result["instance_ids"])


def test_digest_depends_on_seed_and_ids():
    ids = ["a__a-00", "b__b-01"]
    base = swebench_select.digest("d", "test", 1, ids)
    assert base == swebench_select.digest("d", "test", 1, list(ids))
    assert base != swebench_select.digest("d", "test", 2, ids)
    assert base != swebench_select.digest("d", "test", 1, ["a__a-00"])


def test_exclude_ids_keeps_held_out_sample_disjoint():
    excluded = ["a__a-00", "a__a-01", "b__b-00"]
    remaining = swebench_select.exclude_ids(_POOL, excluded)

    assert not (set(excluded) & {row["instance_id"] for row in remaining})
    assert len(remaining) == len(_POOL) - 3
    # 排除顺序不影响结果（集合语义）
    assert remaining == swebench_select.exclude_ids(_POOL, list(reversed(excluded)))
