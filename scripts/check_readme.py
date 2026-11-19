#!/usr/bin/env python3
"""核对 README 里那些"能算出来的数字"是否与本仓代码一致。

为什么需要这个：README 的表格是外人抄数字的地方，而它最典型的腐化方式不是算错，
是**换了示例输入、忘了改表格**——表里那几格看起来精确，实际是上一版残留。
本仓的示例全部随仓发布（`examples.*.json`），所以每个数都该能当场重算。

只核对**可复算**的项（案例表的成本/正确率/每正确成本、胜率比、测试数）。
不核对叙述性判断（"便宜但更错不算赢"这种），那是人写的，脚本没有资格改。

`--selftest` 用注入样本证明三件事：① 数字漂移必须报；② 干净 README 必须放行；
③ 别处表格里长得像的行**不许**被当成案例表。

退出码：0 = 全部一致；1 = 有不一致；2 = 用法错（示例文件缺失等）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
SRC = ROOT / "src"

# 三个案例表的行：| 方案名... | 成本 | 正确率 | 每正确成本 |
# 表格行：| 方案（含说明） | 成本 | 正确率 | 每正确成本 |
ROW = re.compile(r"^\| (.+?) \| (.+?) \| (.+?) \| (.+?) \|", re.M)
TESTCOUNT = re.compile(r"(\d+) 项[，,]")

# 三个案例：模型名 → (成本, 正确率, 每正确成本)
CASES: dict[str, tuple[str, str, str, dict]] = {}


def _load(name: str) -> dict:
    p = ROOT / name
    if not p.exists():
        raise SystemExit(f"缺示例文件 {name}，无法复算")
    raw = json.loads(p.read_text())
    return {o["name"]: o for o in raw}


def _import_core():
    sys.path.insert(0, str(SRC))
    from costpercorrect.core import option_cost_per_correct, compare_options

    return option_cost_per_correct, compare_options


def actual() -> dict:
    """从随仓示例重算 README 里引用的每一个数。"""
    option_cost_per_correct, compare_options = _import_core()

    out: dict[str, object] = {}

    # 案例一：真实部署选型
    real = _load("examples.real-case-2026-11-10.json")
    rows1 = {n: option_cost_per_correct(o) for n, o in real.items()}
    cmp1 = compare_options(list(real.values()))
    out["case1"] = rows1
    out["case1_ratio"] = cmp1["ratio"]

    # 案例二：确定性（2.27×）
    det = _load("examples.determinism-2026-11-19.json")
    rows2 = {n: option_cost_per_correct(o) for n, o in det.items()}
    out["case2"] = rows2
    out["case2_ratio"] = compare_options(list(det.values()))["ratio"]
    out["case2_cost_ratio"] = (
        rows2["awq-c16-flag1"]["cost_per_task"] / rows2["awq-c16-flag0"]["cost_per_task"]
    )

    # 案例三：确定性 + 适应能力（6.46× / 2.70×）
    lora = _load("examples.lora-determinism-2026-11-19.json")
    rows3 = {n: option_cost_per_correct(o) for n, o in lora.items()}
    cmp3 = compare_options(list(lora.values()))
    out["case3"] = rows3
    out["case3_ratio"] = cmp3["ratio"]
    # 「最贵的那一档每正确只要 X，比最便宜的（按任务成本）便宜 2.70×」
    # = 成本最低那档的每正确成本 / 全局最低每正确成本
    cheapest_cost = min(rows3.values(), key=lambda r: r["cost_per_task"])
    out["case3_price_ratio"] = cheapest_cost["cost_per_correct"] / min(
        r["cost_per_correct"] for r in rows3.values()
    )

    # 测试数（README 写「16 项」）
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-o", "addopts=", "-q"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    m = re.search(r"(\d+) tests? collected", collected)
    out["tests"] = int(m.group(1)) if m else -1

    return out


def _fmt(v: float, places: int) -> str:
    """按 README 的呈现精度格式化（成本 6 位、正确率 4 位）。"""
    return f"{v:.{places}f}"


def compare(text: str, got: dict) -> list[str]:
    """纯函数：给定 README 文本与实测数字，返回不一致项。空列表 = 一致。

    抽成纯函数是为了能对"注入过错误的文本"跑同一套判据 —— 门要能红，
    就得能在不碰真 README 的前提下被喂坏输入。
    """
    problems: list[str] = []

    # ---- 测试数 ----
    m = TESTCOUNT.search(text)
    if not m:
        problems.append("找不到测试数（「N 项，含退出码…」的措辞，改了就同步更新匹配式）")
    elif int(m.group(1)) != got["tests"]:
        problems.append(f"测试数：README 写 {m.group(1)}，pytest 实测 {got['tests']}")

    def check_table(
        section: str, cases: dict, key: str, cost_places: int, acc_places: int,
        cost_label: str, acc_label: str, cpc_label: str,
    ) -> None:
        """核对一个案例表的每一行。"""
        for name, row in cases.items():
            # 用原始浮点值比，不用 _fmt 后的展示串：README 的 base-awq-c16 成本写
            # 0.0000232（7 位小数），而 6 位格式化会得到 0.000023 —— 拿展示串当真值
            # 会把"更精确的写法"误判成漂移。展示串只用于报错信息。
            real_cost = row["cost_per_task"]
            real_acc = row["accuracy"]
            real_cpc = row["cost_per_correct"]
            hit = None
            for mrow in ROW.finditer(text):
                if name in mrow.group(1):
                    hit = mrow
                    break
            if hit is None:
                problems.append(f"{section}：表格里找不到 `{name}`")
                continue
            written_cost, written_acc, written_cpc = hit.group(2), hit.group(3), hit.group(4)
            # 表格里的数可能带货币符号或加粗，剥掉再比
            for label, written_raw, real_str in [
                (cost_label, written_cost, real_cost),
                (acc_label, written_acc, real_acc),
                (cpc_label, written_cpc, real_cpc),
            ]:
                written = written_raw.replace("¥", "").replace("**", "").strip()
                real = real_str
                try:
                    val = float(written)
                except ValueError:
                    problems.append(f"{section} `{name}` {label}：README 写 {written_raw!r}，不是数")
                    continue
                # 容差取「写出小数位的半格」：写 6 位就容 5e-7，写 1 位就容 0.05。
                # 用固定相对容差会把「最后一位抄错」当成一致（自证注入就红不了）。
                dec = len(written.split(".")[1]) if "." in written else 0
                tol = 0.5 * 10 ** (-dec) if dec else 1e-9
                if abs(val - real) > tol:
                    problems.append(
                        f"{section} `{name}` {label}：README 写 {written}，重算 {real:.8g}"
                    )

    check_table("真实案例表", got["case1"], "case1", 6, 3, "每任务成本", "正确率", "每正确成本")
    check_table("确定性表", got["case2"], "case2", 6, 2, "每任务成本", "接受度", "每正确成本")
    check_table("第三案例表", got["case3"], "case3", 6, 4, "成本/任务", "正确率", "成本/正确")

    # ---- 比值句：每个比值用专属匹配式，不用位置索引（位置会随文本增删漂移）----
    def ratio_check(pattern: re.Pattern, real: float, label: str,
                    tolerance: float = 0.02) -> None:
        ms = list(pattern.finditer(text))
        if not ms:
            problems.append(f"找不到{label}（匹配式没命中，改了措辞就同步更新）")
            return
        w = float(ms[-1].group(1))
        if abs(w - real) > tolerance:
            problems.append(f"{label}：README 写 {w}×，重算 {real:.2f}×")

    ratio_check(
        re.compile(r"每正确贵 (\d+\.\d+)×"), got["case1_ratio"],
        "真实案例的「每正确贵 N×」",
    )
    ratio_check(
        re.compile(r"买可复现要贵 (\d+\.\d+)×"), got["case2_ratio"],
        "确定性案例的「贵 N×」",
    )
    ratio_check(
        re.compile(r"成本比 (\d+\.\d+)×"), got["case2_cost_ratio"],
        "确定性案例的「成本比 N×」",
    )
    ratio_check(
        re.compile(r"胜方 = (\d+\.\d+)×"), got["case3_ratio"],
        "第三案例的「最贵可判方案 / 胜方 = N×」",
    )
    ratio_check(
        re.compile(r"便宜 \*{0,2}(\d+\.\d+)×\*{0,2}"), got["case3_price_ratio"],
        "第三案例的「便宜 N×」",
    )

    return problems


def _selftest() -> int:
    got = {
        "case1": {
            "base-awq-c1": {"cost_per_task": 0.00023814, "accuracy": 0.125, "cost_per_correct": 0.00190512},
            "base-awq-c16": {"cost_per_task": 2.322e-05, "accuracy": 0.125, "cost_per_correct": 0.00018576},
            "lora-p1v2-c2": {"cost_per_task": 0.00014421, "accuracy": 1.0, "cost_per_correct": 0.00014421},
        },
        "case1_ratio": 13.21,
        "case2": {
            "awq-c16-flag0": {"cost_per_task": 0.0499122, "accuracy": 0.95, "cost_per_correct": 0.05253916},
            "awq-c16-flag1": {"cost_per_task": 0.1192752, "accuracy": 1.0, "cost_per_correct": 0.1192752},
        },
        "case2_ratio": 2.27,
        "case2_cost_ratio": 2.39,
        "case3": {
            "base-awq-c16-flag0": {"cost_per_task": 0.0499068, "accuracy": 0.125, "cost_per_correct": 0.3992544},
            "base-awq-c16-flag1": {"cost_per_task": 0.1192698, "accuracy": 0.125, "cost_per_correct": 0.9541584},
            "lora-p1v2-c16-flag1": {"cost_per_task": 0.1478088, "accuracy": 1.0, "cost_per_correct": 0.1478088},
        },
        "case3_ratio": 6.46,
        "case3_price_ratio": 2.70,
        "tests": 16,
    }

    good = (
        "## 测试\n\n```bash\npython3 -m pytest tests/ -q   # 16 项，含退出码 0/1/2/3 全语义\n```\n\n"
        "## 真实案例\n\n"
        "| 方案 | 每任务成本 | 正确率 | 每正确成本 |\n"
        "|---|---|---|---|\n"
        "| base-awq-c1 | ¥0.000238 | 0.125 | ¥0.001905 |\n"
        "| base-awq-c16 | ¥0.0000232 | 0.125 | ¥0.000186 |\n"
        "| lora-p1v2-c2 | ¥0.000144 | 1.0 | ¥0.000144 |\n\n"
        "base-awq-c1 每正确贵 13.2×\n\n"
        "## 确定性\n\n"
        "| 方案 | 每任务成本 | 接受度 | 每正确成本 |\n"
        "|---|---|---|---|\n"
        "| awq-c16-flag0 | 0.049912 | 0.95 | 0.052539 |\n"
        "| awq-c16-flag1 | 0.119275 | 1.00 | 0.119275 |\n\n"
        "买可复现要贵 2.27×，成本比 2.39×（c=16）\n\n"
        "## 第三案例\n\n"
        "| 方案 | 成本/任务 | 正确率 | 成本/正确 |\n"
        "|---|---|---|---|\n"
        "| base-awq-c16-flag0 | 0.049907 | 0.1250 | 0.399254 |\n"
        "| base-awq-c16-flag1 | 0.119270 | 0.1250 | 0.954158 |\n"
        "| lora-p1v2-c16-flag1 | 0.147809 | 1.0000 | 0.147809 |\n\n"
        "最贵可判方案 / 胜方 = 6.46×，最贵那档反而便宜 **2.70×**\n"
    )

    cases: list[tuple[str, str, bool, str]] = []
    cases.append(("干净文本", good, False, "合规输入必须放行"))
    cases.append(("测试数漂移", good.replace("16 项", "18 项"), True, "测试数漂移必须报"))
    cases.append(("案例一成本漂移", good.replace("¥0.000238", "¥0.000239"), True, "成本格漂移必须报"))
    cases.append(("案例二接受度漂移", good.replace("| 0.95 |", "| 0.96 |"), True, "正确率格漂移必须报"))
    cases.append(("比值漂移", good.replace("贵 2.27×", "贵 2.50×"), True, "比值漂移必须报"))
    cases.append(("第三案例 cpc 漂移", good.replace("0.399254", "0.399255"), True, "每正确成本漂移必须报"))

    # 不许乱红之一：别的表格里的行（不是案例表的模型名）不许被当成案例行
    noisy = good.replace(
        "最贵可判方案 / 胜方 = 6.46×",
        "| some-other-model | 1.0 | 2.0 | 3.0 |\n\n最贵可判方案 / 胜方 = 6.46×",
    )
    cases.append(("别的表里有无关模型行", noisy, False, "不在案例表里的模型名不报"))

    # 不许乱红之二：正文提到但表格没写的模型名，不该报「找不到」
    prose = good.replace(
        "最贵可判方案 / 胜方 = 6.46×",
        "另有 qwen3-8b 与 gpt-4o 参与过早期对比，未随本表列出。\n最贵可判方案 / 胜方 = 6.46×",
    )
    cases.append(("正文提到表格外的模型", prose, False, "正文提及不等于表内声明"))

    fails: list[str] = []
    for name, text, expect_bad, why in cases:
        problems = compare(text, got)
        if bool(problems) != expect_bad:
            fails.append(
                f"{name}（期望{'红' if expect_bad else '绿'}，实际 {problems or '绿'}；{why}）"
            )
        else:
            print(f"  ✓ {name}：{'红了' if expect_bad else '放行'} —— {why}")

    # 真实 README 必须通过
    real_problems = compare(README.read_text(), got)
    if real_problems:
        fails.append(f"真实 README 与实测不一致：{real_problems[:3]}")
    else:
        print("  ✓ 真实 README：三个案例表与五个比值全部重算一致")

    if fails:
        print(f"\n✗ selftest {len(fails)} 条不通过：")
        for f in fails:
            print("  " + f)
        return 1
    red = len([c for c in cases if c[2]])
    green = len([c for c in cases if not c[2]]) + 1
    print(f"\n✓ selftest 全通过（{red + green} 例：{red} 条必红 + {green} 条必绿）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="核对 README 数字是否与本仓示例一致")
    ap.add_argument("--selftest", action="store_true", help="非空性反证自测")
    ap.add_argument("--readme", default=str(README))
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    try:
        got = actual()
    except SystemExit as e:
        print(str(e))
        return 2

    text = Path(args.readme).read_text()
    summary = {
        "tests": got["tests"],
        "case1_ratio": round(got["case1_ratio"], 2),
        "case2_ratio": round(got["case2_ratio"], 2),
        "case2_cost_ratio": round(got["case2_cost_ratio"], 2),
        "case3_ratio": round(got["case3_ratio"], 2),
        "case3_price_ratio": round(got["case3_price_ratio"], 2),
    }
    print("实测：" + json.dumps(summary, ensure_ascii=False))

    problems = compare(text, got)
    if problems:
        print("\nREADME 与代码不一致：")
        for p in problems:
            print("  ✗ " + p)
        return 1
    print("README 数字全部可复算。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
