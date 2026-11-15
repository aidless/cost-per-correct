"""核心计算：方案成本账、链正确率、方案对比。

口径（全部显式，防「数字不知道从哪来」）：
- 单方案任务成本 = tokens_in/1e6 × price_in + tokens_out/1e6 × price_out（美元）
- cost-per-correct = 任务成本 / 正确率；正确率为 0 → None（unavailable，不进胜负）
- 复合方案：成本 = Σ 步骤成本；正确率 = ∏ 步骤正确率（乘性衰减）
- 对比：cost-per-correct 最小者赢；ratio = 败方 / 胜方
"""
from __future__ import annotations

from typing import Any

# 正确率合法区间：(0, 1]；0 合法但触发 unavailable；>1 或 <0 是配置错误
_ACC_MIN, _ACC_MAX = 0.0, 1.0


def _validate_accuracy(name: str, accuracy: float) -> None:
    """正确率越界直接抛配置错误，绝不静默截断（截断会造出假数字）。"""
    if not isinstance(accuracy, (int, float)) or isinstance(accuracy, bool):
        raise ValueError(f"{name}: accuracy 必须是数值，收到 {accuracy!r}")
    if accuracy < _ACC_MIN or accuracy > _ACC_MAX:
        raise ValueError(f"{name}: accuracy 越界 {accuracy}，合法区间 [0, 1]")


def chain_accuracy(step_accuracies: list[float]) -> float:
    """复合链的正确率：乘性衰减。任一步为 0 则整链为 0。

    为什么是乘法不是平均：路由错一次、校验漏一次，整条链跟着错；
    这是 predictions 审计 C09 给低先验（~30%）的同一笔数学。
    """
    acc = 1.0
    for i, a in enumerate(step_accuracies):
        _validate_accuracy(f"step[{i}]", a)
        acc *= a
    return acc


def _step_cost(step: dict[str, Any]) -> float:
    """一步的成本账：单价按每百万 token，token 数按该步实际用量。"""
    for key in ("price_in_per_1m", "price_out_per_1m", "tokens_in", "tokens_out"):
        if key not in step:
            raise ValueError(f"步骤缺字段 {key}: {step!r}")
    cost = (step["tokens_in"] / 1_000_000 * step["price_in_per_1m"]
            + step["tokens_out"] / 1_000_000 * step["price_out_per_1m"])
    if cost < 0:
        raise ValueError(f"步骤成本为负，检查单价与 token 数: {step!r}")
    return cost


def option_cost_per_correct(opt: dict[str, Any]) -> dict[str, Any]:
    """算一个方案的成本账。

    两种形态二选一：
    - 单体：直接给 price_in_per_1m / price_out_per_1m / tokens_in / tokens_out / accuracy
    - 复合链：给 steps=[每步同上字段]，链正确率乘性衰减、成本累加
    返回：cost_per_task / accuracy / cost_per_correct（None=unavailable）/ verdict_basis
    """
    name = opt.get("name", "<unnamed>")
    if "steps" in opt:
        steps = opt["steps"]
        if not steps:
            raise ValueError(f"{name}: steps 为空")
        cost_per_task = sum(_step_cost(s) for s in steps)
        accuracy = chain_accuracy([s.get("accuracy", 1.0) for s in steps])
    else:
        for key in ("price_in_per_1m", "price_out_per_1m", "tokens_in", "tokens_out", "accuracy"):
            if key not in opt:
                raise ValueError(f"{name}: 缺字段 {key}")
        cost_per_task = _step_cost(opt)
        accuracy = float(opt["accuracy"])
        _validate_accuracy(name, accuracy)

    result: dict[str, Any] = {
        "name": name,
        "cost_per_task": cost_per_task,
        "accuracy": accuracy,
        "cost_per_correct": None,
        "verdict_basis": None,
    }
    if accuracy == 0.0:
        # 正确率为 0：cost-per-correct 数学上无定义，记 unavailable 并排除出胜负，
        # 不折成「无穷贵」——证据缺失 ≠ 最差方案（与预测审计五值判决同一纪律）
        result["verdict_basis"] = "accuracy_zero"
    else:
        result["cost_per_correct"] = cost_per_task / accuracy
        result["verdict_basis"] = "computed"
    return result


def compare_options(
    options: list[dict[str, Any]], min_accuracy: float | None = None
) -> dict[str, Any]:
    """对比多个方案：cost-per-correct 最小者赢。

    两类排除（都不计胜负，只记原因）：
    - 正确率为 0 → excluded_reason=accuracy_zero（unavailable，证据缺失 ≠ 最差）
    - 低于 min_accuracy 底线 → excluded_reason=accuracy_below_floor
      （便宜但更错不算赢：产品对正确率有底线时，cost-per-correct 便宜也过不了验收）
    全部被排除时 winner=None。"""
    if len(options) < 2:
        raise ValueError("至少需要两个方案才能对比")
    if min_accuracy is not None:
        _validate_accuracy("min_accuracy", min_accuracy)
    rows = {option_cost_per_correct(o)["name"]: option_cost_per_correct(o) for o in options}
    if len(rows) != len(options):
        raise ValueError("方案名重复，无法区分")
    for r in rows.values():
        if r["cost_per_correct"] is None:
            r["excluded_reason"] = r["verdict_basis"]
        elif min_accuracy is not None and r["accuracy"] < min_accuracy:
            r["excluded_reason"] = "accuracy_below_floor"
    eligible = [r for r in rows.values()
                if r["cost_per_correct"] is not None and "excluded_reason" not in r]
    winner = None
    ratio = None
    if eligible:
        best = min(eligible, key=lambda r: r["cost_per_correct"])
        winner = best["name"]
        others = [r for r in eligible if r is not best]
        if others:
            loser = max(others, key=lambda r: r["cost_per_correct"])
            ratio = loser["cost_per_correct"] / best["cost_per_correct"]
    return {"winner": winner, "ratio": ratio, "options": rows}
