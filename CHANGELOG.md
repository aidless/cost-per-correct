# 变更记录

## [0.1.0] - 2026-11-19

首次公开发布。

### 包含

- **核心指标**：`option_cost_per_correct` —— 每一条「正确」的期望成本，而不是每 token 成本。
- **三组随仓实测**：real-case（13.21× 成本差）、determinism（2.27× / 2.39×）、lora-determinism（6.46× / 2.70×）。数据在 `examples.*.json`，可逐条复算。
- **`scripts/check_readme.py`**：9 例自检，README 里每个数字与 examples JSON 重算比对，漂移即 CI fail（已接入 GitHub Actions）。
- **16 项测试**，零依赖。
