# cost-per-correct

把模型选型的记分牌从 **cost-per-token** 纠正为 **cost-per-correct**：便宜的错误输出是负资产，真正该比的是「每元买到多少正确答案」。
> 本文档里的可复算数字由 `scripts/check_readme.py` 机检：README 漂移即 fail build（`--selftest` 含必红 + 必绿反证）。


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

## 第二个案例：确定性不是免费的（2026-11-19，实测）

同一个模型（Qwen3-4B-AWQ）、同一台机（RTX 3060 6GB）、同一份 prompt 集，只改 vLLM 的
`VLLM_BATCH_INVARIANT`。成本单位换成 **GPU 分钟 / 1M output tokens**——本工具只做算术，
单位由你给（¥、GPU-min、kWh 都行），这里换成 GPU-min 是为了不引入未测量的功率。

```bash
cost-per-correct examples.determinism-2026-11-19.json      # flag0 胜出，买可复现要贵 2.27×
```

| 方案 | 每任务成本（GPU-min） | 接受度 | 每正确成本 | 备注 |
|---|---|---|---|---|
| `awq-c16-flag0`（默认） | 0.049912 | 0.95 | **0.052539** | 分歧 2/40 = 0.050 |
| `awq-c16-flag1` | 0.119275 | 1.00 | 0.119275 | 分歧 0/40 |

两个关键口径，缺一个这张表就是错的：

1. **accuracy 这里不是模型正确率，是「逐字节可复现接受度」= 1 − 分歧率**。flag 只改解码 kernel
   的归约顺序，不改模型、不改量化、不改权重——离线正确率两档相同（本题用 0.125 的底模不参与比较），
   变的只有「同一 batch 形态是否给同一串字节」。所以这里比的是**验收口径**，不是模型能力。
2. **成本比 2.39×（c=16）而不是「性能数字」**：吞吐 180.33 → 75.46 tok/s，折 92.43 → 220.88
   GPU-min/1M；c=1 档更贵（1080.09 → 2904.20，2.69×），因为小 batch 吃不满不变性 kernel 的固定开销。

结论怎么用：**cost-per-correct 只负责给「确定性」标价（2.27×），不负责决定该不该买**。
如果验收里有一条「同输入必须同输出」（回归比对、审计留痕、缓存命中），这 2.27× 是买那份可复现；
如果没有这一条，默认档就是便宜的正确答案。数字来自
`ttftkit/results/invariance-2026-11-10/verdict-queries40-pair.md`，可复算。

## 第三个案例：确定性 + 适应能力一起买，反而更便宜（2026-11-19，实测）

同一底物（RTX 3060 6GB / vLLM 0.33.0 / Qwen3-4B-AWQ / `--enforce-eager`）、同一批 40 条 query、`temperature=0.7 seed=1234`。三档的服务端配置不同，**正确率用任务口径**（离线评测 `evd`），不是分歧率：

| 方案 | 成本/任务 | 正确率 | 成本/正确 |
|---|---|---|---|
| `base-awq-c16-flag0` | 0.049907 | 0.1250 | **0.399254** |
| `base-awq-c16-flag1` | 0.119270 | 0.1250 | 0.954158 |
| `lora-p1v2-c16-flag1` | 0.147809 | 1.0000 | **0.147809** |

```bash
python3 -m costpercorrect.cli examples.lora-determinism-2026-11-19.json
# winner: lora-p1v2-c16-flag1  (最贵可判方案 / 胜方 = 6.46×)
```

读法三条：

1. **正确率压过成本**。最贵的那一档（0.1478/任务）每正确只要 0.1478，比最便宜的（0.0499/任务、正确率 0.125）便宜 **2.70×**。单价看反了，结论就反了。
2. **确定性自己买不到正确率**。`flag0 → flag1` 成本涨 2.39×、正确率一动不动（0.125 → 0.125）——这一档是纯支出，值不值取决于「可复现」对你的用途值多少钱，不取决于正确率。
3. **同一份输入必须带同一份口径**。`--min-accuracy 0.5` 会把两档底模判 `accuracy_below_floor`（退出码 1），只剩唯一可判方案、无对比基线；这是有意的：低于底线的方案不该靠「便宜」赢。

**这一格买到的东西有代价，写在同一张表外面**：这组配置的延迟闸不过——c=16 TTFT p99 1597.5 ms（上限 2000，勉强过）、c=4 TTFT p99 4752.3 ms（不过）、TPOT p99 259–261 ms（上限 200，不过）。cost-per-correct 只回答「每单位正确花多少」，不回答「用户等不等得起」；后者归 `ttftkit` 的 limits 闸。两把尺分开用，别互相顶替。

## 第四个案例：DPO 相对 SFT 的每正确成本（2026-11-20，实测）

两个 adapter **逐字节同结构**（r=32 / alpha=16 / 七层 / 264308896 B），所以推理单价完全相同
（273.72 GPU分钟/1M out tok，来源 `ttftkit/results/invariance-2026-11-10/verdict-queries40-lora.md`）。
差异只在正确率——而正确率的口径这次换了：**三合一合规率**（有证据 ∧ 无循环复读 ∧ 阶段符合），
不是单看 evd。

| 方案 | tokens_out | accuracy（三合一） | 成本/任务 | 成本/正确 |
|---|---|---|---|---|
| base-awq-c16-flag1 | 603 | 0/8 = 0.000 | 0.165053 | — （accuracy_zero，不可判） |
| sft-p1v2-adapter | 282 | 2/8 = 0.250 | 0.077189 | 0.308756 |
| dpo-p2-adapter | 303 | 5/8 = 0.625 | 0.082937 | **0.132699** |

`winner: dpo-p2-adapter (最贵可判方案 / 胜方 = 2.33×)`

**为什么换口径才看得见 DPO 的价值**：单看 evd，SFT 和 DPO 都是 0.75，持平，看不出任何增益。
DPO 的全部增益在**循环复读从 6/8 降到 3/8**。只有把「无复读」并进正确率定义，
这笔增益才会体现在每正确成本上（2.33×）。这正是本工具的意义：**正确率怎么定义，决定谁赢**。

三条边界（与评测报告一致，不放大）：
1. **分母是 8 条生成样本**，三合一合规率一个样本翻转就是 12.5pp。2.33× 只能当方向性信号。
2. **base 的 accuracy=0 是不可判不是零成本**：它一条都不达标，谈不上「每正确多少钱」，被排除而非记为便宜。
3. **stage 那一轴本身不干净**（见 `paper_agent/notes/2026-11-20-stage-drop-triage.md`：200 token 截断冒充能力退化），
   把它并进三合一是保守选择——若剔除 stage，SFT/DPO 的差距会更大而不是更小。

```bash
PYTHONPATH=src python3 -m costpercorrect.cli examples.dpo-vs-sft-2026-11-20.json
```

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

