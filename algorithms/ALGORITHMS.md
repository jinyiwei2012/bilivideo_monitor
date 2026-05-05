# B站视频播放量预测算法说明

本文档详细说明系统中所有75种预测算法的实现原理、数学公式和适用场景。

## 目录

1. [算法概述](#算法概述)
2. [基础速度模型](#基础速度模型)
3. [增长模型](#增长模型)
4. [扩散模型](#扩散模型)
5. [时间序列模型](#时间序列模型)
6. [深度学习](#深度学习)
7. [Transformer模型](#transformer模型)
8. [统计模型](#统计模型)
9. [集成学习](#集成学习)
10. [集成模型](#集成模型)
11. [互动率模型](#互动率模型)
12. [高级分析](#高级分析)
13. [贝叶斯模型](#贝叶斯模型)
14. [生命周期模型](#生命周期模型)
15. [多任务学习](#多任务学习)
16. [线性模型](#线性模型)
17. [算法选择建议](#算法选择建议)
18. [算法评估指标](#算法评估指标)
19. [高级模块](#高级模块)
20. [未来改进方向](#未来改进方向)
21. [参考论文](#参考论文)

---

## 算法概述

### 预测目标
预测视频播放量从当前值增长到目标阈值（10万/100万/1000万）所需的时间。

### 输入数据
- 当前播放量
- 历史监控数据（时间序列）
- 视频信息（标题、UP主、互动数据等）

### 输出结果
- 预测所需时间（小时）
- 置信度（0-1）
- 元数据（算法参数、特征等）

---

## 基础速度模型

### 1. 线性速度算法 (Linear Velocity)

**文件**: `models/simple/linear_velocity.py`

#### 原理
假设播放量以恒定速度增长，基于当前速度线性外推。

#### 数学公式
```
V = ΔViews / ΔTime
T = (Target - Current) / V
```

#### 适用场景
- 视频处于稳定增长期
- 数据点较少时的简单预测

---

## 增长模型

### 2. 指数增长 (Exponential Growth)

**文件**: `models/growth/exponential_growth.py`

#### 原理
假设播放量增长速度与当前播放量成正比：dV/dt = r * V，解为 V(t) = V₀ * exp(r * t)。

适合视频发布初期的快速增长阶段，此时推荐算法带来的曝光与播放量正相关。

内置指数衰减机制，防止长期过度外推。

#### 适用场景
- 发布早期（前几周）快速增长的视频
- 初始推荐流量大的视频

### 3. 对数增长 (Logarithmic Growth)

**文件**: `models/growth/logarithmic_growth.py`

#### 原理
播放量随时间呈对数增长，增长速度逐渐减慢但永不为零。

```
Views(t) = a * ln(t + b) + c
```

#### 适用场景
- 长期缓慢增长的视频（长尾内容）

### 4. 幂律增长 (Power Law)

**文件**: `models/growth/power_law.py`

#### 原理
播放量增长遵循幂律分布：Views(t) = a * t^b。b < 1 时增长减速，b > 1 时增长加速。

#### 适用场景
- 病毒式传播视频
- 初期爆发性增长

### 5. Gompertz增长模型

**文件**: `models/growth/gompertz.py` / `models/growth/gompertz_growth.py`

#### 原理
S型增长曲线，初期慢、中期快、后期饱和。

```
Views(t) = a * exp(-b * exp(-c*t))
```

#### 适用场景
- 有明显生命周期的视频

### 6. Logistic增长模型

**文件**: `models/growth/logistic_growth.py`

#### 原理
经典的S型增长模型：dN/dt = r*N*(1 - N/K)，解为 N(t) = K / (1 + ((K-N0)/N0) * exp(-rt))。

#### 适用场景
- 有明显上限的视频内容

### 7. Richards曲线

**文件**: `models/growth/richards_curve.py`

#### 原理
广义的Logistic曲线，增加形状参数提供更灵活的增长模式。

```
Y(t) = A / (1 + exp(-k*(t-t0)))^(1/ν)
```

### 8. Weibull增长模型

**文件**: `models/growth/weibull_growth.py`

#### 原理
灵活的分布模型：F(t) = 1 - exp(-(t/λ)^k)。k<1 减速，k>1 加速。

---

## 扩散模型

### 9. Bass扩散模型 (Bass Diffusion)

**文件**: `models/advanced/bass_diffusion.py`

#### 原理
基于创新扩散理论，模拟产品/内容在市场中的传播过程。区分两种传播机制：
1. **创新效应 (p)**: 外部影响，如平台推荐
2. **模仿效应 (q)**: 内部口碑传播，如分享

#### 累积函数
```
F(t) = m * (1 - exp(-(p+q)*t)) / (1 + (q/p)*exp(-(p+q)*t))
```

---

## 时间序列模型

### 10. ARIMA模型

**文件**: `models/time_series/arima_simple.py`

#### 原理
自回归积分滑动平均模型：ARIMA(p,d,q) = 自回归 + 差分 + 移动平均。

### 11. SARIMA季节预测 (Seasonal ARIMA)

**文件**: `models/time_series/sarima_simple.py`

#### 原理
在标准 ARIMA(p,d,q) 基础上加入季节性成分 (P,D,Q,m)，捕捉星期周期性。

对于B站视频，周周期（m=7）能有效刻画工作日/周末的播放量差异。

#### 数学公式
```
SARIMA(p,d,q)(P,D,Q)m:
(1-ΣφᵢLⁱ)(1-ΦₛLˢ)(1-L)ᵈ(1-Lˢ)ᴰyₜ = (1+ΣθᵢLⁱ)(1+ΘₛLˢ)εₜ
```

#### 核心流程
1. 差分 + 季节性差分平稳化
2. AR成分拟合自回归系数
3. MA成分拟合滑动平均系数
4. 季节性成分提取周期模式
5. 合成预测

#### 置信度
综合考虑季节性强度和数据点数量：
```python
seasonal_strength = std(seasonal_pattern) / std(views)
conf = 0.35 + 0.25 * n_points_conf + 0.2 * seasonal_strength
```

### 12. 指数平滑 (Exponential Smoothing)

**文件**: `models/time_series/exponential_smoothing.py`

#### 原理
给近期观测更高权重：s_t = α*y_t + (1-α)*s_{t-1}。

### 13. Holt-Winters

**文件**: `models/time_series/holt_winters.py`

#### 原理
考虑趋势和季节性的三重指数平滑。

### 14. 移动平均 (Moving Average)

**文件**: `models/time_series/moving_average.py`

### 15. 加权移动平均 (Weighted Moving Average)

**文件**: `models/time_series/weighted_moving_average.py`

### 16. 线性增长 (Linear Growth)

**文件**: `models/time_series/linear_growth.py`

### 17. 趋势外推 (Trend Extrapolation)

**文件**: `models/time_series/trend_extrapolation.py`

### 18. 趋势回归 (Trend Regression)

**文件**: `models/time_series/trend_regression.py`

### 19. Theta预测

**文件**: `models/time_series/theta_forecast.py`

#### 原理
M3预测竞赛获胜方法。通过改变时间序列曲率生成两条Theta线，组合得到最终预测。

### 20. Prophet预测

**文件**: `models/time_series/prophet_simple.py`

#### 原理
Facebook开源的时间序列预测工具，基于加法模型。

### 21. 多季节分解 (Multi-Seasonal Decomposition)

**文件**: `models/time_series/multi_seasonal_decomposition.py`

#### 原理
同时考虑日周期和周周期模式，将时间序列分解为：

```
Views = Trend + Daily_Seasonal + Weekly_Seasonal + Residual
```

分别建模后再合成预测，能更准确地捕捉复合周期模式。

#### 分解流程
1. **趋势分量**: 双边移动平均提取长期趋势
2. **日周期分量**: 按24小时周期计算逐时段均值
3. **周周期分量**: 从日周期残差中提取7天周期模式
4. **残差**: 去除趋势和所有周期后的噪声

#### 适用场景
- 有足够历史数据（>10个点）
- 播放量呈现明显的日/周周期性
- 需要区分短期波动和长期趋势

### 22. 马尔可夫体制转换 (Markov Regime Switching)

**文件**: `models/time_series/markov_switching.py`

#### 原理
B站视频播放量通常经历不同阶段：快速增长期（推荐流量大）→ 稳定增长期（日常搜索）→ 衰退期。

模型使用隐马尔可夫链描述体制之间的转换，每个体制内用独立的增长参数。

#### 前向算法
```python
# 每个时间点计算属于各体制的概率
obs_prob = exp(-0.5 * ((growth - mean) / std)^2)
alpha = obs_prob * (alpha @ transition_matrix)
```

#### 蒙特卡洛模拟
通过200次未来路径模拟，取中位数作为预测：
1. 从当前体制概率分布采样初始体制
2. 按转移矩阵逐日模拟体制转换
3. 从各体制的增长分布采样日增长量
4. 统计到达阈值的天数分布

#### 适用场景
- 增长速度频繁变化的视频
- 需要区分"是否还在推荐期"
- 长周期视频的趋势预测

---

## 深度学习

### 23. MLP预测器

**文件**: `models/deep_learning/mlp_predictor.py`

### 24. 神经网络 (Neural Network)

**文件**: `models/deep_learning/neural_network_simple.py`

#### 架构
```
输入层 -> 隐藏层1 (64, ReLU) -> 隐藏层2 (32, ReLU) -> 输出层 (1)
```

### 25. LSTM时序预测

**文件**: `models/deep_learning/lstm_simple.py`

#### 原理
长短期记忆网络，专门处理时间序列数据。

### 26. GRU简化预测

**文件**: `models/deep_learning/gru_simple.py`

#### 原理
GRU 使用更新门和重置门替代 LSTM 的三个门，参数更少、训练更快。
研究表明在播放量预测任务上 GRU 通常优于 LSTM。

#### 门控机制
```python
z = sigmoid(0.3*log_vel + 0.2*growth_rate - 0.15*norm_age)  # 更新门
r = sigmoid(0.25*log_views + 0.3*quality - 0.1*norm_age)     # 重置门
h' = tanh(r * log_vel + 0.3*quality + 0.2*growth_rate)        # 候选状态
h = (1-z) * h_prev + z * h'                                     # 新隐藏状态
```

### 27. BiLSTM双向预测 (Bidirectional LSTM)

**文件**: `models/deep_learning/bilstm_simple.py`

#### 原理
同时从正向和反向处理时间序列：
- **正向LSTM**: 从过去看到现在 -- 捕获趋势惯性
- **反向LSTM**: 从现在看到过去 -- 抑制过度外推

最终输出 = 正向隐藏状态 + 反向隐藏状态

#### LSTM单元
```python
f = sigmoid(Wf*h_prev + Xf*x + bf)  # 遗忘门
i = sigmoid(Wi*h_prev + Xi*x + bi)  # 输入门
c = f*c_prev + i*tanh(Wc*h_prev + Xc*x + bc)  # 记忆更新
o = sigmoid(Wo*h_prev + Xo*x + bo)  # 输出门
h = o * tanh(c)
```

#### 综合策略
正向趋势驱动 + 反向修正，防止在数据不足时过度外推。

### 28. TCN卷积预测 (Temporal Convolutional Network)

**文件**: `models/deep_learning/tcn_simple.py`

#### 原理
使用空洞因果卷积 (Dilated Causal Convolution) 构建时序模型。相比RNN系列：
- 训练更稳定（无梯度爆炸/消失）
- 可通过空洞卷积指数级扩大感受野
- 支持并行计算

#### TCN残差块
每层包含：
1. 空洞因果卷积（确保未来信息不泄漏到过去）
2. ReLU激活
3. Dropout正则化
4. 残差连接（恒等映射）

#### 感受野计算
```
Receptive Field = 1 + 2*(K-1) * Sigma(dilations)
```
当 dilations = [1,2,4,8,16,32] 时，感受野指数级增长。

#### 适用场景
- 中等长度时间序列（10-100个点）
- 需要稳定训练的深度学习方案
- 替代LSTM的轻量级选择

### 29. CNN-LSTM混合模型

**文件**: `models/deep_learning/cnn_lstm_hybrid.py`

#### 原理
结合CNN和RNN的优点：
1. **CNN阶段**: 多尺度卷积核提取局部时序模式（日周期、突发增长）
2. **LSTM阶段**: 从CNN特征中建模长期依赖

#### 多尺度卷积
```python
# 使用不同大小的卷积核
kernel_sizes = [3, 5]
# 边缘检测核: 捕捉变化率
edge_kernel = [-1, 0, 1]  # k=3
# 平滑核: 捕捉均值趋势
smooth_kernel = [1/3, 1/3, 1/3]  # k=3
```

#### 适用场景
- 数据同时包含局部模式和长期趋势
- 播放量有突发性变化（推荐波动）
- 需要比纯LSTM更稳健的特征提取

### 30. N-BEATS简化版

**文件**: `models/deep_learning/n_beats_simple.py`

#### 原理
使用基函数展开捕捉时序模式。将预测分解为多个block，每个block输出回看分量和预测分量。

### 31. TimesNet简化版

**文件**: `models/deep_learning/timess_net_simple.py`

#### 原理
将1D时间序列转换为2D，捕获周期内和周期间的模式。

### 32. DLinear简化版

**文件**: `models/deep_learning/dlinear_simple.py`

#### 原理
将序列分解为趋势分量和剩余分量，分别使用线性映射后叠加。

---

## Transformer模型

### 33. 注意力机制 (Attention Mechanism)

**文件**: `models/deep_learning/attention_mechanism.py`

### 34. Informer简化版

**文件**: `models/deep_learning/informer_simple.py`

#### 原理
高效Transformer，使用ProbSparse自注意力将复杂度从O(L平方)降低到O(L log L)。

### 35. TFT简化版 (Temporal Fusion Transformer)

**文件**: `models/deep_learning/tft_simple.py`

#### 原理
结合静态/动态特征，使用变量选择网络、门控残差网络和时态自注意力。

### 36. PatchTST简化版

**文件**: `models/deep_learning/patch_tst_simple.py`

#### 原理
将时间序列分成多个patch，使用简化注意力机制捕捉长时间序列的局部模式。

---

## 统计模型

### 37. 高斯过程 (Gaussian Process)

**文件**: `models/statistical/gaussian_process.py`

### 38. 贝叶斯回归 (Bayesian Regression)

**文件**: `models/statistical/bayesian_regression.py`

### 39. ElasticNet回归

**文件**: `models/statistical/elasticnet_regression.py`

#### 原理
结合L1(Lasso)和L2(Ridge)正则化的线性回归。使用坐标下降法优化。

### 40. Huber鲁棒回归

**文件**: `models/statistical/huber_regression.py`

#### 原理
使用 Huber 损失函数（MSE + MAE 混合）的线性回归。使用IRLS（迭代加权最小二乘）拟合。

### 41. Theil-Sen回归 (Theil-Sen Regression)

**文件**: `models/statistical/theil_sen_regression.py`

#### 原理
非参数回归方法。计算所有数据点对之间斜率的中位数作为回归斜率，对异常值的容忍度高达29.3%。

#### 数学公式
```python
slope = median((y_j - y_i) / (x_j - x_i) for all i < j)
intercept = median(y_i - slope * x_i)
```

对大数据集采用随机子采样（最多2000个点对），保证计算效率。

#### 趋势一致性评估
将时序分段计算各段斜率，评估趋势稳定性。

#### 适用场景
- 存在异常值/突发高峰的数据
- 需要稳健趋势估计的场景
- 与普通最小二乘对比使用

### 42. 分位数回归 (Quantile Regression)

**文件**: `models/statistical/quantile_regression.py`

#### 原理
同时估计多个条件分位数，提供完整预测分布：
- tau=0.25: 悲观情景
- tau=0.50: 中位数预测（最稳健）
- tau=0.75: 乐观情景

#### 分位数损失
```python
loss = mean(max(tau*(y-y_pred), (tau-1)*(y-y_pred)))
```

使用梯度下降优化，学习率自动衰减。

#### 预测区间
预测区间宽度（乐观-悲观）反映不确定性。

#### 适用场景
- 需要评估预测不确定性
- 风险管理场景
- 对比不同情景下的策略

### 43. 泊松回归 (Poisson Regression)

**文件**: `models/statistical/poisson_regression.py`

#### 原理
播放量增量为非负整数，使用泊松分布的广义线性模型（GLM）更合理。

连接函数: log link，即 log(E[y]) = X*beta

使用IRLS（迭代加权最小二乘）拟合。

#### 拟合优度
使用伪R方评估：
```python
deviance = 2 * sum(y*log(y/y_pred) - (y-y_pred))
pseudo_r2 = 1 - deviance / null_deviance
```

#### 适用场景
- 播放量增量偏小且呈计数分布
- 数据存在过度离散时

### 44. SVR支持向量回归

**文件**: `models/statistical/svr_predictor.py`

### 45. 随机森林 (Random Forest)

**文件**: `models/statistical/random_forest_simple.py`

---

## 集成学习

### 46. AdaBoost自适应提升

**文件**: `models/ensemble/adaptive_boosting.py`

### 47. Gradient Boosting梯度提升

**文件**: `models/ensemble/gradient_boost_simple.py`

### 48. XGBoost

**文件**: `models/ensemble/xgboost_simple.py`

### 49. LightGBM

**文件**: `models/ensemble/lightgbm_simple.py`

### 50. CatBoost

**文件**: `models/ensemble/catboost_simple.py`

### 51. ExtraTrees极端随机树

**文件**: `models/ensemble/extra_trees_simple.py`

#### 原理
在随机森林基础上增加随机化程度：
1. **不使用Bootstrap采样**: 使用全部训练数据
2. **随机分割点**: 分裂时随机选择分割点（而非最优分割点）

这些随机化进一步降低方差，在某些数据集上表现优于随机森林。

#### 算法流程
```python
for each tree:
    for each node:
        随机选择特征子集
        在特征范围内随机选择分割点
        按方差减少评估分割质量
        构建左右子树
最终预测 = 所有树的平均值
```

#### 置信度
基于树间预测标准差评估一致性。

### 52. Bagging集成

**文件**: `models/ensemble/bagging_simple.py`

#### 原理
Bootstrap Aggregating：通过对训练数据有放回采样（Bootstrap），训练多个基学习器，最终预测取所有学习器的平均。

#### 参数
```python
n_estimators = 25    # 基学习器数量
max_samples = 0.8    # 每个学习器的采样比例
max_depth = 5        # 限制树深度防止过拟合
```

#### Bagging vs ExtraTrees
| 特性 | Bagging | ExtraTrees |
|------|---------|------------|
| 数据采样 | Bootstrap (有放回) | 全部数据 |
| 分割点选择 | 最优分割 | 随机分割 |
| 方差降低 | 通过平均化 | 通过随机化 |
| 偏差 | 较低 | 略高 |

### 53. Cascade级联集成

**文件**: `models/ensemble/cascade_ensemble.py`

#### 原理
与传统并行集成不同，级联集成将预测器按顺序排列，每个预测器的输出作为额外特征输入下一个预测器。

#### 三级级联
```
Level 1 (线性趋势): 简单线性斜率预测
    | 输出传递给Level 2
Level 2 (指数平滑): SES + L1修正
    | 输出传递给Level 3
Level 3 (季节性感知): 周周期 + L2修正
    |
最终预测
```

#### 级间一致性
三级预测越一致，置信度越高。

参考: Linardatos et al. (2024), "Regressor cascading for time series forecasting"

---

## 集成模型

### 54. 加权集成 (Weighted Ensemble)

**文件**: `models/ensemble/ensemble_weighted.py`

### 55. 投票集成 (Voting Ensemble)

**文件**: `models/ensemble/ensemble_voting.py`

### 56. 堆叠集成 (Stacking)

**文件**: `models/ensemble/ensemble_stacking.py`

### 57. 平均集成 (Average Ensemble)

**文件**: `models/ensemble/ensemble_average.py`

### 58. 加权速度 (Weighted Velocity)

**文件**: `models/ensemble/weighted_velocity.py`

---

## 互动率模型

### 59. 点赞动量 (Like Momentum)

**文件**: `models/advanced/like_momentum.py`

### 60. 分享速度 (Share Velocity)

**文件**: `models/advanced/share_velocity.py`

### 61. 评论趋势 (Comment Trend)

**文件**: `models/time_series/comment_trend.py`

### 62. 投币Boost (Coin Boost)

**文件**: `models/ensemble/coin_boost.py`

### 63. 互动率综合 (Engagement Rate)

**文件**: `models/advanced/engagement_rate.py`

### 64. 内容质量评分 (Quality Score)

**文件**: `models/advanced/quality_score.py`

### 65. 病毒潜力 (Viral Potential)

**文件**: `models/advanced/viral_potential.py`

---

## 高级分析

### 66. 卡尔曼滤波 (Kalman Filter)

**文件**: `models/advanced/kalman_filter.py`

### 67. 变化点检测 (Change Point Detection)

**文件**: `models/advanced/change_point_detection.py`

#### 原理
使用CUSUM（累积和）算法检测播放量增速的突变点。

### 68. 生存分析 (Survival Analysis)

**文件**: `models/advanced/survival_analysis.py`

#### 原理
预测视频"停止增长"的时间。使用Kaplan-Meier估计的简化版。

### 69. 视频生命周期建模 (Lifecycle Modeling)

**文件**: `models/advanced/lifecycle_modeling.py`

### 70. Hawkes自激过程 (Hawkes Self-Exciting Process)

**文件**: `models/advanced/hawkes_process.py`

#### 原理
B站视频播放量的增长具有自激励特性：一个视频获得播放后，可能通过推荐算法触发更多播放（级联效应）。

#### 强度函数
```
lambda(t) = mu + sum phi(t - t_i)
phi(tau) = kappa * (tau + c)^(-(1+theta))
```
其中：
- mu: 基础强度（自然流量）
- kappa: 激励强度（推荐效率）
- theta: 幂律衰减指数（热度消退速度）
- c: 截止参数

#### 分支比（病毒性指标）
```
Branching Ratio = kappa / (theta * c^theta)
```
- **分支比 > 1**: 超临界状态，病毒式传播
- **分支比 < 1**: 亚临界状态，自然衰减

#### 参数适配
```python
# 互动率高的视频激励更强
kappa = 0.2 + 0.4 * (quality * 0.6 + engagement * 0.4)
# 高质量视频热度衰减更慢
theta = 1.5 - 0.5 * engagement
```

#### 适用场景
- 病毒式传播视频
- 需要量化"是否在病毒期"
- 理解推荐算法带来的级联效应

参考: Dong et al. (2022), "Universal scaling behavior and Hawkes process of videos' views on Bilibili.com"

---

## 贝叶斯模型

### 71. UP主历史表现贝叶斯模型 (UPcaster History Bayesian)

**文件**: `models/statistical/upcaster_history_bayesian.py`

#### 原理
利用UP主历史数据，通过贝叶斯估计提升预测准确性。

---

## 生命周期模型

### 72. 视频生命周期建模

**文件**: `models/advanced/lifecycle_modeling.py`

| 阶段 | 速度范围 | 策略 |
|------|---------|------|
| 导入期 | < 50/h | 平均增速外推 |
| 成长期 | >= 50/h | 近期速度 x1.1 |
| 成熟期 | 10-50/h | 指数衰减 |
| 衰退期 | < 10/h | 长期趋势外推 |
| 病毒期 | >= 500/h | 根据加速度调整 |

---

## 多任务学习

### 73. 多任务学习简化版 (Multi-Task Learning)

**文件**: `models/advanced/multi_task_simple.py`

#### 原理
同时预测多个阈值（10万/100万/1000万），利用任务间的相关性提高预测准确性。

---

## 线性模型

### 74. DLinear简化版

**文件**: `models/deep_learning/dlinear_simple.py`

---

## 算法选择建议

### 按视频阶段选择

| 视频阶段 | 推荐算法 | 原因 |
|---------|---------|------|
| 新发布 (<24h) | 线性速度、指数增长 | 数据少，简单模型更稳定 |
| 增长期 (1-7天) | Bass扩散、指数衰减、TCN | 捕捉增长趋势 |
| 稳定期 (>7天) | 对数增长、SARIMA、多季节分解 | 长期缓慢增长+周期 |
| 爆发期 | Hawkes过程、病毒潜力 | 捕捉病毒传播特征 |
| 波动期 | 马尔可夫体制转换、变化点检测 | 处理增长模式切换 |

### 按数据量选择

| 数据点 | 推荐算法 |
|-------|---------|
| < 5 | 线性速度、指数增长 |
| 5-20 | 指数衰减、Bass扩散、Theil-Sen |
| 20-50 | ARIMA、ExtraTrees、Bagging |
| 50-100 | SARIMA、BiLSTM、CNN-LSTM |
| > 100 | LSTM、TCN、集成模型 |

### 按数据特征选择

| 数据特征 | 推荐算法 |
|---------|---------|
| 有异常值 | Theil-Sen回归、Huber回归 |
| 有周期性 | SARIMA、多季节分解、Holt-Winters |
| 有体制转换 | 马尔可夫体制转换、变化点检测 |
| 计数型增量 | 泊松回归 |
| 需评估不确定性 | 分位数回归 |
| 病毒式传播 | Hawkes过程 |
| 有UP主历史 | UP主贝叶斯 |

### 集成策略

系统默认使用加权集成（`_weighted`），权重由 `WeightManager` 基于历史预测准确率动态调整，结合 `OnlineLearner`（Hedge算法）在线学习各算法的表现。

---

## 算法评估指标

### 准确性指标
- **MAE**: 平均绝对误差
- **MAPE**: 平均绝对百分比误差
- **RMSE**: 均方根误差

### 可靠性指标
- **置信度**: 算法自身评估的可靠性（0-1）
- **覆盖率**: 成功预测的比例
- **稳定性**: 多次预测的一致性

---

## 高级模块

### 在线学习 (OnlineLearner)

**文件**: `online_learner.py`

使用 **Hedge 算法**（指数权重专家混合）动态调整各算法权重。

#### 核心机制
```
每次实际值到达后：
1. 计算每个算法的相对误差 error = |predicted - actual| / actual
2. 累积损失 L_i += ln(1 + error_i)
3. 更新权重 w_i 与 exp(-eta x (L_i - min_L))
4. 归一化后输出推荐权重
```

### 因果推断 (CausalAnalyzer)

**文件**: `causal_inference.py`

使用 **Granger 因果检验**（OLS简化实现）检验各指标是否领先于播放量变化。

### 图神经网络 (VideoGraph)

**文件**: `graph_neural.py`

构建视频关联图，使用简化 **GCN**（图卷积网络）学习节点嵌入。

#### 图构建规则
| 边类型 | 权重 | 说明 |
|--------|------|------|
| 同UP主 | 0.5 | 强关联 |
| 发布时间接近 | 0~0.3 | 48h内线性衰减 |
| 互动率相似 | 0~0.2 | 差异越小权重越高 |

---

## 未来改进方向

1. ~~在线学习: 根据实际结果实时调整模型~~ 已实现
2. ~~多任务学习: 同时预测多个阈值~~ 已实现
3. ~~变化点检测: 检测播放量增速突变~~ 已实现
4. ~~生存分析: 预测视频停止增长的时间~~ 已实现
5. ~~UP主历史表现贝叶斯估计~~ 已实现
6. ~~视频生命周期建模~~ 已实现
7. ~~PatchTST简化版~~ 已实现
8. ~~TCN时序卷积网络~~ 已实现
9. ~~BiLSTM双向预测~~ 已实现
10. ~~CNN-LSTM混合模型~~ 已实现
11. ~~SARIMA季节性预测~~ 已实现
12. ~~Hawkes自激过程~~ 已实现
13. ~~马尔可夫体制转换~~ 已实现
14. ~~ExtraTrees/Bagging/Cascade集成~~ 已实现
15. ~~Theil-Sen/分位数/泊松回归~~ 已实现
16. ~~多季节分解~~ 已实现
17. ~~指数增长~~ 已实现
18. **迁移学习**: 利用相似视频的历史数据
19. **元学习 (Meta-Learning)**: 快速适应新UP主/新视频类型
20. **多模态融合**: 结合视频标题、封面、描述等文本/图像特征
21. **大模型时序预测**: 借鉴Chronos、TimesFM等基础模型

---

## 参考论文

1. Bass, F. M. (1969). A new product growth for model consumer durables.
2. Rogers, E. M. (2003). Diffusion of Innovations.
3. Hochreiter, S., & Schmidhuber, J. (1997). Long short-term memory.
4. Cho, K., et al. (2014). Learning phrase representations using RNN encoder-decoder. (GRU)
5. Bai, S., et al. (2018). An empirical evaluation of generic convolutional and recurrent networks for sequence modeling. (TCN)
6. Chen, T., & Guestrin, C. (2016). XGBoost: A scalable tree boosting system.
7. Ke, G., et al. (2017). LightGBM: A highly efficient gradient boosting decision tree.
8. Freund, Y., & Schapire, R. E. (1997). A decision-theoretic generalization of on-line learning. (Hedge)
9. Granger, C. W. J. (1969). Investigating causal relations by econometric models.
10. Kipf, T. N., & Welling, M. (2017). Semi-supervised classification with graph convolutional networks.
11. Nie, Y., et al. (2023). A Time Series is Worth 64 Words. (ICLR 2023, PatchTST)
12. Oreshkin, B. N., et al. (2020). N-BEATS. (ICLR 2020)
13. Wu, H., et al. (2023). TimesNet. (ICLR 2023)
14. Zhou, H., et al. (2021). Informer. (AAAI 2021)
15. Dong, et al. (2022). Universal scaling behavior and Hawkes process of videos' views on Bilibili.com.
16. Assimakopoulos, V., & Nikolopoulos, K. (2000). The theta model: a decomposition approach to forecasting.
17. Koenker, R., & Hallock, K. F. (2001). Quantile regression.
18. Theil, H. (1950). A rank-invariant method of linear and polynomial regression analysis.
19. Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau.
20. Linardatos, P., et al. (2024). Regressor cascading for time series forecasting.
21. Box, G. E. P., et al. (2015). Time Series Analysis: Forecasting and Control. (SARIMA)

---

*文档版本: 5.0*
*最后更新: 2026-05-05*
*算法总数: 75*
