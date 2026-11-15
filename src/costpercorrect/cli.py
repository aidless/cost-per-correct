"""命令行入口：读方案 JSON → 对比 → 输出报告 + 退出码。

退出码（学 ttftkit 的门禁语义）：
- 0 有胜者且全部方案 cost-per-correct 可算
- 1 有胜者，但有方案被排除（正确率 0 或低于底线）——可用，带 WARN
- 2 配置错误（JSON 解析失败、缺字段、正确率越界、方案名重复、不足两个方案）
- 3 无胜者（全部方案被排除）
"""
from __future__ import annotations

import argparse
import json
import sys

from .core import compare_options
from . import __version__


def _fmt(x: float | None, digits: int = 6) -> str:
    return "-" if x is None else f"{x:.{digits}f}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="cost-per-correct",
        description="把模型选型从 cost-per-token 纠正为 cost-per-correct",
    )
    p.add_argument("options_json", help="方案列表 JSON 文件（数组，每项见 README 口径）")
    p.add_argument("--min-accuracy", type=float, default=None,
                   help="正确率底线（0-1]，低于它的方案排除出胜负")
    p.add_argument("--json", action="store_true", help="输出机器可读 JSON 而不是表格")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = p.parse_args(argv)

    try:
        with open(args.options_json, encoding="utf-8") as f:
            options = json.load(f)
        report = compare_options(options, min_accuracy=args.min_accuracy)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"[config-error] {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{'方案':<24}{'成本/任务':>12}{'正确率':>10}{'成本/正确':>14}  备注")
        for r in report["options"].values():
            note = r.get("excluded_reason") or ""
            print(f"{r['name']:<24}{_fmt(r['cost_per_task']):>12}{r['accuracy']:>10.4f}"
                  f"{_fmt(r['cost_per_correct']):>14}  {note}")
        if report["winner"] is None:
            print("\nwinner: None（全部方案被排除）")
        else:
            if report["ratio"] is None:
                ratio_note = "唯一可判方案，无对比基线"
            else:
                ratio_note = f"最贵可判方案 / 胜方 = {_fmt(report['ratio'], 2)}×"
            print(f"\nwinner: {report['winner']}  ({ratio_note})")

    if report["winner"] is None:
        return 3
    excluded = [r for r in report["options"].values() if "excluded_reason" in r]
    return 1 if excluded else 0


if __name__ == "__main__":
    sys.exit(main())
