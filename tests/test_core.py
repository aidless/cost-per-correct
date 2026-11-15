# cost-per-correct 核心计算测试：先写测试（RED），再写实现（GREEN）
# 精确值逐字复制纪律：断言里的数字来自测试用例本身的设计值，禁止近似
import math
import pytest
from costpercorrect.core import (
    option_cost_per_correct,
    chain_accuracy,
    compare_options,
)


class Test单体方案:
    def test基础账_每百万定价(self):
        # 设计值：in 8k tok @ $3/1M，out 2k tok @ $15/1M，正确率 0.8
        # 任务成本 = 8_000/1e6*3 + 2_000/1e6*15 = 0.024 + 0.030 = 0.054
        # cost-per-correct = 0.054 / 0.8 = 0.0675
        opt = {
            "name": "frontier",
            "price_in_per_1m": 3.0,
            "price_out_per_1m": 15.0,
            "tokens_in": 8000,
            "tokens_out": 2000,
            "accuracy": 0.8,
        }
        r = option_cost_per_correct(opt)
        assert math.isclose(r["cost_per_task"], 0.054, rel_tol=1e-12)
        assert math.isclose(r["cost_per_correct"], 0.0675, rel_tol=1e-12)

    def test正确率为零_返回不可判而非无穷(self):
        opt = {
            "name": "broken",
            "price_in_per_1m": 1.0,
            "price_out_per_1m": 1.0,
            "tokens_in": 1000,
            "tokens_out": 1000,
            "accuracy": 0.0,
        }
        r = option_cost_per_correct(opt)
        assert r["cost_per_correct"] is None
        assert r["verdict_basis"] == "accuracy_zero"

    def test正确率越界_配置错误(self):
        opt = {
            "name": "bad",
            "price_in_per_1m": 1.0,
            "price_out_per_1m": 1.0,
            "tokens_in": 1,
            "tokens_out": 1,
            "accuracy": 1.5,
        }
        with pytest.raises(ValueError):
            option_cost_per_correct(opt)


class Test复合链:
    def test乘性衰减_两步链(self):
        # 设计值：两步 0.9 x 0.9 = 0.81（乘性，不是平均 0.9）
        assert math.isclose(chain_accuracy([0.9, 0.9]), 0.81, rel_tol=1e-12)

    def test链中任一步为零_整链为零(self):
        assert chain_accuracy([0.95, 0.0, 0.99]) == 0.0

    def test复合方案_成本累加正确率相乘(self):
        # 步骤1: in 1000 @ $1/1M, out 100 @ $2/1M, acc 0.9
        #   成本 = 0.001 + 0.0002 = 0.0012
        # 步骤2: in 500 @ $1/1M, out 200 @ $2/1M, acc 0.8
        #   成本 = 0.0005 + 0.0004 = 0.0009
        # 链成本 = 0.0021；链正确率 = 0.9*0.8 = 0.72
        # cost-per-correct = 0.0021 / 0.72 ≈ 0.00291666...
        opt = {
            "name": "composite",
            "steps": [
                {"price_in_per_1m": 1.0, "price_out_per_1m": 2.0,
                 "tokens_in": 1000, "tokens_out": 100, "accuracy": 0.9},
                {"price_in_per_1m": 1.0, "price_out_per_1m": 2.0,
                 "tokens_in": 500, "tokens_out": 200, "accuracy": 0.8},
            ],
        }
        r = option_cost_per_correct(opt)
        assert math.isclose(r["cost_per_task"], 0.0021, rel_tol=1e-12)
        assert math.isclose(r["accuracy"], 0.72, rel_tol=1e-12)
        assert math.isclose(r["cost_per_correct"], 0.0021 / 0.72, rel_tol=1e-12)


class Test方案对比:
    def test便宜但更错_反超判定(self):
        # 单体贵但对：0.054 / 0.95 ≈ 0.056842
        # 复合便宜但乘性衰减：链成本 0.002，链正确率 0.9*0.7=0.63 → 0.003174...
        # 复合赢（这是视频 C08 主张成立的样子）
        a = {"name": "frontier", "price_in_per_1m": 3.0, "price_out_per_1m": 15.0,
             "tokens_in": 8000, "tokens_out": 2000, "accuracy": 0.95}
        b = {"name": "composite", "steps": [
            {"price_in_per_1m": 1.0, "price_out_per_1m": 2.0,
             "tokens_in": 1000, "tokens_out": 400, "accuracy": 0.9},
            {"price_in_per_1m": 1.0, "price_out_per_1m": 2.0,
             "tokens_in": 500, "tokens_out": 100, "accuracy": 0.7},
        ]}
        rep = compare_options([a, b])
        assert rep["winner"] == "composite"
        assert rep["ratio"] == rep["options"]["frontier"]["cost_per_correct"] / rep["options"]["composite"]["cost_per_correct"]

    def test重试吃掉优势_低于正确率底线不得获胜(self):
        # 复合每元正确率更便宜（0.0072 < 0.0568），但链正确率 0.5*0.5=0.25
        # 低于底线 0.6 → 排除出胜负，frontier 胜；无底线时复合反而赢（诚实记录）
        a = {"name": "frontier", "price_in_per_1m": 3.0, "price_out_per_1m": 15.0,
             "tokens_in": 8000, "tokens_out": 2000, "accuracy": 0.95}
        b = {"name": "fragile_chain", "steps": [
            {"price_in_per_1m": 1.0, "price_out_per_1m": 2.0,
             "tokens_in": 1000, "tokens_out": 100, "accuracy": 0.5},
            {"price_in_per_1m": 1.0, "price_out_per_1m": 2.0,
             "tokens_in": 500, "tokens_out": 50, "accuracy": 0.5},
        ]}
        # 无底线：复合赢（这就是 C08 的账——便宜真的占优，哪怕链很脆）
        rep0 = compare_options([a, b])
        assert rep0["winner"] == "fragile_chain"
        assert math.isclose(rep0["options"]["fragile_chain"]["cost_per_correct"],
                            0.0018 / 0.25, rel_tol=1e-12)
        # 有底线：复合被排除，frontier 胜
        rep = compare_options([a, b], min_accuracy=0.6)
        assert rep["winner"] == "frontier"
        assert rep["options"]["fragile_chain"]["accuracy"] == 0.25
        assert rep["options"]["fragile_chain"]["excluded_reason"] == "accuracy_below_floor"

    def test全体低于底线_winner为None(self):
        a = {"name": "a", "price_in_per_1m": 1.0, "price_out_per_1m": 1.0,
             "tokens_in": 1000, "tokens_out": 1000, "accuracy": 0.3}
        b = {"name": "b", "price_in_per_1m": 1.0, "price_out_per_1m": 1.0,
             "tokens_in": 1000, "tokens_out": 1000, "accuracy": 0.2}
        rep = compare_options([a, b], min_accuracy=0.5)
        assert rep["winner"] is None
        assert all(o.get("excluded_reason") == "accuracy_below_floor"
                   for o in rep["options"].values())

    def test正确率为零的方案_不参与胜负_记unavailable(self):
        a = {"name": "ok", "price_in_per_1m": 1.0, "price_out_per_1m": 1.0,
             "tokens_in": 1000, "tokens_out": 1000, "accuracy": 0.5}
        b = {"name": "dead", "price_in_per_1m": 1.0, "price_out_per_1m": 1.0,
             "tokens_in": 1000, "tokens_out": 1000, "accuracy": 0.0}
        rep = compare_options([a, b])
        assert rep["winner"] == "ok"
        assert rep["options"]["dead"]["cost_per_correct"] is None
        assert rep["options"]["dead"]["excluded_reason"] == "accuracy_zero"
