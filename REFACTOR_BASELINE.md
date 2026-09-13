# 重构前基线（Refactor Baseline）

> 用途：重构的"改动前"参照。每完成一个改动单元后重跑下列命令，与本文档对比。
> 运行环境：conda **`bili`**（`C:\ProgramData\anaconda3\envs\bili\python.exe`，Python 3.10.20 / Anaconda）——**唯一允许的环境**。
> 分支：`refactor/optimization`（基线记录时与之等价）

## 1. 测试

```bash
python -m pytest tests/ -q
```
结果：**115 passed**，4 warnings，28.54s。

## 2. 静态检查（flake8）

```bash
python -m flake8 . --count --statistics
```
结果：**959** 项。主要构成：
- `F401` 未使用导入 **527**
- `F841` 未使用变量 **84**
- `C901` 复杂函数 **39**
- `E402` 37 · `E121/E126/E127` 缩进类 108 · `F811` 13 · **`F821` 未定义名 3**（必须归零）· `W391` 13 · `W504` 4

## 3. 圈复杂度（radon cc）

```bash
python -m radon cc -s .
```
结果：**30 个函数 CC>15**。顶部热点：

| CC | 函数 |
|---|---|
| 52 | `algorithms/registry.py::_prepare_video_data` |
| 50 | `_torch_upgrade.py::try_torch_predict` |
| 45 | `scripts/characterize_algorithms.py::diff_cmd` |
| 40 | `ui/snapshot_tab.py::SnapshotBarChart.paintEvent` |
| 38 | `ui/prediction_accuracy.py::_load_data` |
| 36 | `ui/settings_window.py::_persist_settings` |
| 34 | `core/smart_alert.py::detect_paid_promotion_scored` |
| 31 | `algorithms/training/trainer.py::_train_one` |

## 4. 可维护性指数（radon mi）

```bash
python -m radon mi -s -n B .
```
结果：**17 个文件 MI<B**：

```
algorithms/registry.py                  C 0.00
algorithms/models/deep_learning/_torch_upgrade.py  C 0.00
ui/training_panel.py                    C 0.00
ui/danmaku_analysis.py                  C 2.92
ui/snapshot_tab.py                      C 5.81
ui/finetune_panel.py                    C 8.47
ui/milestone_stats.py                   C 8.93
ui/main_gui_events.py                   B 9.47
ui/database_query.py                    B 10.83
ui/crossover_analysis.py                B 11.98
ui/prediction_panel.py                  B 12.42
ui/detail_panel.py                      B 14.02
core/smart_alert.py                     B 14.39
core/database/central_backup.py         B 14.62
core/bilibili_auth.py                   B 16.62
ui/training_base.py                     B 17.35
ui/main_gui.py                          B 18.96
```

## 5. 验收口径（相对基线）

- `pytest`：保持 **115 passed**（只增不减，新增回归测试计入）。
- `flake8`：总项数**单调下降**；`F821`、`F811` **归零**。
- `radon cc`：被改动函数的 CC **下降**，无新增 >15。
- `radon mi`：目标文件 MI 上升；`registry.py` / `_torch_upgrade.py` / `training_panel.py` 离开 C 级。
- 每个改动单元单独一个 commit，先跑该单元"验证"再提交（见 `OPTIMIZATION_PLAN.md` §1.7/§1.8、§9、§10）。
