# 算法执行策略（声明与审计）

本文件记录 137 个注册算法的**声明式执行策略**。当前只做声明与审计，**不改变任何现有并发行为**——未真正消费策略去切换实例生命周期。

## 三态定义

| 策略 | 语义 |
|---|---|
| `STATELESS_SHARED` | 无可变实例状态，可跨视频安全共享同一实例 |
| `LOCKED_SHARED` | 有可变实例状态，但已有实例锁保护；共享安全性由锁保证 |
| `PER_VIDEO` | 需按 BVID 生命周期独享实例（**当前只声明，未生效**） |

**未知算法一律按 `LOCKED_SHARED` 处理**——安全默认，绝不默认为无状态共享。

## 落点

- `algorithms/execution_policy.py`：`ExecutionStrategy` 枚举 + `strategy_for()` / `manifest_key()` / 审计辅助。
- `algorithms/execution_policy_manifest.py`：137 项穷尽清单，键 = `module_path.ClassName`（稳定类身份，非 UI 展示名）。
- `algorithms/registry_parts/_models.py`：只读查询接口 `get_execution_strategy()` / `execution_policy_summary()`。

## 当前锁现状（策略归类依据）

- `deep_learning` 全部 42 个算法持可变模型/缓存：torch 路径运行时经 `_prediction_lock`/`_gpu_use_lock` 保护（`torch_upgrade/runtime.py` 惰性挂载）；`cnn_image`/`diffusion_ts` 显式持 `_cache_lock`。故全部标 `LOCKED_SHARED`。
- 其余包（`simple`/`growth`/`statistical`/`ensemble`/`time_series`/`advanced`/`content`/`event`/`frequency`）为局部计算，无长期实例可变状态，标 `STATELESS_SHARED`。

## 边界

- `PER_VIDEO` 仅声明：注册表仍返回共享实例，不下沉实例工厂。
- 本包不改 `algorithms/base.py`、`algorithms/registry.py`、任何算法类文件，不改注册/调度/并发/锁。
- 审计测试 `tests/test_algorithm_execution_policy.py` 守卫：137 全覆盖、无幽灵项、已知有状态模型不得标 `STATELESS_SHARED`、未知默认 `LOCKED_SHARED`、既有锁仍在。

## 后续（真正消费策略的独立包）

- `STATELESS_SHARED`：直接共享实例。
- `LOCKED_SHARED`：共享实例 + 统一执行锁。
- `PER_VIDEO`：按 BVID 生命周期创建与回收实例。
