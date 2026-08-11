# 接口统一与兼容层删除可行性报告(破坏性变更)

> 项目:B站视频监控与播放量预测系统(pyqt6 分支)
> 日期:2026-08-11
> 范围:算法层接口统一 + 放弃老版本兼容 + 删除兼容层的专项评估
> 关联:ALGORITHM_REWRITE_REPORT.md(算法重写报告)、REFACTOR_REPORT.md(全库报告)

---

## 1. 结论先行

| 评估项 | 结论 |
|---|---|
| 统一接口(唯一 predict → PredictionResult) | ✅ **可行且推荐** |
| 放弃老版本算法接口兼容(破坏性变更) | ✅ **可行**——桌面应用,无外部 API 消费者 |
| 删除兼容层(adapter / _predict_legacy / 元组返回) | ✅ **可行**——删 ~700-900 行 + 消除双接口歧义 |
| 工作量 | **5-8 人日**(不含测试加固) |
| 主要风险 | registry 核心编排 + 训练管线 build_model 耦合(可控) |
| 建议 | **做**。作为算法重构(报告二)的第 0.5 步,先于骨架模板化 |

核心判断:**代码库内部接口没有外部消费者**(桌面应用、无插件系统、无第三方调用),"放弃老版本兼容"的代价为零——兼容层纯粹是历史迭代遗留(adapter 注释还写着"加载 55+ 算法",实际已 136)。删掉它,新算法只需实现一个 `predict()`。

⚠️ **边界声明**:本方案"放弃的兼容"仅指**算法运行时接口**(返回类型/方法签名)。以下三类"兼容"**不删**:
1. **DB 历史数据格式**(已存的 predictions 记录) — 是数据不是接口;
2. **checkpoint 模型文件格式**(.pt 跨版本加载) — 是资产不是接口;
3. **第三方库 API 探测**(torch 新旧 API 的 hasattr/try) — 删了会破坏对库版本的鲁棒性。

---

## 2. 兼容层全景盘点(要删什么)

### 2.1 `ModelAlgorithmAdapter` 适配层(最大目标,整层删除)

`algorithms/model_adapter.py`(~435 行)是旧接口桥接层,当前全部 136 个算法经它包装后进入 registry:

| 组成部分 | 行号 | 职责 | 删除后去向 |
|---|---|---|---|
| `ModelAlgorithmAdapter.__init__` | 41-54 | 反射提取 name/algorithm_id/category | registry 直接读实例属性 |
| `predict()` | 56-80 | 透传 + 异常兜底 | registry 直接调 `algo.predict` |
| `predict_dict()` | 82-111 | registry 并行预测入口 | 删除(registry 自己拼 dict) |
| `_prepare_video_data()` | 113-161 | 历史数据转换 | **保留一份**(与 registry.py:160 合并,当前重复!) |
| `_parse_result()` | 163-281 | **双格式分派(D/21)** | 只剩格式 1,复杂度 ~21→8 |
| `_make_na_result/_make_error_result` | 283-313 | 兜底结果 | 移入 registry 或 base |
| `weight/accuracy/build_model` 反射属性 | 315-372 | 权重/准确率转发 | registry 直接操作算法实例 |
| `load_all_model_algorithms()` | 375-434 | 动态扫描 + **`BasePredictionAlgorithm` 旧基类名检查**(L424) | 并入 registry 扫描逻辑 |

### 2.2 元组返回格式(25 文件 / 33 处)

`(seconds, confidence)` 旧返回格式分布:

| 类别 | 文件 | 处数 |
|---|---|---|
| growth | gompertz/logistic/richards/weibull | 8(各 2) |
| time_series | holt_winters / multi_seasonal / prophet(3)/ seasonal | 6 |
| statistical | elasticnet/huber/poisson/quantile/svr/theil_sen | 9 |
| deep_learning | attention/bilstm/dlinear/informer(2)/mlp/patch_tst/tft | 8 |
| advanced | kalman_filter / survival_analysis | 3 |
| ensemble | adaptive_boosting / cascade_ensemble | 3 |
| **合计** | **25 文件** | **33 处** |

→ `_parse_result` 的格式 2 分支(L249-278)存在的唯一理由就是这些元组。

### 2.3 `_predict_legacy` 双方法模式(5 文件)

gompertz_growth:91 / logistic_growth:89 / richards_curve:97 / weibull_growth:98 / holt_winters:81 —— 每个文件同时存在 `_predict_legacy()`(返回元组)与 `predict()`(薄包装委托)。删除后两个方法合并为一个 `predict()`。

### 2.4 旧基类名残留

`model_adapter.py:424` 仍检查 `"BasePredictionAlgorithm" in base_names` —— 已无任何算法继承该名,纯死代码。

---

## 3. 统一后的目标接口

```python
class BaseAlgorithm(ABC):
    def predict(self, video_data: Dict[str, Any], threshold: int = 100000) -> PredictionResult:
        """唯一预测接口。所有 136 个算法只实现这一个方法。"""
        ...

@dataclass(slots=True)
class PredictionResult:
    algorithm_name: str
    algorithm_id: str
    target_threshold: int
    predicted_hours: float
    confidence: float
    current_views: int
    current_velocity: float
    metadata: Dict[str, Any]
    timestamp: datetime
```

- **输入**:统一 `video_data` dict(含 view_count/history_data/timestamp/bvid);
- **输出**:统一 `PredictionResult` 对象;
- **注册**:registry 直接扫描/实例化算法类,**不再包装**;
- **并行预测**:registry `_run_parallel_predictions` 直接调 `algo.predict()`,结果在 registry 内统一转 dict;
- **训练**:`build_model`/`algorithm_id` 直接读算法实例属性。

---

## 4. 破坏面分析(谁会被打破)

| 影响面 | 现状 | 破坏点 | 风险 |
|---|---|---|---|
| **registry.py**(核心编排) | L319 `hasattr(algo, "predict_dict")` 分派 | 改为直接 `algo.predict()`,`_parse_result` 逻辑并入 | **高**(所有预测路径经过) |
| **25 个算法文件** | 返回元组 | 改返回 PredictionResult(数值逻辑不动) | 中(需全量回归) |
| **5 个 growth/time_series 文件** | `_predict_legacy`+predict 双方法 | 合并为一个 predict | 中 |
| **训练管线**(trainer.py:344/479/520/587, registry.py:679-703) | 经 `adapter.build_model` 反射转发 | 直接读 `algo.build_model` | 中 |
| **测试**(test_model_algorithms.py 10+ 处引用) | 测 adapter | 改测算法实例 | 低 |
| **UI 层** | 无 adapter 直接引用(已验证) | 无破坏 | 无 |
| **权重管理器/online_learner** | 经 adapter 的 set_weight/get_accuracy 转发 | registry 直连实例 | 低 |
| **DB / checkpoint / 缓存文件** | — | **不受影响**(数据格式不在本方案范围) | 无 |

**关键点**:UI 层零改动(已确认 ui/ 无 adapter 引用);破坏集中在 algorithms/ 内部。

---

## 5. 可行性评估

### 5.1 收益

| 项 | 量化 |
|---|---|
| 删除 `model_adapter.py` | **~435 行**整文件 |
| 25 文件元组→PredictionResult 转换样板 | ~150-250 行 |
| 5 文件 `_predict_legacy` 包装删除 | ~80 行 |
| `_parse_result` 复杂度 | D/21 → ~8(删格式 2 分支) |
| 双接口歧义消除 | 新算法只需实现 1 个 predict,不再纠结返回什么 |
| adapter/registry 重复的 `_prepare_video_data` | 合并为 1 份 |

**合计删 ~700-900 行 + 核心复杂度显著下降。**

### 5.2 风险与兜底

| 风险 | 等级 | 兜底 |
|---|---|---|
| registry 编排改动影响所有预测 | 高 | 先建特征化测试基线(报告二第 0 步);registry 改动单测覆盖 |
| 25 文件返回类型改动引入数值回归 | 中 | 元组→PredictionResult 是**纯包装转换**(数值不变),全量 diff 验证 |
| 训练管线 build_model 访问方式变化 | 中 | trainer 侧逐点替换 + 训练冒烟 |
| 测试引用 adapter | 低 | 同步更新 test_model_algorithms.py |

### 5.3 工作量(5-8 人日)

| 步骤 | 内容 | 估算 |
|---|---|---|
| 1 | 定义目标接口 + 迁移工具函数(na/error 结果进 base) | 1 天 |
| 2 | 25 文件元组返回批量转换(机械替换) | 2-3 天 |
| 3 | 5 文件 `_predict_legacy` 合并 | 1 天 |
| 4 | 删 adapter + registry 直连改造 + `_prepare_video_data` 合并 | 2-3 天 |
| 5 | 训练管线 build_model 直连 + 测试更新 | 1-2 天 |
| 6 | 全量验收(136 注册 + 特征化 diff=0) | 0.5 天 |

---

## 6. 边界:哪些"兼容"不该删

| 兼容类型 | 现状 | 处理 |
|---|---|---|
| DB predictions 记录格式 | 历史数据含 predicted_hours 字段 | **保留**(数据迁移风险远大于收益) |
| checkpoint 文件跨版本加载 | torch.load weights_only 处理(hf_loader.py:195) | **保留**(训练资产) |
| 第三方库 API 探测 | `_torch_upgrade.py` 对 torch 的 hasattr/getattr、onnx_exporter.py:131 `_compat` | **保留**(库版本鲁棒性) |
| video_data 输入格式 | `_prepare_video_data` 支持 datetime/ISO/数字 3 种时间戳 | **保留**(监控数据流兼容) |
| `_cached_video_data` 性能缓存 | registry.py:320 传入 | **保留**(性能机制,非兼容层) |

---

## 7. 实施步骤(建议顺序)

```
前置:特征化测试锁基线(固定样本跑 136 算法 → 输出快照)

步骤 1:目标接口落地
   - PredictionResult 字段冻结(8 字段不变)
   - _make_na_result/_make_error_result 移入 BaseAlgorithm

步骤 2:25 文件元组→PredictionResult(纯包装转换,数值不变)
   - 每文件:return (seconds, conf) → return PredictionResult(...)
   - 与 ALGORITHM_REWRITE_REPORT 的 _wrap_result 骨架衔接

步骤 3:5 文件 _predict_legacy 合并
   - _predict_legacy 本体改名为 predict,删薄包装层

步骤 4:删除 ModelAlgorithmAdapter 整层
   - registry 扫描逻辑接管(去掉 BasePredictionAlgorithm 死检查)
   - _run_parallel_predictions 直接调 algo.predict()
   - _parse_result 简化为单格式,移入 registry
   - 删除 model_adapter.py 文件

步骤 5:训练管线直连
   - trainer/registry 的 build_model/algorithm_id 直接读实例

步骤 6:验收
   - 注册数 = 136
   - 特征化 diff = 0(1e-6)
   - tests 全绿 + radon E/F 归零
```

---

## 8. 一句话结论

**可行,值得做,且应该做**:接口统一 + 删兼容层是本项目破坏性变更中"收益/风险比"最高的一个——零外部消费者、删 ~800 行、复杂度 D/21→8、新算法开发成本直降;唯一需要认真对待的是 registry 编排改造与 25 个文件的批量返回转换,均由特征化测试兜底。建议作为算法重构(报告二)的前置步骤一并执行。
