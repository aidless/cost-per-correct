# cost-per-correct

把模型选型的记分牌从 **cost-per-token** 纠正为 **cost-per-correct**：便宜的错误输出是负资产，真正该比的是「每元买到多少正确答案」。

## 为什么不是又一个省钱计算器

选型场景里最常见的错误是把「token 单价低」当成「方案便宜」。两条账经常反向：

- **复合链按乘性衰减**：路由 0.9 × 校验 0.8 → 整链 0.72，不是平均 0.85。长链重试会把省钱优势吃回去——本工具的 `steps` 形态直接按 ∏aᵢ 算，不给你平均的幻觉。
- **便宜但更错不算赢**：`--min-accuracy` 底线闸把低于产品正确率要求的方案排除出胜负——每元正确率再低也过不了验收。

## 口径（全部显式）

| 量 | 定义 |
| --- | --- |
| 任务成本 | `tokens_in/1e6 × price_in + tokens_out/1e6 × price_out`（美元） |
| 链正确率 | ∏ 步骤正确率（乘性；任一步为 0 则整链为 0） |
| cost-per-correct | 任务成本 ÷ 正确率；正确率为 0 → `None`（unavailable，排除出胜负） |
| 胜者 | cost-per-correct 最小的未被排除方案；`ratio` = 最贵可判方案 ÷ 胜方 |

正确率越界（<0 或 >1）、缺字段、负成本、方案名重复 → 配置错误，绝不静默截断。

## 用法

```bash
pip install -e .
```

方案文件（单体直接给字段，复合给 `steps`）：

```json
[
  {"name": "frontier",
   "price_in_per_1m": 3.0, "price_out_per_1m": 15.0,
   "tokens_in": 8000, "tokens_out": 2000, "accuracy": 0.95},
  {"name": "composite",
   "steps": [
     {"price_in_per_1m": 1.0, "price_out_per_1m": 2.0,
      "tokens_in": 1000, "tokens_out": 400, "accuracy": 0.9},
     {"price_in_per_1m": 1.0, "price_out_per_1m": 2.0,
      "tokens_in": 500, "tokens_out": 100, "accuracy": 0.7}]}
]
```

```bash
cost-per-correct options.json                     # 全部可判 → 退出码 0
cost-per-correct options.json --min-accuracy 0.8  # 有方案被排除 → 1
cost-per-correct options.json --json              # 机器可读
cost-per-correct --version
```

退出码：`0` 全部可判且有胜者｜`1` 有胜者但存在被排除方案｜`2` 配置错误｜`3` 全部被排除。可直接接 CI。

## 真实案例（2026-11-10，全部实测数字）

单卡 6GB 私有化部署选型：底模直出 vs QLoRA adapter 挂载。成本侧来自 ttftkit 实弹报告（`ttftkit/results/invariance-2026-11-10/`，1 Hz 功率采样，¥0.6/kWh）；正确率侧来自 `paper_agent/reports/eval_3way_v2.json`（8 样本证据引用率 evd，**离线评测数字，作为在线路线的近似，已声明**）。

```bash
cost-per-correct examples.real-case-2026-11-10.json                # lora-p1v2-c2 胜出，base-awq-c1 每正确贵 13.2×
cost-per-correct examples.real-case-2026-11-10.json --min-accuracy 0.5   # base 两档 accuracy_below_floor 排除，退出码 1
```

| 方案 | 每任务成本 | 正确率 | 每正确成本 |
|---|---|---|---|
| base-awq-c1（底模直出） | ¥0.000238 | 0.125 | ¥0.001905 |
| base-awq-c16（底模批处理） | ¥0.0000232 | 0.125 | ¥0.000186 |
| **lora-p1v2-c2（adapter 挂载）** | ¥0.000144 | 1.0 | **¥0.000144** |

这个案例就是 min_accuracy 底线闸的来历：不加底线时纯看每元正确数，底模批处理档（¥0.000186）逼近 adapter（¥0.000144）；但正确率 0.125 的方案对「要证据引用」的任务根本不达标——底线一上，脏便宜当场出局。

## 正确率从哪来

本工具不测正确率，只消费它。正确率应来自你对同一任务集的实测（两个方案用同一份任务、同一判分脚本），把评测集与判分口径写进你的选型报告——本工具的输出里不带正确率来源时，结论只值一半。

## 测试

```bash
python3 -m pytest tests/ -q   # 16 项，含退出码 0/1/2/3 全语义与 --version
```

## 定位

方法论出处：预测审计 `predictions/ai-second-half-2026`（C08 成本优势的判定口径）。
姊妹件：`ttftkit`（延迟/吞吐回归门禁）——那边量「快不快、稳不稳」，这边量「每元买到多少对」。

上面提到的 `ttftkit/`、`paper_agent/`、`predictions/` 都是作者工作区里的内部件，**未随本仓发布**；本仓只带 `examples.real-case-2026-11-10.json` 这份输入与它的计算结果，读者能复算「同一份输入算出同一张表」，但无法复核这两份输入是怎么测出来的。这一点写在明处，不当成可复现。

## 许可

MIT，见 [LICENSE](LICENSE)。

