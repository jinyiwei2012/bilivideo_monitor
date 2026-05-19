# Checkpoints 目录

存放训练产物（PyTorch state_dict），按算法分目录管理。

## 目录结构

```
algorithms/checkpoints/
├── <algo_id>/                       # 算法全局 checkpoint
│   ├── v1_20260520_143012.pt        # 版本文件
│   ├── v2_20260521_090345.pt
│   ├── active.json                  # {"active_version": "v2_..."}
│   └── metadata.json                # 各版本的训练时间/数据量/loss
└── <algo_id>/_video/<BVID>/         # 视频微调 checkpoint
    └── v1_*.pt ...
```

## 重新生成

`.pt` 文件不入版本控制（见根目录 `.gitignore`），按需通过 GUI 重新训练：

> 设置 → 模型训练 → 训练所有勾选

## 默认推理行为

- 有 active checkpoint → 使用 torch 推理（更准）
- 无 checkpoint / 加载失败 / 推理异常 → 自动降级到 numpy 简化版

详见 `algorithms/training/checkpoint_manager.py`。
