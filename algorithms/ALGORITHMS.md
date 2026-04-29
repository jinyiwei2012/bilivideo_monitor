# B站视频播放量预测算法说明

本文档详细说明系统中所有预测算法的实现原理、数学公式和适用场景。

## 目录

1. [算法概述](#算法概述)
2. [基础速度模型](#基础速度模型)
3. [时间衰减模型](#时间衰减模型)
4. [扩散模型](#扩散模型)
5. [机器学习模型](#机器学习模型)
6. [集成模型](#集成模型)
7. [时间序列模型](#时间序列模型)
8. [统计模型](#统计模型)
9. [贝叶斯模型](#贝叶斯模型)
10. [生命周期模型](#生命周期模型)
11. [多任务学习](#多任务学习)
12. [线性模型](#线性模型)
13. [深度学习](#深度学习)
14. [Transformer模型](#transformer模型)
15. [互动率模型](#互动率模型)
16. [趋势回归模型](#趋势回归模型)
17. [算法选择建议](#算法选择建议)

---

## 算法概述

### 预测目标
预测视频播放量从当前值增长到目标阈值（10万/100万/1000万）所需的时间。

### 输入数据
- 当前播放量
- 历史监控数据（时间序列）
- 视频信息（标题、UP主、互动数据等）

### 输出结果
- 预测所需时间（小时或秒）
- 置信度（0-1）
- 元数据（算法参数、特征等）

---

## 基础速度模型

### 1. 线性速度算法 (Linear Velocity)

**文件**: `models/linear_velocity.py`

#### 原理
假设播放量以恒定速度增长，基于当前速度线性外推。

#### 数学公式
```
V = ΔViews / ΔTime
T = (Target - Current) / V
```

其中：
- V: 当前播放速度（播放/小时）
- T: 预测所需时间

#### 实现
```python
velocity = (current_views - previous_views) / time_diff_hours
remaining = target_views - current_views
predicted_hours = remaining / velocity
```

#### 适用场景
- 视频处于稳定增长期
- 没有明显的增长加速或减速趋势
- 数据点较少时的简单预测

#### 置信度计算
```python
confidence = min(1.0, max(0.3, 1 - age_hours / 168))
```
置信度随视频年龄增加而降低（一周后显著降低）。

---

### 2. 加权速度算法 (Weighted Velocity)

**文件**: `models/weighted_velocity.py`

#### 原理
给近期数据更高权重，认为近期速度更能反映未来趋势。

#### 数学公式
```
V_weighted = Σ(w_i * v_i) / Σ(w_i)
其中 w_i = exp(-λ * (t_now - t_i))
```

#### 实现
```python
# 指数加权
weights = [exp(-decay_rate * (now - t)) for t in timestamps]
velocity = sum(w * v for w, v in zip(weights, velocities)) / sum(weights)
```

#### 适用场景
- 视频增长速度在变化
- 需要更关注近期趋势
- 新发布视频的早期预测

---

### 3. 近期速度算法 (Recent Velocity)

**文件**: `models/recent_velocity.py`

#### 原理
仅使用最近N个数据点计算速度，忽略早期数据。

#### 实现
```python
recent_data = history_data[-n_points:]  # 默认最近5个点
velocity = calculate_velocity(recent_data)
```

#### 适用场景
- 视频增长模式发生显著变化
- 需要快速响应趋势变化
- 排除历史异常数据的影响

---

## 时间衰减模型

### 4. 指数衰减算法 (Exponential Decay)

**文件**: `models/exponential_decay.py`

#### 原理
播放量增长速度随时间自然衰减，符合内容传播的自然规律。

#### 数学公式
```
v(t) = v_0 * exp(-λt)

积分求解:
∫v(t)dt = (v_0/λ) * (1 - exp(-λt)) = Remaining

解得:
t = -ln(1 - λ*Remaining/v_0) / λ
```

其中：
- λ = ln(2)/24 ≈ 0.0289 (24小时半衰期)
- v_0: 初始速度

#### 实现
```python
decay_rate = 0.693 / 24  # 24小时后速度减半
v0 = velocity * exp(decay_rate * age_hours)
numerator = decay_rate * remaining / v0
predicted_hours = -log(1 - numerator) / decay_rate
```

#### 适用场景
- 已经过了爆发期的视频
- 增长速度明显放缓的视频
- 长期趋势预测

#### 为什么采用此算法
内容传播遵循自然衰减规律：
1. 新视频获得平台推荐，增长快
2. 随着时间推移，推荐减少，增长放缓
3. 最终趋于稳定或缓慢增长

指数衰减模型准确描述了这一过程。

---

### 5. 对数增长算法 (Logarithmic Growth)

**文件**: `models/logarithmic_growth.py`

#### 原理
播放量随时间呈对数增长，增长速度逐渐减慢但永不为零。

#### 数学公式
```
Views(t) = a * ln(t + b) + c

求解目标时间:
Target = a * ln(T + b) + c
T = exp((Target - c)/a) - b
```

#### 适用场景
- 长期缓慢增长的视频
- 长尾内容
- 经典视频（持续有搜索流量）

---

### 6. 幂律增长算法 (Power Law)

**文件**: `models/power_law.py`

#### 原理
播放量增长遵循幂律分布，常见于病毒式传播。

#### 数学公式
```
Views(t) = a * t^b

其中 b < 1 时增长减速
b > 1 时增长加速
```

#### 适用场景
- 病毒式传播视频
- 社交媒体传播
- 初期爆发性增长

---

## 扩散模型

### 7. Bass扩散模型 (Bass Diffusion)

**文件**: `models/bass_diffusion.py`

#### 原理
基于创新扩散理论，模拟产品/内容在市场中的传播过程。区分两种传播机制：
1. **创新效应 (p)**: 外部影响，如平台推荐
2. **模仿效应 (q)**: 内部口碑传播，如分享

#### 数学公式
```
Bass微分方程:
f(t) / (1 - F(t)) = p + q*F(t)

累积采用者函数:
F(t) = m * (1 - exp(-(p+q)*t)) / (1 + (q/p)*exp(-(p+q)*t))

其中:
- m: 市场潜力（最大播放量）
- p: 创新系数 (0.01-0.03)
- q: 模仿系数 (0.3-0.5)
```

#### 参数调整
```python
# 根据粉丝数调整市场潜力
m = max(follower * 3, 1000000)

# 根据互动率调整模仿系数
q = min(0.5, 0.3 + like_rate * 10)

# 根据视频质量调整创新系数
p = min(0.1, 0.02 + quality * 0.05)
```

#### 实现
使用二分查找求解目标时间：
```python
def bass_cumulative(t):
    exp_term = exp(-(p+q)*t)
    return m * (1 - exp_term) / (1 + (q/p)*exp_term)

# 二分查找
while abs(views_mid - target) > threshold:
    if views_mid < target:
        t_low = t_mid
    else:
        t_high = t_mid
```

#### 适用场景
- 病毒式传播视频
- 有强烈社交属性的内容
- 需要区分外部推荐和口碑传播

#### 为什么采用此算法
Bass模型是新产品扩散预测的经典模型：
1. **理论基础扎实**: 基于社会学创新扩散理论
2. **参数可解释**: p和q有明确的实际意义
3. **适应性强**: 可根据视频特征调整参数
4. **预测准确**: 在社交媒体传播预测中表现优异

---

### 8. Gompertz增长模型

**文件**: `models/gompertz_growth.py`

#### 原理
S型增长曲线，初期慢、中期快、后期饱和。

#### 数学公式
```
Views(t) = a * exp(-b * exp(-c*t))

其中:
- a: 上限（市场潜力）
- b: 位移参数
- c: 增长率
```

#### 适用场景
- 有明显生命周期的视频
- 最终会达到饱和的内容
- 长期趋势预测

---

### 9. Logistic增长模型

**文件**: `models/logistic_growth.py`

#### 原理
经典的S型增长模型，描述有限资源下的增长。

#### 数学公式
```
dN/dt = r*N*(1 - N/K)

解:
N(t) = K / (1 + ((K-N0)/N0) * exp(-rt))

其中:
- K: 环境容量（最大播放量）
- r: 内禀增长率
- N0: 初始播放量
```

#### 适用场景
- 有明显上限的内容
- 竞争激烈的领域
- 市场容量有限的视频

---

### 10. Weibull增长模型

**文件**: `models/weibull_growth.py`

#### 原理
灵活的分布模型，可模拟各种增长模式。

#### 数学公式
```
F(t) = 1 - exp(-(t/λ)^k)

其中:
- λ: 尺度参数
- k: 形状参数（k<1减速，k>1加速）
```

#### 适用场景
- 需要灵活形状参数的场景
- 不同增长模式的视频
- 作为基准模型对比

---

### 11. Richards曲线

**文件**: `models/richards_curve.py`

#### 原理
广义的Logistic曲线，增加形状参数提供更灵活的增长模式。

#### 数学公式
```
Y(t) = A / (1 + exp(-k*(t-t0)))^(1/ν)

其中 ν 是形状参数
```

---

## 机器学习模型

### 12. 神经网络 (Neural Network)

**文件**: `models/neural_network_simple.py`

#### 原理
多层感知机（MLP）学习历史数据中的非线性模式。

#### 架构
```
输入层: [时间特征, 播放量, 互动数据]
    ↓
隐藏层1: 64神经元 (ReLU)
    ↓
隐藏层2: 32神经元 (ReLU)
    ↓
输出层: 1神经元 (预测时间)
```

#### 特征工程
```python
features = [
    current_views,
    like_count,
    coin_count,
    share_count,
    video_age_hours,
    velocity_1h,
    velocity_6h,
    velocity_24h,
    engagement_rate
]
```

#### 适用场景
- 有大量历史数据
- 复杂的非线性关系
- 需要自动特征学习

---

### 13. LSTM时序预测

**文件**: `models/lstm_simple.py`

#### 原理
长短期记忆网络，专门处理时间序列数据。

#### 架构
```
输入: [时间窗口内的播放量序列]
    ↓
LSTM层1: 50单元
    ↓
LSTM层2: 50单元
    ↓
全连接层: 预测未来播放量
```

#### 适用场景
- 有明显时间模式的数据
- 长期依赖关系
- 需要记忆历史信息

---

### 14. 随机森林 (Random Forest)

**文件**: `models/random_forest_simple.py`

#### 原理
集成多棵决策树，通过投票提高预测稳定性。

#### 参数
```python
n_estimators = 100  # 树的数量
max_depth = 10      # 最大深度
min_samples_split = 5
```

#### 适用场景
- 特征维度较高
- 需要特征重要性分析
- 防止过拟合

---

### 15. XGBoost

**文件**: `models/xgboost_simple.py`

#### 原理
梯度提升决策树，高效准确的集成学习方法。

#### 优势
1. 正则化防止过拟合
2. 自动处理缺失值
3. 支持并行计算
4. 内置交叉验证

---

### 16. CatBoost

**文件**: `models/catboost_simple.py`

#### 原理
Yandex开发的梯度提升库，对类别特征处理优秀。

---

### 17. 支持向量回归 (SVR)

**文件**: `models/svr_predictor.py`

#### 原理
使用支持向量机进行回归预测。

#### 核函数
```python
kernel = 'rbf'  # 径向基函数
C = 1.0         # 正则化参数
epsilon = 0.1   # 容忍度
```

---

### 18. MLP预测器

**文件**: `models/mlp_predictor.py`

#### 原理
多层感知机的另一种实现，使用scikit-learn。

---

## 集成模型

### 19. 加权集成 (Weighted Ensemble)

**文件**: `models/ensemble_weighted.py`

#### 原理
结合多个算法的预测结果，按权重加权平均。

#### 数学公式
```
T_ensemble = Σ(w_i * T_i) / Σ(w_i)

其中 w_i 是算法i的权重
```

#### 权重分配
```python
weights = {
    'linear_velocity': 1.0,
    'exponential_decay': 1.3,
    'bass_diffusion': 1.5,
    'neural_network': 1.2
}
```

#### 适用场景
- 综合多个算法的优势
- 提高预测稳定性
- 降低单一算法的偏差

---

### 20. 投票集成 (Voting Ensemble)

**文件**: `models/ensemble_voting.py`

#### 原理
多个算法投票，取中位数或多数表决。

---

### 21. 堆叠集成 (Stacking)

**文件**: `models/ensemble_stacking.py`

#### 原理
使用元学习器组合多个基学习器的预测。

```
第一层: 多个基学习器
    ↓
第二层: 元学习器（通常是线性回归）
    ↓
最终预测
```

---

### 22. 平均集成 (Average Ensemble)

**文件**: `models/ensemble_average.py`

#### 原理
简单平均所有算法的预测结果。

---

### 23. 自适应提升 (AdaBoost)

**文件**: `models/adaptive_boosting.py`

#### 原理
迭代调整样本权重，关注预测错误的样本。

---

### 24. 梯度提升 (Gradient Boosting)

**文件**: `models/gradient_boost_simple.py`

#### 原理
串行训练弱学习器，每个学习器纠正前一个的错误。

---

## 时间序列模型

### 25. ARIMA模型

**文件**: `models/arima_simple.py`

#### 原理
自回归积分滑动平均模型，经典的时间序列预测方法。

#### 数学公式
```
ARIMA(p,d,q):
(1 - Σφ_iL^i)(1-L)^d y_t = (1 + Σθ_iL^i)ε_t

其中:
- p: 自回归阶数
- d: 差分阶数
- q: 移动平均阶数
```

#### 适用场景
- 有明显趋势的时间序列
- 需要统计严谨性
- 数据点足够多（>30）

---

### 26. 指数平滑 (Exponential Smoothing)

**文件**: `models/exponential_smoothing.py`

#### 原理
给近期观测更高权重，平滑历史数据。

#### 数学公式
```
s_t = α*y_t + (1-α)*s_{t-1}

其中 α 是平滑参数 (0<α<1)
```

---

### 27. Holt-Winters

**文件**: `models/holt_winters.py`

#### 原理
考虑趋势和季节性的三重指数平滑。

---

### 28. 移动平均 (Moving Average)

**文件**: `models/moving_average.py`

#### 原理
使用历史数据的平均值预测未来。

---

### 29. 季节性分解

**文件**: `models/seasonal_decomposition.py`

#### 原理
将时间序列分解为趋势、季节性和残差。

---

## 统计模型

### 30. 高斯过程 (Gaussian Process)

**文件**: `models/gaussian_process.py`

#### 原理
非参数贝叶斯方法，提供预测的不确定性估计。

#### 优势
- 提供置信区间
- 灵活的非线性拟合
- 适合小样本

---

### 31. 贝叶斯回归

**文件**: `models/bayesian_regression.py`

#### 原理
使用贝叶斯方法估计参数分布。

---

### 32. 卡尔曼滤波 (Kalman Filter)

**文件**: `models/kalman_filter.py`

#### 原理
递归的状态估计算法，适合实时更新预测。

#### 应用
```
状态: [播放量, 速度]
观测: 实际播放量
预测: 下一时刻状态
```

---

### 33. 注意力机制 (Attention Mechanism)

**文件**: `models/attention_mechanism.py`

#### 原理
学习不同时间步的重要性权重。

---

### 42. 变化点检测 (Change Point Detection)

**文件**: `models/change_point_detection.py`

#### 原理
使用CUSUM（累积和）算法检测播放量增速的突变点，根据当前所处的"增速阶段"调整预测策略。

#### CUSUM算法
```
正向CUSUM: C_i^+ = max(0, C_{i-1}^+ + z_i - k)
负向CUSUM: C_i^- = max(0, C_{i-1}^- - z_i - k)

其中：
- z_i: 标准化后的速度值
- k: 控制限（默认0.5）
- 当C_i > h时检测到变化点（h默认2.0）
```

#### 检测策略
1. **加速阶段**: 近期检测到加速变化点，预测速度上调20%
2. **减速阶段**: 近期检测到减速变化点，预测速度下调20%
3. **稳定阶段**: 无变化点或变化点较旧，使用近期平均速度
4. **后变化稳定**: 变化点发生后趋于稳定

#### 适用场景
- 视频因推荐算法调整突然爆火
- 因热点事件播放量突变
- 需要动态调整预测策略的场景

---

### 43. 生存分析 (Survival Analysis)

**文件**: `models/survival_analysis.py`

#### 原理
预测视频"停止增长"的时间（即播放量基本稳定的时间）。使用Kaplan-Meier估计的简化版。

#### 核心概念
- **生存函数 S(t)**: 视频在t时刻仍在增长的概率
- **事件**: 速度低于阈值（默认1.0播放量/小时）
- **删失数据**: 研究结束时仍未"停止增长"的视频

#### 简化Kaplan-Meier估计
```
S(t) = Π_{i:t_i ≤ t} (1 - d_i/n_i)

其中：
- d_i: t_i时刻发生事件的数量
- n_i: t_i时刻处于风险集的数量
```

#### 预测调整策略
| 生存概率 | 调整策略 | 置信度 |
|---------|---------|---------|
| < 0.3  | 速度下调50% | 0.7 |
| 0.3-0.5 | 速度下调30% | 0.65 |
| 0.5-0.7 | 速度下调15% | 0.6 |
| > 0.7  | 保持当前速度 | 0.55 |

#### 适用场景
- 预测视频生命周期末期
- 长期趋势预测
- 需要判断"是否还会增长"的场景

---

## 贝叶斯模型

### 44. UP主历史表现贝叶斯模型 (UPcaster History Bayesian)

**文件**: `models/upcaster_history_bayesian.py`

#### 原理
利用UP主历史数据，通过贝叶斯估计提升预测准确性。将UP主历史表现作为先验分布，结合当前视频数据得到后验预测。

#### 贝叶斯更新公式
```
后验均值 = (先验均值/先验方差 + n*观测均值/观测方差) / (1/先验方差 + n/观测方差)
后验方差 = 1 / (1/先验方差 + n/观测方差)
```

#### 先验分布构造
- **有充足历史数据**: 使用历史视频的平均增速作为先验均值，方差较小
- **历史数据少**: 使用历史数据计算均值和方差
- **无历史数据**: 退化为普通预测（使用当前视频数据）

#### 先验权重调整
```python
prior_weight = 0.3  # 可调整
posterior_mu = prior_weight * mu_prior + (1 - prior_weight) * current_vel
```

#### 适用场景
- UP主有历史视频数据
- 需要利用UP主维度信息
- 新视频预测（借用历史经验）

---

## 生命周期模型

### 45. 视频生命周期建模 (Lifecycle Modeling)

**文件**: `models/lifecycle_modeling.py`

#### 原理
将视频生命周期划分为不同阶段，针对不同阶段使用不同预测策略。

#### 生命周期阶段
| 阶段 | 速度范围 | 加速度 | 预测策略 |
|------|---------|--------|----------|
| 导入期 | < 50/h | 任意 | 平均增速外推 |
| 成长期 | ≥ 50/h | > 0 | 近期速度×1.1 |
| 成熟期 | 10-50/h | ≈ 0 | 指数衰减模型 |
| 衰退期 | < 10/h | < 0 | 长期趋势外推 |
| 病毒期 | ≥ 500/h | 任意 | 根据加速度调整 |

#### 阶段判断依据
1. **当前速度**: 决定基本阶段
2. **加速度**: 决定阶段内的子状态
3. **速度变异系数**: 判断稳定性

#### 预测策略
- **导入期**: 使用平均速度和趋势外推
- **成长期**: 使用近期速度，考虑增长惯性
- **成熟期**: 使用指数衰减模型
- **衰退期**: 使用长期趋势，预测较准确
- **病毒期**: 根据加速度调整，考虑热度消退

#### 适用场景
- 需要明确视频所处阶段
- 不同阶段需要不同预测策略
- 视频全生命周期分析

---

## 多任务学习

### 46. 多任务学习简化版 (Multi-Task Learning Simplified)

**文件**: `models/multi_task_simple.py`

#### 原理
同时预测多个阈值（10万/100万/1000万），利用任务间的相关性提高预测准确性。

#### 核心思路
1. **共享特征提取**: 使用统一的速度特征
2. **任务特定层**: 不同阈值对应不同的增长模式
3. **一致性检查**: 不同阈值的预测应保持一致

#### 阈值预测策略
| 阈值 | 预测策略 | 权重 |
|------|---------|------|
| 10万 | 使用近期速度 | 0.4 |
| 100万 | 结合近期和平均速度 | 0.4 |
| 1000万 | 考虑衰减（长期） | 0.2 |

#### 一致性调整
```python
一致性 = 标准差(各任务预测速度) / 均值(各任务预测速度)

if 一致性 < 0.3:
    使用加权平均（高置信度）
else:
    使用当前速度（低置信度）
```

#### 适用场景
- 需要同时预测多个阈值
- 任务间有相关性
- 希望提高预测稳定性

---

## 线性模型

### 48. DLinear简化版 (DLinear Simplified)

**文件**: `models/dlinear_simple.py`

#### 原理
简单但有效的线性模型，在某些任务上超越Transformer。将序列分解为趋势分量和剩余分量，分别使用线性映射。

论文：Are Transformers Effective for Time Series Forecasting? (AAAI 2023)

#### 核心机制
```
1. 分解：序列 = 趋势分量 + 剩余分量
2. 线性映射：分别对两个分量做线性变换
3. 叠加：预测 = 趋势预测 + 剩余预测
```

#### 数学公式
```
趋势分量：使用移动平均提取
剩余分量：原始序列 - 趋势分量

预测：Linear(趋势) + Linear(剩余)
```

#### 优势
- 非常简单，训练快
- 在某些数据集上超越Transformer
- 可解释性强

#### 适用场景
- 数据量不大的场景
- 需要快速预测
- 作为基准模型

---

## 深度学习

### 49. N-BEATS简化版 (N-BEATS Simplified)

**文件**: `models/n_beats_simple.py`

#### 原理
使用基函数展开（stack of fully connected layers）捕捉时序模式。将预测分解为多个block，每个block输出回看分量和预测分量。

论文：N-BEATS: Neural basis expansion analysis for interpretable time series forecasting (ICLR 2020)

#### 核心机制
```
每个Block：
  1. 输入 → 全连接网络
  2. 分解为：回看分量（用于分解） + 预测分量（未来预测）
  3. 残差连接：输入 - 回看分量 → 下一个Block
```

#### 数学公式
```
输出 = Σ (ForecastBlock_i)

每个Block:
  backcast = Block(x)
  forecast = Block(x)
  x_next = x - backcast  (残差连接)
```

#### 优势
- 可解释性强（趋势/季节性分解可视化）
- 在M4竞赛中表现优异
- 支持多种损失函数

#### 适用场景
- 需要可解释预测
- 数据量充足
- 中长期预测

---

### 50. TimesNet简化版 (TimesNet Simplified)

**文件**: `models/times_net_simple.py`

#### 原理
将1D时间序列转换为2D，捕获周期内和周期间的模式。通过2D卷积捕捉时序中的多维模式。

论文：TimesNet: Temporal 2D-Variation Modeling for General Time Series Analysis (ICLR 2023)

#### 核心机制
```
1. 将1D序列按周期长度P转换为2D矩阵
   例如：序列 [1,2,3,4,5,6], P=3
   2D = [[1,2,3], [4,5,6]]
2. 应用2D卷积提取周期内和周期间特征
3. 转换回1D进行预测
```

#### 优势
- 同时捕获周期内和周期间模式
- 在多项任务上达到SOTA
- 通用性强（分类/预测/异常检测）

#### 适用场景
- 有明显周期性的数据
- 需要捕捉复杂时序模式
- 多任务学习

---

## Transformer模型

### 47. PatchTST简化版 (Patch Time Series Transformer Simplified)

**文件**: `models/patch_tst_simple.py`

#### 原理
将时间序列分成多个patch（类似NLP中的token），使用简化注意力机制捕捉长时间序列的局部模式。

核心思路来自论文：
"A Time Series is Worth 64 Words: Long-term Forecasting with Transformers" (ICLR 2023)

#### Patch处理
```
序列: [v1, v2, v3, v4, v5, v6, v7, v8, ...]
Patch 1: [v1, v2, v3, v4]  (patch_len=4)
Patch 2: [v3, v4, v5, v6]  (stride=2)
Patch 3: [v5, v6, v7, v8]
...
```

#### Patch表示
每个patch使用4个统计量表示：
1. **均值**: patch的平均速度
2. **标准差**: patch的波动程度
3. **斜率**: patch的线性趋势
4. **最后一个值**: patch的结束速度

#### 简化注意力机制
```python
# 使用最后一个patch作为query
query = repr[-1]

# 计算相似度（点积）
similarities = [dot(query, k) for k in repr]

# Softmax得到注意力权重
attention_weights = softmax(similarities)

# 加权求和
attended = Σ(weight_i * repr_i)
```

#### 预测调整
根据注意力预测和近期速度的差异调整：
- 差异小（<20%）: 高置信度，使用加权平均
- 差异中（20%-50%）: 中等置信度
- 差异大（>50%）: 低置信度，更依赖近期速度

#### 适用场景
- 长时间序列预测
- 需要捕捉局部模式
- 希望利用Transformer的注意力机制

---

### 51. Informer简化版 (Informer Simplified)

**文件**: `models/informer_simple.py`

#### 原理
高效Transformer，使用ProbSparse自注意力将复杂度从O(L²)降低到O(L log L)。

论文：Informer: Beyond Efficient Transformer for Long Sequence Time-Series Forecasting (AAAI 2021)

#### 核心机制
```
1. ProbSparse自注意力：只计算最重要的注意力连接
2. 自注意力蒸馏：下采样减少序列长度
3. 生成式解码器：避免误差累积
```

#### ProbSparse注意力
```
不是所有注意力连接都需要计算，
只保留每个query最重要的factor个key。
```

#### 优势
- 长序列预测效率高
- 内存占用低
- 在长序列任务上达到SOTA

#### 适用场景
- 长序列预测（>100个点）
- 需要高效Transformer
- 内存受限环境

---

### 52. TFT简化版 (Temporal Fusion Transformer Simplified)

**文件**: `models/tft_simple.py`

#### 原理
结合静态/动态特征，提供可解释性的时间序列预测。使用变量选择网络、门控残差网络和时态自注意力。

论文：Temporal Fusion Transformers for Interpretable Multi-horizon Time Series Forecasting (2019)

#### 核心机制
```
1. 变量选择网络：选择相关输入变量
2. 门控残差网络（GRN）：特征融合
3. 可解释多头注意力：时态自注意力
4. 结合静态协变量：利用不随时间变化的特征
```

#### 数学公式
```
变量选择：w_i = softmax(v^T * elu(W*x_i + b))
GRN：gated_linear(x) = (W1*x + b1) ⊗ sigmoid(W2*x + b2)
```

#### 优势
- 可解释性强（特征重要性可视化）
- 支持静态和动态特征
- 在M4/M5竞赛中表现优异

#### 适用场景
- 需要可解释预测
- 有静态特征（视频类型、UP主属性等）
- 多 horizon 预测

---

## 互动率模型

### 34. 点赞动量 (Like Momentum)

**文件**: `models/like_momentum.py`

#### 原理
基于点赞增长速度预测播放量增长。

#### 假设
点赞和播放量存在稳定比例关系，点赞增长预示着播放量增长。

---

### 35. 分享速度 (Share Velocity)

**文件**: `models/share_velocity.py`

#### 原理
基于分享传播速度预测病毒式扩散。

---

### 36. 弹幕趋势 (Comment Trend)

**文件**: `models/comment_trend.py`

#### 原理
基于弹幕活跃度预测视频热度。

---

### 37. 投币Boost (Coin Boost)

**文件**: `models/coin_boost.py`

#### 原理
投币代表高质量认可，投币率高的视频增长更快。

---

### 38. 互动率综合 (Engagement Rate)

**文件**: `models/engagement_rate.py`

#### 原理
综合考虑点赞率、投币率、分享率预测增长潜力。

---

### 39. 内容质量评分 (Quality Score)

**文件**: `models/quality_score.py`

#### 原理
基于多维度互动数据评估内容质量，质量高的视频增长更快。

---

### 40. 病毒潜力 (Viral Potential)

**文件**: `models/viral_potential.py`

#### 原理
识别具有病毒传播特征的视频。

#### 特征
```python
viral_features = [
    share_rate > threshold,
    growth_acceleration > 0,
    engagement_rate > average,
    early_views_growing_fast
]
```

---

## 趋势回归模型

### 41. 趋势回归 (Trend Regression)

**文件**: `models/trend_regression.py`

#### 原理
拟合播放量时间序列的趋势线。

---

## 算法选择建议

### 按视频阶段选择

| 视频阶段 | 推荐算法 | 原因 |
|---------|---------|------|
| 新发布 (<24h) | 线性速度、加权速度 | 数据少，简单模型更稳定 |
| 增长期 (1-7天) | Bass扩散、指数衰减 | 捕捉增长趋势和衰减 |
| 稳定期 (>7天) | 对数增长、幂律 | 长期缓慢增长 |
| 爆发期 | 病毒潜力、Bass扩散 | 捕捉病毒传播特征 |

### 按数据量选择

| 数据点数量 | 推荐算法 | 原因 |
|-----------|---------|------|
| < 5 | 线性速度、加权速度 | 简单模型避免过拟合 |
| 5-20 | 指数衰减、Bass扩散 | 中等复杂度 |
| 20-50 | ARIMA、机器学习 | 足够数据训练 |
| > 50 | LSTM、集成模型 | 复杂模型发挥优势 |

### 按视频类型选择

| 视频类型 | 推荐算法 | 原因 |
|---------|---------|------|
| 娱乐/搞笑 | 病毒潜力、Bass扩散 | 易传播 |
| 教程/知识 | 对数增长、线性 | 长尾流量 |
| 热点/新闻 | 指数衰减、近期速度 | 时效性强 |
| 音乐/MV | 互动率模型 | 粉丝效应明显 |

### 集成策略

推荐使用加权集成作为默认算法：
```python
# 推荐权重配置
weights = {
    'linear_velocity': 1.0,      # 基础预测
    'exponential_decay': 1.3,    # 考虑衰减
    'bass_diffusion': 1.5,       # 传播模型
    'engagement_rate': 1.2,      # 互动因素
    'weighted_velocity': 1.1     # 近期趋势
}
```

---

## 算法评估指标

### 准确性指标
- **MAE** (平均绝对误差): |预测时间 - 实际时间|
- **MAPE** (平均绝对百分比误差): |误差|/实际时间
- **RMSE** (均方根误差): 对大误差更敏感

### 可靠性指标
- **置信度**: 算法自身评估的可靠性
- **覆盖率**: 成功预测的比例
- **稳定性**: 多次预测的一致性

---

## 高级模块（2026-04-22 新增，2026-04-30 扩展）

### 在线学习 (OnlineLearner)

**文件**: `online_learner.py`

#### 原理
使用 **Hedge 算法**（指数权重专家混合）动态调整各算法权重。

#### 核心机制
```
每次实际值到达后：
1. 计算每个算法的相对误差 error = |predicted - actual| / actual
2. 累积损失 L_i += ln(1 + error_i)
3. 更新权重 w_i ∝ exp(-η × (L_i - min_L))
4. 归一化后输出推荐权重
```

#### 参数
- `eta = 0.5` : Hedge 学习率
- `decay = 0.95` : EWMA 误差衰减系数
- `warmup = 5` : 至少 5 次反馈才开始调整
- `min_weight = 0.05` : 最低权重防淘汰

#### 集成方式
- 每次预测后，将上次预测值与当前实际值对比，反馈给 OnlineLearner
- 在线学习器独立于 WeightManager，提供辅助权重参考
- 支持持久化（JSON），重启后可恢复学习状态

---

### 因果推断 (CausalAnalyzer)

**文件**: `causal_inference.py`

#### 原理
使用 **Granger 因果检验**（OLS 简化实现）检验各指标是否领先于播放量变化。

#### 分析方法
1. **Granger 因果检验**：检验点赞/投币/分享等是否"导致"播放量变化
   - 对每个 lag k 构建受限/无限制回归
   - F 统计量衡量因果强度，F > 3.0 视为显著
2. **Pearson 相关性**：各指标与播放量的线性相关性
3. **Lead-Lag 交叉相关**：分析指标领先/滞后播放量的时序关系

#### 可检验指标
| 指标 | 说明 |
|------|------|
| like_count | 点赞 |
| coin_count | 投币 |
| share_count | 分享 |
| favorite_count | 收藏 |
| danmaku_count | 弹幕 |
| reply_count | 评论 |
| viewers_total | 在线人数 |
| viewers_app | APP观看 |
| viewers_web | 网页观看 |

#### 输出
```python
{
    'granger_ranking': [(feature, f_stat, best_lag, label), ...],  # F统计量降序
    'correlation':    {feature: pearson_r, ...},                    # 相关系数
    'lead_lag':       {feature: best_shift, ...},                   # 领先/滞后
    'key_drivers':    [feature, ...],                                # 关键驱动因素
}
```

---

### 图神经网络 (VideoGraph)

**文件**: `graph_neural.py`

#### 原理
构建视频关联图，使用 **简化 GCN**（图卷积网络）学习节点嵌入。

#### 图构建规则
| 边类型 | 权重 | 说明 |
|--------|------|------|
| 同UP主 | 0.5 | 强关联 |
| 发布时间接近 | 0~0.3 | 48h内线性衰减 |
| 互动率相似 | 0~0.2 | 差异越小权重越高 |

#### GCN 架构
```
输入: 节点特征矩阵 X (N × 12)
    ↓
Layer 0: H^(1) = ReLU(Ã · X · W^(0) + b^(0))    # 12 → 8
    ↓
Layer 1: H^(2) = Ã · H^(1) · W^(1) + b^(1)      # 8 → 4
    ↓
输出: 节点嵌入 (N × 4)
```

其中 Ã = D^{-1/2} A D^{-1/2} 为对称归一化邻接矩阵（含自环）。

#### 节点特征（12维）
| 维度 | 特征 | 说明 |
|------|------|------|
| 1 | log10(播放量) | 播放量规模 |
| 2 | 点赞率 | like / view |
| 3 | 投币率 | coin / view |
| 4 | 分享率 | share / view |
| 5 | 收藏率 | fav / view |
| 6 | 弹幕率 | danmaku / view |
| 7 | 评论率 | reply / view |
| 8 | 在线率 | viewer / view |
| 9 | log10(时长) | 视频时长规模 |
| 10 | 综合互动率 | (like+coin+fav+share) / view |
| 11 | 投币/点赞比 | coin / like |
| 12 | 弹幕/评论比 | danmaku / reply |

#### 图增强特征
每个视频的最终特征 = 自身特征(12) + 邻居聚合特征(12) + GCN嵌入(4) = 28维

---

### 变化点检测 (Change Point Detection)

**文件**: `models/change_point_detection.py`

#### 原理
使用CUSUM（累积和）算法检测播放量增速的突变点，根据当前所处的"增速阶段"调整预测策略。

#### 核心机制
- 正向CUSUM检测加速变化点
- 负向CUSUM检测减速变化点
- 根据最近变化点类型调整预测速度

#### 适用场景
- 视频因推荐算法调整突然爆火
- 因热点事件播放量突变

---

### 生存分析 (Survival Analysis)

**文件**: `models/survival_analysis.py`

#### 原理
预测视频"停止增长"的时间。使用Kaplan-Meier估计的简化版。

#### 适用场景
- 预测视频生命周期末期
- 长期趋势预测

---

### UP主历史表现贝叶斯模型 (UPcaster History Bayesian)

**文件**: `models/upcaster_history_bayesian.py`

#### 原理
利用UP主历史数据，通过贝叶斯估计提升预测准确性。

#### 适用场景
- UP主有历史视频数据
- 新视频预测（借用历史经验）

---

### 视频生命周期建模 (Lifecycle Modeling)

**文件**: `models/lifecycle_modeling.py`

#### 原理
将视频生命周期划分为不同阶段，针对不同阶段使用不同预测策略。

#### 生命周期阶段
导入期 → 成长期 → 成熟期 → 衰退期（可能包含病毒期）

---

### 多任务学习简化版 (Multi-Task Learning Simplified)

**文件**: `models/multi_task_simple.py`

#### 原理
同时预测多个阈值（10万/100万/1000万），利用任务间的相关性提高预测准确性。

---

### PatchTST简化版 (Patch Time Series Transformer Simplified)

**文件**: `models/patch_tst_simple.py`

#### 原理
将时间序列分成多个patch，使用简化注意力机制捕捉长时间序列的局部模式。

#### 适用场景
- 长时间序列预测
- 需要捕捉局部模式

---

## 未来改进方向

1. ~~在线学习: 根据实际结果实时调整模型~~ ✅ 已实现
2. ~~多任务学习: 同时预测多个阈值~~ ✅ 已实现（2026-04-30）
3. ~~变化点检测: 检测播放量增速突变~~ ✅ 已实现（2026-04-30）
4. ~~生存分析: 预测视频"停止增长"的时间~~ ✅ 已实现（2026-04-30）
5. ~~UP主历史表现贝叶斯估计~~ ✅ 已实现（2026-04-30）
6. ~~视频生命周期建模~~ ✅ 已实现（2026-04-30）
7. ~~PatchTST简化版（Transformer）~~ ✅ 已实现（2026-04-30）
8. **迁移学习**: 利用相似视频的历史数据
9. **元学习 (Meta-Learning)**: 快速适应新UP主/新视频类型
10. **多模态融合**: 结合视频标题、封面、描述等文本/图像特征

---

## 参考论文

1. Bass, F. M. (1969). A new product growth for model consumer durables.
2. Rogers, E. M. (2003). Diffusion of Innovations.
3. Hochreiter, S., & Schmidhuber, J. (1997). Long short-term memory.
4. Chen, T., & Guestrin, C. (2016). XGBoost: A scalable tree boosting system.
5. Freund, Y., & Schapire, R. E. (1997). A decision-theoretic generalization of on-line learning. (Hedge算法)
6. Granger, C. W. J. (1969). Investigating causal relations by econometric models. (Granger因果检验)
7. Kipf, T. N., & Welling, M. (2017). Semi-supervised classification with graph convolutional networks. (GCN)
8. Nie, Y., et al. (2023). A Time Series is Worth 64 Words: Long-term Forecasting with Transformers. (ICLR 2023, PatchTST)
9. Oreshkin, B. N., et al. (2020). N-BEATS: Neural basis expansion analysis for interpretable time series forecasting. (ICLR 2020)
10. Wu, H., et al. (2023). TimesNet: Temporal 2D-Variation Modeling for General Time Series Analysis. (ICLR 2023)
11. Zhou, H., et al. (2021). Informer: Beyond Efficient Transformer for Long Sequence Time-Series Forecasting. (AAAI 2021)
12. Goold, B., et al. (2019). Temporal Fusion Transformers for Interpretable Multi-horizon Time Series Forecasting. (ArXiv 2019)

---

*文档版本: 4.0*
*最后更新: 2026-04-30*
