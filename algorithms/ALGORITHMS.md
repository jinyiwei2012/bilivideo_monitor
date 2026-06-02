# B站视频播放量预测算法说明

本文档详细说明系统中所有141种预测算法的实现原理、数学公式和适用场景。

## 目录

1. [算法概述](#算法概述)
2. [基础速度模型](#基础速度模型)
3. [增长/衰减模型](#增长衰减模型)
4. [扩散模型](#扩散模型)
5. [时间序列模型](#时间序列模型)
6. [深度学习](#深度学习)
7. [Transformer模型](#transformer模型)
8. [统计模型](#统计模型)
9. [机器学习](#机器学习)
10. [集成模型](#集成模型)
11. [互动率模型](#互动率模型)
12. [高级分析](#高级分析)
13. [概率/贝叶斯模型](#概率贝叶斯模型)
14. [生命周期模型](#生命周期模型)
15. [多任务学习](#多任务学习)
16. [线性模型](#线性模型)
17. [频域分析](#频域分析)
18. [事件驱动](#事件驱动)
19. [内容感知](#内容感知)
20. [算法选择建议](#算法选择建议)
21. [算法评估指标](#算法评估指标)
22. [高级模块](#高级模块)
23. [时间序列交叉验证与回测](#时间序列交叉验证与回测)
24. [特征工程](#特征工程)
25. [数据清洗模块](#数据清洗模块)
26. [PyTorch 训练管线](#pytorch-训练管线)
27. [未来改进方向](#未来改进方向)
28. [参考论文](#参考论文)

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

## 增长/衰减模型

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

### 指数衰减 (Exponential Decay)

**文件**: `models/time_series/exponential_decay.py`

#### 原理
假设播放量增速随时间指数衰减：`V(t) = V₀ * exp(-λ * t)`。适合视频推荐热度消退后的自然衰减期，衰减率 λ 由历史数据拟合。

#### 适用场景
- 播放量增速持续下降的视频
- 长时间未获得推荐流量的老视频

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

### 22. MSTL多重季节分解 (Multiple Seasonal-Trend decomposition)

**文件**: `models/time_series/mstl_decomposition.py`

#### 原理
将播放量序列迭代分解为多重季节分量 + 趋势 + 残差，对每类成分分别预测后合成。使用 `statsmodels.tsa.seasonal.MSTL`（statsmodels >= 0.14），自动检测周/月周期。

#### 降级链
statsmodels MSTL → savgol_filter → velocity 兜底

### 23. TBATS季节分解

**文件**: `models/time_series/tbats_simple.py`

#### 原理
三角函数处理多重季节性（日/周/月），Box-Cox变换后分解趋势与季节成分，残差拟合一阶自回归(AR)模型。三角函数周期用 cos/sin 基函数表示。

#### 降级链
Box-Cox + 三角函数 → numpy 实现 → velocity 兜底

### 24. GARCH波动率聚集 (GARCH)

**文件**: `models/time_series/garch_simple.py`

#### 原理
广义自回归条件异方差模型，建模播放量增量的波动率聚集效应（如爆款后波动衰减）。输出带置信区间的概率预测，适合评估不确定性。

#### 数学公式
```
σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}
```
预测速度 = (μ + σ) × views_last / 3600

#### 降级链
numpy GARCH → velocity 兜底

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

### 25. NARX外生自回归

**文件**: `models/time_series/narx_simple.py`

#### 原理
带外生输入的非线性自回归模型。将历史播放量差分作为自回归项，同时引入互动数据（点赞、投币、收藏的差分）作为外生变量。用最小二乘拟合线性权重后外推。可捕捉互动指标对播放量的领先效应。

#### 数学公式
```
Δviews(t) = β₀ + Σᵢ₌₁ᵖ (αᵢ·Δviews(t-i) + βᵢ·Δlikes(t-i) + γᵢ·Δcoins(t-i) + δᵢ·Δfavs(t-i))
```

#### 适用场景
- 互动数据丰富的视频
- 需要量化互动对播放量的拉动效应

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

### 33. CNN图像化预测 (CNN Image)

**文件**: `models/deep_learning/cnn_image.py`

#### 原理
将 1D 时序窗口重塑为 2D 图像矩阵，使用多扩张率 Conv2d 同时沿时间方向和特征方向提取局部模式。多分支结构（不同 dilation）捕捉多尺度时序特征。

#### 降级链
torch Conv2d → numpy 滑动均值 → velocity 兜底

### 34. Diffusion TS扩散预测 (Denoising Diffusion Probabilistic Model)

**文件**: `models/deep_learning/diffusion_ts.py`

#### 原理
将时序预测建模为条件生成任务。训练阶段对目标序列逐步加噪（100步线性β调度），用 UNet1D 预测添加的噪声；推理阶段从纯高斯噪声开始，100步反向去噪得到预测值。PyTorch 实现 + DDPM 框架。

#### 降级链
torch 反向扩散 → numpy 简化版（高斯采样）→ velocity 兜底

### 35. KNF Koopman预测 (Koopman Neural Forecaster, ICLR 2023)

**文件**: `models/deep_learning/knf.py`

#### 原理
将非线性时序通过编码器映射到 Koopman 不变子空间，在该空间内时间动态变为线性演化 `K·z_t → z_{t+1}`。包含全局共享 Koopman 矩阵（跨视频通用规律）和局部自适应矩阵（元网络预测的单视频微调），支持反馈循环逐步预测。

#### 降级链
torch KNF → numpy 简化版（全局线性+滑动均值）→ velocity 兜底

### 36. Mar-BiLSTM马尔可夫 (Markov-augmented BiLSTM)

**文件**: `models/deep_learning/mar_bilstm.py`

#### 原理
BiLSTM 编码短期上下文，可学习的马尔可夫转移矩阵建模长期状态演化。维护 N 个可学习"状态原型"（增长/衰减/爆发/稳定/震荡等），软分配当前样本到原型分布，用马尔可夫矩阵多步演化后解码出预测速度。

#### 降级链
torch → numpy（双向 EMA + 简单状态分配）→ velocity 兜底

### 37. TIDE稠密编码器 (Time Series Dense Encoder)

**文件**: `models/deep_learning/tide_simple.py`

#### 原理
基于残差MLP的轻量时序预测。用二次多项式拟合趋势得到"编码器"窗口，外推趋势后叠加季节模版（tile重复）得到最终预测。结构极简但在多种数据集上超越复杂Transformer（Zeng et al., AAAI 2023）。

#### Torch模型
`TIDETorchModel`: 残差 MLP 编码器-解码器，`MLP(hidden=64) + residual skip`

### 38. TSMixer MLP混合器

**文件**: `models/deep_learning/tsmixer_simple.py`

#### 原理
纯MLP架构，交替在时间维和通道维做MLP混合。极轻量化、训练快，在小样本播放量数据上不易过拟合。随机权重矩阵 + GELU激活。

#### Torch模型
`TSMixerTorchModel`: 时间维MLP + 通道维MLP + LayerNorm 交替

### 39. DeepAR概率自回归

**文件**: `models/deep_learning/deepar_simple.py`

#### 原理
基于RNN的自回归概率预测模型。从历史回报率（return）分布采样200条未来路径，模拟未来播放量概率分布。输出中位数预测 + 25/75百分位区间。

#### Torch模型
`DeepARTorchModel`: GRU编码器 + mu/sigma双头输出概率分布

### 40. Chronos零样本基础模型

**文件**: `models/deep_learning/chronos_base.py`

#### 原理
基于T5架构的亚马逊时序基础模型。支持从 HuggingFace 加载 `amazon/chronos-t5-small` 预训练权重，零样本预测。无需微调，通过趋势分解+季节模式外推测速。

#### Torch模型
`ChronosTorchModel`: 轻量T5 Transformer编码器（2层）

### 41. Mamba S6状态空间模型

**文件**: `models/deep_learning/mamba_s6_simple.py`

#### 原理
2024年最热门的Transformer替代架构。通过选择性SSM高效建模播放量的长程依赖，线性复杂度。简化版用2维离散状态空间 `[z₁, z₂]` 逐步更新，A/B/C矩阵参数化。

#### Torch模型
`MambaS6TorchModel`: 离散SSM `state = A@state + B@x` → 线性头输出

### 42. iTransformer倒置Transformer

**文件**: `models/deep_learning/itransformer_simple.py`

#### 原理
将Transformer反转：把每个变量（播放量、点赞、投币、收藏）的时间序列作为token，用注意力机制捕捉跨指标的相关性。简化版用指标矩阵的自注意力 + 随机投影。

#### Torch模型
`ITransformerTorchModel`: 变量投影 + TransformerEncoder → 展平预测头

### 43. SCINet卷积交互网络

**文件**: `models/deep_learning/scinet_simple.py`

#### 原理
二叉树结构逐层下采样-卷积-交互，捕捉不同时间尺度上的模式（小时级爆发 vs 日级增长）。偶数/奇数索引子序列分别卷积，用差值门控交互。

#### Torch模型
`SCINetTorchModel`: 偶/奇分支Conv1d + 差值门控交互

### 44. TimesFM谷歌基础模型

**文件**: `models/deep_learning/timesfm_simple.py`

#### 原理
Google的Decoder-only预训练时序模型，在1亿+真实时间序列上预训练。基于Patch（子序列分块）+ Decoder架构，零样本预测。

#### Torch模型
`TimesFMTorchModel`: Patch分块投影 + TransformerDecoder + 线性输出

### 45. Time-MoE专家混合

**文件**: `models/deep_learning/time_moe_simple.py`

#### 原理
华为时序专家混合模型。4个专家分别学习不同增长阶段模式（冷启动/病毒传播/稳定增长/饱和），可训练门控网络自动选择最优专家。路由依据近期增长率+当前互动率。

#### Torch模型
`TimeMoETorchModel`: 特征投影 → 门控网络(softmax) → 4专家混合输出(summation)

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

### 37. Lag-Llama基础模型

**文件**: `models/deep_learning/lag_llama.py`

#### 原理
基于 Llama 架构的时序基础模型，从 HuggingFace（`time-series-foundation-models/Lag-Llama`）加载预训练权重，提取滞后特征后自回归解码，零样本预测播放量速度。无需视频侧微调。

#### 降级链
HF 零样本 → 滞后特征+自回归 → velocity 兜底

### 38. MOIRAI基础模型

**文件**: `models/deep_learning/moirai.py`

#### 原理
Salesforce 通用时序基础模型（`Salesforce/moirai-1.1-R-small`），在大规模公开时序数据上预训练。支持任意多变量时序的零样本预测，适用于速度 + 互动率等多维输入。

#### 降级链
HF 零样本 → 历史均值+趋势外推 → velocity 兜底

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

### 46. TSFC特征分类 (Time Series Feature Classification)

**文件**: `models/statistical/tsfc_classification.py`

#### 原理
从历史速度序列中提取多维统计特征（均值、方差、趋势、自相关、谱熵、峰度、偏度），用 sklearn RandomForestClassifier 将视频分类到若干"增长模式"桶（低速/匀速/爆发/衰减/震荡），用桶内历史平均速度作为预测速度。无需 GPU，即用即跑。

#### 降级链
sklearn 分类 → 近期均值兜底

### 47. DTW-kNN类比预测

**文件**: `models/statistical/dtw_knn.py`

#### 原理
用动态时间规整(DTW)距离从历史数据中检索增长模式最相似的k个片段，加权平均作为预测权重 = 1/dist。本质上是"类比推理"预测——找过去相似的走势来推测未来。考虑播放量、点赞、投币的三维梯度profile。

#### 适用场景
- 有充足历史数据（>20个点）
- 视频增长模式存在重复性
- 作为深度学习方法的轻量替代

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

### 59. NGBoost概率提升

**文件**: `models/ensemble/ngboost_simple.py`

#### 原理
自然梯度提升(Natural Gradient Boosting)，输出完整概率分布（高斯分布参数 μ, σ）。用自然梯度优化分布参数，适合建模播放量预测的不确定性。基于滞后特征（4阶视图+互动滞后）拟合。

#### 降级链
ngboost → velocity 兜底

### 60. TabNet注意力特征网络

**文件**: `models/ensemble/tabnet_simple.py`

#### 原理
带Transformer风格注意力机制的表格网络。用随机投影 + 门控注意力自动选择最重要的特征（播放量、点赞、投币、收藏、分享的log值及其梯度），输出趋势信号调整预测速度。

#### 降级链
numpy 注意力门控 → velocity 兜底

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

### 71. DistDF分布对齐 (Distribution Distance Forecasting)

**文件**: `models/advanced/distdf_align.py`

#### 原理
视频速度序列在不同阶段（冷启动 → 推荐期 → 衰减期）存在分布漂移。用 Wasserstein 距离衡量近期窗口与历史全局分布的差异：差异大时（分布漂移中）向全局均值收缩预测；差异小时（分布稳定）信任近期数据。无需训练，纯统计方法。

#### 降级链
scipy Wasserstein距离 → numpy 自实现 → 近期均值

### 72. 频域分解 (Fourier/Wavelet Decomposition)

**文件**: `models/advanced/fourier_wavelet.py`

#### 原理
将播放量序列通过FFT变换到频域，保留前1/4最强谐波滤除噪声，逆变换得到周期模式。线性趋势 + 周期波动叠加预测。无需训练，纯信号处理方法。

### 73. SIRD传染病传播模型

**文件**: `models/advanced/sird_model.py`

#### 原理
将视频传播类比传染病SIRD模型。S=易感粉丝数，I=当前活跃播放/传播，R=已观看，D=流失。用常微分方程(ODE)求解未来I+R曲线。参数β(传播率)、γ(恢复率)、δ(流失率)从实时数据估计。

### 74. CausalImpact因果推断

**文件**: `models/advanced/causal_impact.py`

#### 原理
贝叶斯结构时间序列模型。用点赞、投币、收藏等协变量构建反事实预测（若无互动会怎样），互动率变化与播放量差值即为"因果效应"。估算互动指标对播放量的增量贡献。

### 75. 层级贝叶斯 (Hierarchical Bayes)

**文件**: `models/advanced/hierarchical_bayes.py`

#### 原理
利用UP主级别的超参数共享信息（UP主历史平均播放量、投稿数），将新视频的播放量预测纳入层级结构进行收缩估计。本地数据方差大时向UP主全局均值收缩，数据充足时信任本地估计。

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

## 频域分析

新增类别 (2026-06)，将时序变换到频域进行分析与预测。

### 75. 小波分解 (Wavelet Decomposition)

**文件**: `models/frequency/wavelet_decomp.py`

#### 原理
用离散小波变换 (Haar小波) 将时序分解为多级近似系数和细节系数。在最低频分量上做多项式趋势拟合，过滤高频噪声（细节系数×0.3衰减）后逐级重建。适合去除非平稳噪声，提取干净的长期趋势。

---

### 76. 频谱残差 (Spectral Residual)

**文件**: `models/frequency/spectral_residual.py`

#### 原理
FFT → 对数幅度谱 → 均值滤波（背景谱） → 残差 = log谱 - 背景谱 → iFFT → 显著区域检测。将异常突发信号从正常趋势中分离，趋势分量用插值补齐突发区域后再外推。

---

### 77. 希尔伯特-黄变换 (Hilbert-Huang Transform)

**文件**: `models/frequency/hilbert_huang.py`

#### 原理
简化 EMD (经验模态分解) 迭代提取 IMF (固有模态函数) → 多尺度趋势合成。最低频 IMF 为残差趋势，各 IMF 分别计算增长率后加权。适合非平稳非线性时序。

---

## 事件驱动

新增类别 (2026-06)，借鉴金融技术分析和异常检测，识别播放量突变。

### 78. 脉冲检测 (Anomaly Spike Detection)

**文件**: `models/event/anomaly_spike.py`

#### 原理
滑动窗口 Z-score (阈值2.0) 检测播放量异常脉冲 → 分离基线增长和脉冲幅度 → 指数衰减建模脉冲后回落。适合区分自然增长与被平台推荐/热搜等事件驱动的短期脉冲。

---

### 79. 动量突破 (Momentum Breakout)

**文件**: `models/event/momentum_breakout.py`

#### 原理
借鉴金融 MACD/RSI：快均线(5) vs 慢均线(15) → MACD线 = 快-慢，信号线 = EMA → 突破信号 = MACD - 信号。正差分比例 (RSI) 判断动量方向。合成信号调整预测速度。

---

### 80. 热搜趋势 (Hot Trend Detection)

**文件**: `models/event/hot_trend.py`

#### 原理
二阶导数 (加速度) 持续性检测 → 加速度持续为正(>60%) 判定为"热搜加速" → 二次外推。若加速度为负(<30%)，降为保守估计 (0.7×当前速度)。加急动度 (jerk, 三阶导数) 捕捉趋势拐点。

---

## 内容感知

新增类别 (2026-06)，基于内容质量与互动信号调整预测。

### 81. 互动衰减 (Engagement Decay)

**文件**: `models/content/engagement_decay.py`

#### 原理
计算互动率序列 (点赞/播放) → 指数衰减拟合 `eng = a * exp(-λt) + c` → 根据衰减率 λ 判定生命周期阶段:
- λ < -0.02: 成长期 (加速因子 1.3)
- -0.02 ≤ λ < 0.005: 成熟期 (1.0)
- 0.005 ≤ λ < 0.02: 缓慢衰减 (0.7)
- λ ≥ 0.02: 快速衰减 (0.4)

---

### 82. 病毒传播评分 (Virality Score)

**文件**: `models/content/virality_score.py`

#### 原理
四维度加权评分 (0-1):
1. 播放增速 (权重0.30)
2. 互动率 (权重0.35)
3. 分享率 (权重0.15)
4. 加速度 (权重0.20)
→ 综合病毒传播分 → 映射到加速因子 [0.5, 2.5]

---

### 83. 质量衰减 (Quality-Adjusted Decay)

**文件**: `models/content/quality_decay.py`

#### 原理
`quality_score` (弹幕密度+投币/点赞比+互动率) → 质量加权的指数时间衰减 `decay_rate = 1/age / (0.3+0.7*quality)`。高质量视频衰减更缓。60%质量衰减 + 40%近期趋势。

---

## 新增深度学习模型

### 84. NLinear (AAAI 2023)

**文件**: `models/deep_learning/nlinear.py`

#### 原理
极简线性预测: RevIN 可逆实例归一化 → 单层线性映射 (window→horizon)。论文证明在很多任务上打平甚至超越复杂 Transformer。TorchModel 含 RevIN 层。

---

### 85. N-HiTS (AAAI 2023)

**文件**: `models/deep_learning/nhits.py`

#### 原理
多尺度分层插值: 堆叠 N 个 block，每个输出 backcast + forecast。每层对输入做 MaxPool 下采样实现多尺度。残差连接 (每层预测相加，残差回传下层)。

---

### 86. TimeMixer (ICLR 2024)

**文件**: `models/deep_learning/time_mixer.py`

#### 原理
多尺度可分解混合: AvgPool 不同 kernel (1/2/4) 下采样 → 每个尺度独立 MLP Mixer → 跨尺度融合。排行榜第一梯队模型。

---

### 87. BiTCN

**文件**: `models/deep_learning/bitcn.py`

#### 原理
双向时序卷积: 前向 TCN (因果卷积) + 反向 TCN (翻转序列) → 双向特征拼接 → 预测头。前向捕获历史→当前，反向捕获远期依赖。含 RevIN 归一化。

---

### 88. WPMixer (AAAI 2025)

**文件**: `models/deep_learning/wpmixer.py`

#### 原理
小波包多分辨率混合: 原始分辨率 + 2x下采样 + 4x下采样 → 三个独立 MLP Mixer → 融合输出。2025年最新高效架构。

---

### 89. Koopa (NeurIPS 2023)

**文件**: `models/deep_learning/koopa.py`

#### 原理
Koopman 算子理论: 编码器映射到 Koopman 空间 → 线性算子 K 驱动演化 (多分量) → 解码器映射回预测。比 KNF 更先进。

---

### 90. SegRNN (arXiv 2023)

**文件**: `models/deep_learning/segrnn.py`

#### 原理
分段 RNN: 将长序列切分为多个等长 segment → 每个独立编码 → GRU 串联所有 segment → 输出预测。处理长序列效果优于单 GRU/LSTM。

---

### 91. FiLM (NeurIPS 2022)

**文件**: `models/deep_learning/film.py`

#### 原理
频率 Legendre 记忆: Legendre 多项式基底 (P0-P3) 对时间维做正交投影 → 频率混合层捕捉周期模式 → MLP 预测。FFT 频谱分析辅助。

---

### 92. FreTS (NeurIPS 2023)

**文件**: `models/deep_learning/frets.py`

#### 原理
频域 MLP: FFT 变换 → 在频域用 MLP 处理幅度 → iFFT 还原时域。自然捕捉周期性，对季节性强的时间序列效果好。

---

### 93. LightTS (arXiv 2022)

**文件**: `models/deep_learning/lightts.py`

#### 原理
轻量采样 MLP: 对输入做步长采样降维 → 轻量 MLP 预测。极低参数量，推理速度快。

---

### 94. Autoformer (NeurIPS 2021)

**文件**: `models/deep_learning/autoformer.py`

#### 原理
自相关 Transformer: FFT 计算序列自相关代替点积注意力 → 移动平均趋势分解 + 自相关季节性分解 → 渐进式分解架构。经典时序 Transformer。

---

### 95. FEDformer (ICML 2022)

**文件**: `models/deep_learning/fedformer.py`

#### 原理
频域增强 Transformer: FFT → TopK 频率分量 → 频域幅度/相位增强 (MLP) → 平均池化全局特征。频域建模自然抗噪。

---

### 96. Crossformer (ICLR 2023)

**文件**: `models/deep_learning/crossformer.py`

#### 原理
跨维依赖 Transformer: 序列分段 → 段间 MultiheadAttention 捕捉跨维依赖关系。适合多变量时序的交叉影响建模。

---

## 新增集成学习

### 97. Stacking 元学习器

**文件**: `models/ensemble/stacking_ensemble.py`

#### 原理
二级模型架构: Level 0 基模型 (Ridge + GBM) → 预测结果作为 Level 1 元学习器 (Ridge) 的输入特征 → 8:2 train/val split。7维特征工程 (线性/指数/MA/互动率/投币/加速度/CV)。

---

### 98. Blending 集成

**文件**: `models/ensemble/blending_ensemble.py`

#### 原理
区别于 Stacking 的 K-fold: 固定 8:2 holdout → 基模型在训练集学习，元学习器在 holdout 验证集学习 → 防过拟合。3个基模型 (Ridge+GBM+Ridge) → Ridge 元学习器。

---

### 99. 动态集成策略

**文件**: `models/ensemble/dynamic_ensemble.py`

#### 原理
根据数据量 N 自适应切换:
- N<20 (早期): 短期速度权重 0.5
- 20≤N<100 (成长): 中期趋势权重 0.35
- N≥100 (成熟): 长期衰减权重 0.35
阈值灵敏度: 1000万阈值增加长期权重，10万阈值增加短期权重。

---

### 100. 贝叶斯模型平均 (BMA)

**文件**: `models/ensemble/bayesian_averaging.py`

#### 原理
对 5 个基模型 (线性/二次/MA/指数/三次) 计算 BIC = n·log(MSE) + k·log(n)。后验概率 `w_i ∝ exp(-0.5·ΔBIC_i)` → softmax 加权预测。信息论最优模型选择。

---

### 101. 残差修正

**文件**: `models/ensemble/residual_correction.py`

#### 原理
GBM 学习历史「预测 vs 真实」残差: 输入特征 (速度/加速度/互动率/滚动统计/质量分) → 预测当前残差 → 对基础预测加修正量。消除系统性偏差。

---

### 102. 分位数集成

**文件**: `models/ensemble/quantile_ensemble.py`

#### 原理
5 分位数回归 (10%/25%/50%/75%/90%): GBM+Pinball Loss → Bootstrap 200次。50%为中点预测，25%-75%为置信区间，10%-90%为宽区间。输出预测不确定性量化。

---

## 新增统计与时序

### 103. 高斯过程回归

**文件**: `models/statistical/gaussian_process.py`

#### 原理
sklearn GaussianProcessRegressor (RBF+WhiteKernel) 优先 → numpy RBF 协方差矩阵回退。输出点预测 + 方差 (不确定度)。概率预测方法。

---

### 104. Theta方法

**文件**: `models/time_series/theta_method.py`

#### 原理
M3竞赛亚军。Theta=2: 对时序做二阶差分提取 Theta 线 → 线性外推趋势 → 季节调整 (半周期均值)。简洁但效果超越许多复杂模型。

---

### 105. Bass 扩散模型

**文件**: `models/growth/bass_diffusion.py`

#### 原理
`dN/dt = (p+q·N/M)·(M-N)`。最小二乘估计 p (创新系数) 和 q (模仿系数)。市场容量 M 估计为当前播放量的 5-10 倍。模拟 S 曲线达到阈值。

---

## 新增高级分析

### 106. 共形预测

**文件**: `models/advanced/conformal_prediction.py`

#### 原理
分布无关预测区间: 留一法校准集残差 → 分位数残差边界 → α=0.2 覆盖率保证。区间宽度反映模型不确定性。

---

### 107. 概率校准

**文件**: `models/advanced/prob_calibration.py`

#### 原理
Isotonic Regression 校准置信度: 交叉验证误差 → 学习「误差→置信度」单调映射。校准后置信度更准确反映真实误差分布。

---

### 108. 多步多频率融合

**文件**: `models/advanced/multi_step_fusion.py`

#### 原理
seq2seq 多步预测 (线性+二次组合) + 高/中/低频融合 (原始/每3点/每6点) + 加权共形预测 (自适应α)。综合多维信号提升准确度。

---

## 新增工具模块

### 数据清洗 (data_cleaner.py)
- `detect_view_reversal`: 播放量倒退检测
- `zscore_filter`: 滑动窗口 Z-score (阈值3.5)
- `savitzky_golay_smooth`: SG 滤波器去噪
- `interpolate_outliers`: 异常点线性插值修复
- `clean_history`: 完整清洗流水线

### 滚动窗口回测 (rollout_backtest.py)
- `RollingBacktester`: 滑动窗口时间序列交叉验证
- `backtest_multi_predictor`: 多预测器同台对比
- `select_top_k`: 自动选最优K个
- 工厂函数: `make_linear_fn`, `make_moving_avg_fn`, `make_exp_fn`, `make_theta_fn`

### RevIN 层 (_torch_upgrade.py)
可逆实例归一化: `RevIN(x, mode)` — `norm` 模式做归一化，`denorm` 模式还原。解决时序非平稳问题。

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

## PyTorch 训练管线

系统内置统一 PyTorch 训练基础设施，支持深度学习算法的全局预训练与视频级微调。

### 架构

```
algorithms/training/
├── trainer.py            # 统一训练编排器
├── dataset.py            # 时序数据集 (VideoTimeSeriesDataset)
├── checkpoint_manager.py # 多版本 Checkpoint 管理
├── hf_loader.py          # HuggingFace 模型加载器
└── device.py             # 设备管理 (CPU/CUDA)
```

### 核心功能

- **全局预训练**: 基于所有视频数据训练全局模型，支持增量训练（从已有 checkpoint 继续）和重新训练（随机初始化）
- **视频微调**: 基于全局 active checkpoint，对单个视频微调少量 epoch
- **多版本管理**: 每个算法保存多个 checkpoint 版本，支持版本激活/回滚
- **实时可视化**: 训练时通过 UI 面板展示 loss 曲线图 + 文本日志

### 算法集成约定

PyTorch 算法需实现以下方法供训练器调用：

| 方法 | 说明 | 默认值 |
|------|------|--------|
| `build_model()` | 返回 `nn.Module` 实例 | 必选 |
| `get_loss_fn()` | 返回损失函数 | `MSELoss` |
| `preprocess_batch(batch)` | 转换 (x, y) → (input, target) | 透传 |
| `get_optimizer(model)` | 返回优化器 | `Adam(lr=1e-3)` |
| `get_training_features()` | 训练使用的特征列表 | view/like/coin/favorite/share |

### 参与训练的算法

| 算法 | 状态 |
|------|------|
| MLP、神经网络、LSTM、GRU、BiLSTM、TCN、CNN-LSTM、CNN图像化 | ✅ 已集成 |
| N-BEATS、TimesNet、DLinear、Informer、TFT、PatchTST、注意力机制 | ✅ 已集成 |
| Diffusion TS、KNF、Mar-BiLSTM | ✅ 已集成 |
| TIDE、TSMixer、DeepAR、Chronos、Mamba S6、iTransformer、SCINet、TimesFM、Time-MoE | ✅ 已集成 |
| Lag-Llama、MOIRAI | ⚡ HF 零样本（无需训练） |

### 如何通过 Loss 值判断模型好坏

Loss（损失值）是训练过程中衡量模型预测误差的核心指标，但**loss 低 ≠ 模型好**，需要结合多维度信息综合判断。

#### 1. 训练 Loss vs 验证 Loss — 过拟合诊断

两条曲线的关系是最重要的判断依据：

| 模式 | train loss | val loss | 诊断 |
|------|-----------|---------|------|
| ✅ 正常训练 | ↓ 持续下降 | ↓ 同步下降 | 模型在学习有效模式 |
| ⚠️ 欠拟合 | ↓ 缓慢或不降 | ↓ 缓慢或不降 | 模型容量不足 / 学习率太低 / epoch 不够 |
| 🔴 过拟合 | ↓ 持续下降 | ↓ 到某点后**回升** | 模型死记训练数据，泛化变差 |
| 🟡 随机震荡 | ↕ 来回跳动 | ↕ 来回跳动 | 学习率太高 / batch size 太小 / 数据噪声大 |

**经验法则**：当 val loss 连续 3-5 个 epoch 不再下降或开始回升时，应停止训练（early stopping）。继续训练只会过拟合。

#### 2. Loss 的绝对数值 — 看场景不看大小

不同算法的 loss 量级不同，不能跨算法比较：

| 算法 | loss 类型 | 典型范围 | 说明 |
|------|----------|---------|------|
| MSELoss（速度预测） | 均方误差 | 0.01 ~ 1.0 | 取决于速度的归一化尺度 |
| Diffusion TS | 噪声 MSE | 0.01 ~ 0.5 | 预测的 ε 是标准正态，loss 接近 0 表示完美去噪 |
| MAE / L1Loss | 平均绝对误差 | 0.1 ~ 2.0 | 与速度同量纲，更直观 |

**重点**：不要追求 loss = 0（那一定是过拟合）。合理的 loss 表明模型学到了数据中的主要模式而非噪声。

#### 3. 训练 Loss 曲线的理想形态

```
Loss
│
│   ╲
│    ╲
│     ╲
│      ╲____
│       ╲___
│        ╲______ (平稳)
└──────────────────→ Epoch
```

理想曲线特征：
- **快速下降期**：前 5-10 个 epoch loss 快速下降 → 模型在捕捉主要趋势
- **缓慢收敛期**：后段下降变缓，逐渐趋于平稳 → 模型在微调细节
- **无剧烈震荡**：曲线平滑，不出现大幅尖峰

#### 4. 异常曲线排查

```
Loss 急跌后横盘         Loss 震荡不降          Loss 先降后升
│                       │                      │
│ ╲                     │    ╱╲╱╲               │ ╲
│  ╲____                │  ╱  ╱ ╲╱             │  ╲____
│  ╰──── (太低了)       │ ╱                   │       ╲____↗
└──────→                └──────→               └──────────→
```

| 异常形态 | 可能原因 | 解决办法 |
|---------|---------|---------|
| 急跌后横盘（loss 极小） | 模型退化为常数预测（永远输出均值） | 检查数据归一化，增大模型容量 |
| 全程震荡不降 | 学习率过高 / 数据信噪比太低 | 调低 lr，增加 batch size，检查数据 |
| 先降后升（val loss） | 过拟合 | 减少 epoch，增加 dropout，减小模型 |
| loss = NaN | 梯度爆炸 / 除零 | 检查是否有 log(0)，添加 gradient clipping |

#### 5. 本系统中的实际参考值

根据当前各算法的实测训练情况（全局预训练 50 epoch）：

| 算法 | val loss 典型范围 | 说明 |
|------|-----------------|------|
| LSTM / GRU / BiLSTM | 0.05 ~ 0.30 | 速度归一化到 [0,1] 时的 MSE |
| TCN / CNN-LSTM | 0.04 ~ 0.25 | 卷积结构通常略优于纯 RNN |
| MLP / 神经网络 | 0.10 ~ 0.40 | 简单结构，受数据量影响大 |
| N-BEATS / TimesNet | 0.03 ~ 0.20 | 结构复杂，拟合能力强，注意过拟合 |
| Transformer 系列 | 0.03 ~ 0.25 | 参数量大，需要更多数据 |
| Diffusion TS | 0.05 ~ 0.20 | DDPM 噪声预测损失，与数据尺度解耦 |
| KNF / Mar-BiLSTM | 0.04 ~ 0.30 | 依赖全局 checkpoint 质量 |

> **注意事项**：以上数值为参考范围，实际值受训练数据量、归一化方式、随机种子等因素影响。同一算法在不同视频上的 loss 也可能差异很大（高播放量视频数据多、模式清晰，loss 通常更低）。

#### 6. 实用建议

1. **训练时盯着 val loss，别只看 train loss** — train loss 再低也可能是过拟合
2. **关注 loss 下降趋势而非绝对值** — 连续 5 epoch val loss 不再下降就可以停了
3. **结合预测结果看** — 有时 loss 略高但预测趋势正确，比 loss 低但预测恒定的模型更有用
4. **Diffusion TS 注意** — 它的 loss 是噪声预测误差，不是速度预测误差，需要额外看采样结果
5. **多试几次** — 随机初始化 + 数据划分会导致 loss 波动，同一配置跑 3 次取中位数更可靠

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
18. ~~CNN图像化/Diffusion TS/KNF/Mar-BiLSTM 深度学习~~ 已实现
19. ~~Lag-Llama/MOIRAI 大模型零样本预测~~ 已实现
20. ~~PyTorch 训练管线（全局预训练 + 视频微调）~~ 已实现
21. **迁移学习**: 利用相似视频的历史数据
22. **元学习 (Meta-Learning)**: 快速适应新UP主/新视频类型
23. **多模态融合**: 结合视频标题、封面、描述等文本/图像特征

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
22. Traditional, J., et al. (2024). Lag-Llama: Towards Foundation Models for Probabilistic Time Series Forecasting.
23. Ansari, A. F., et al. (2024). MOIRAI: A Large-Scale Time Series Foundation Model.
24. Ho, J., et al. (2020). Denoising Diffusion Probabilistic Models. (DDPM, Diffusion TS)
25. Azencot, O., et al. (2023). Koopman Neural Forecaster (ICLR 2023, KNF)
26. Salinas, D., et al. (2020). DeepAR: Probabilistic Forecasting with Autoregressive Recurrent Networks.
27. Ansari, A. F., et al. (2024). Chronos: Learning the Language of Time Series.
28. Gu, A., & Dao, T. (2024). Mamba: Linear-Time Sequence Modeling with Selective State Spaces.
29. Liu, Y., et al. (2024). iTransformer: Inverted Transformers Are Effective for Time Series Forecasting.
30. Liu, M., et al. (2022). SCINet: Time Series Modeling and Forecasting with Sample Convolution and Interaction.
31. Das, A., et al. (2024). A decoder-only foundation model for time-series forecasting. (TimesFM)
32. Shi, X., et al. (2025). Time-MoE: Billion-Scale Time Series Foundation Models with Mixture of Experts.
33. Duan, T., et al. (2020). NGBoost: Natural Gradient Boosting for Probabilistic Prediction.
34. Arik, S. O., & Pfister, T. (2021). TabNet: Attentive Interpretable Tabular Learning.
35. Brodersen, K. H., et al. (2015). Inferring causal impact using Bayesian structural time-series models.
36. De Livera, A. M., et al. (2011). Forecasting time series with complex seasonal patterns using exponential smoothing. (TBATS)
37. Bandara, K., et al. (2021). MSTL: A Seasonal-Trend Decomposition Algorithm for Time Series with Multiple Seasonal Patterns.
38. Bollerslev, T. (1986). Generalized autoregressive conditional heteroskedasticity. (GARCH)
39. Chen, S.-A., et al. (2023). TSMixer: An All-MLP Architecture for Time Series Forecasting.
40. Zeng, A., et al. (2023). Are Transformers Effective for Time Series Forecasting? (DLinear, AAAI 2023)
41. Challu, C., et al. (2023). N-HiTS: Neural Hierarchical Interpolation for Time Series Forecasting. (AAAI 2023)
42. Wu, H., et al. (2024). TimeMixer: Decomposable Multiscale Mixing for Time Series Forecasting. (ICLR 2024)
43. Liu, M., et al. (2023). Koopa: Learning Non-stationary Time Series Dynamics with Koopman Predictors. (NeurIPS 2023)
44. Yi, K., et al. (2024). FreTS: Frequency-domain MLPs are More Effective Learners. (NeurIPS 2023)
45. Zhou, T., et al. (2023). FiLM: Frequency improved Legendre Memory Model. (NeurIPS 2022)
46. Zhou, H., et al. (2021). Autoformer: Decomposition Transformers with Auto-Correlation. (NeurIPS 2021)
47. Zhou, T., et al. (2022). FEDformer: Frequency Enhanced Decomposed Transformer. (ICML 2022)
48. Zhang, Y., et al. (2023). Crossformer: Transformer Utilizing Cross-Dimension Dependency. (ICLR 2023)
49. Wu, H., et al. (2025). WPMixer: Efficient Multi-Resolution Mixing. (AAAI 2025)
50. Lin, J., et al. (2023). SegRNN: Segment Recurrent Neural Network. (arXiv 2023)
51. Zeng, A., et al. (2023). NLinear: Normalization-Linear Model. (AAAI 2023)
52. Kim, T., et al. (2022). Reversible Instance Normalization (RevIN). (ICLR 2022)
53. Assimakopoulos, V., et al. (2000). The theta model: a decomposition approach to forecasting.
54. Bass, F. M. (1969). A New Product Growth Model for Consumer Durables.
55. Vovk, V., et al. (2005). Algorithmic Learning in a Random World. (Conformal Prediction)
56. Hoeting, J. A., et al. (1999). Bayesian Model Averaging: A Tutorial.

---

*文档版本: 8.0*
*最后更新: 2026-06-02*
*算法总数: 103*
