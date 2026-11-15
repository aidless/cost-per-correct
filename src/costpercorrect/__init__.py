"""cost-per-correct：把「哪个模型方案便宜」量成「哪个方案每元买到更多正确答案」。

设计依据：predictions/ai-second-half-2026/claims.yaml C08 的判定口径
（cost-per-correct ≤ 单体前沿的 1/2，双载体）。核心纪律：
- 记分牌是 cost-per-correct，不是 cost-per-token——便宜的错误输出是负资产；
- 复合链的正确率按乘性衰减（∏aᵢ），不是平均——长链重试会把省钱优势吃回去；
- 正确率为 0 的方案记 unavailable 并排除出胜负，不计为「最贵」。
"""
from .core import chain_accuracy, compare_options, option_cost_per_correct

__all__ = ["chain_accuracy", "compare_options", "option_cost_per_correct"]
__version__ = "0.1.0"
