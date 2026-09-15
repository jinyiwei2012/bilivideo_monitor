# 分析能力增强实现方案（HDS·VDR·运营告警·IQR·AHP）

> 本文是**待实现规格**：每条都给出「落到哪个文件/函数 → 怎么改 → 验收 → 对本项目的收益」，
> 来源为同类开源项目（均为 MIT 或仅借鉴做法，见文末许可说明）。
> 与 [docs/bilibili_api_contract.md](bilibili_api_contract.md) 配套：那份管**接口契约**，这份管**指标与告警**。

## 0. 决策记录

- **不做「数据留存/清理提醒」** —— 本项目的既定目标是**全量保留**历史数据，
  因此不引入 bili_monitor 的「>180 天 / DB >30MB 提示清理」机制。后续请勿再提此需求。
- **新增算法是安全的**：仓内**没有**任何测试断言算法总数（`tests/test_algorithm_schedule.py` 与
  `test_refactor_regressions.py` 中的 "137" 均为注释说明）。新增算法只需同步 README/CHANGELOG 中的数量描述。
- **先对照既有实现，避免重复造**：`algorithms/models/advanced/` 已有
  `engagement_rate.py`、`quality_score.py`、`like_momentum.py`、`share_velocity.py`、
  `conformal_prediction.py`、`prob_calibration.py`、`lifecycle_modeling.py`
  → 第 1、6、7 条**必须先读这些文件再决定是"扩展"还是"新增"**。

---

## 1. HDS 互动深度 + VDR 观看留存率（派生指标）

**收益**
- HDS 把"点赞/投币/收藏/弹幕/评论/分享"按权重折算成**单一互动深度分**，可跨视频比较，
  比现有单一"互动率"更能反映内容质量 → 直接增强 `ui/prediction_panel.py` 的健康度展示与
  `algorithms/models/advanced/engagement_rate.py`（先比对，避免重复）。
- VDR 用**已采集的在线人数**估算"单次观看时长/留存" → 这是目前完全缺失的维度，
  对"视频是否被完整观看"（决定推荐权重）最有解释力，可作为 ETA 的新特征。

**实现方案**

新增 `utils/derived_metrics.py`（纯函数、无副作用、可单测）：

```python
DEFAULT_WEIGHTS: dict[str, float] = {          # 来源：bili_monitor DEFAULT_WEIGHTS
    "coin": 0.4, "favorite": 0.3, "danmaku": 0.4, "reply": 0.4,
    "like": 0.4, "share": 0.6, "view": 0.25,
}
HDS_METRICS = ("like", "coin", "favorite", "danmaku", "reply", "share")  # 排除 view：避免自指

def hds_series(buckets: list[dict], weights: dict[str, float] | None = None) -> list[float]:
    """逐桶 HDS = Σ(w_i · max(Δmetric_i, 0)) / max(Δviews, 1)；Δviews<=0 的桶跳过。"""

def vdr_series(records: list[dict], duration: int) -> list[tuple[str, float, float, float]]:
    """累积 Δt 到 >= duration 时输出一条 (ts, vdr_mid, vdr_upper, vdr_lower)，上限 5.0。
    common   = acc_views * duration / acc_dt
    base_avg = (online_start + online_end) / 2
    mid/upper/lower = common / (base_avg + 500 | base_avg | base_avg + 999)
    要求 duration>0 且有效间隔 >= 3 条，否则返回 []（调用方显示"数据不足"）。"""
```

**参数与边界（照搬上游的保守设定）**：HDS 平滑窗口 2；VDR 平滑窗口 3；
`Δviews <= 0` 的桶直接跳过；VDR 三档分别对应"在线数估计偏乐观/中性/偏悲观"。

**接入点**
1. `ui/detail_panel.py`：比率页新增「互动深度 HDS」「观看留存 VDR」两项（沿用现有增量更新模式，勿重建控件树）。
2. `algorithms/training/dataset.py`：作为**可选特征**加入（先做离线回测对比，再决定是否进模型）。
3. `algorithms/models/advanced/engagement_rate.py`：若已有同类计算，改为调用 `utils/derived_metrics.hds_series`，保持单点实现。

**验收**：`tests/test_derived_metrics.py` —— ① 构造 2 桶已知数据，断言 HDS 数值精确；
② `Δviews=0` 桶被跳过；③ VDR 在 `duration=0` 或有效间隔 <3 时返回空；
④ 在线人数缺失（0）的间隔被跳过。

---

## 2. 数据清洗细化（哨兵值 / 累计回退 / 暴跌 / 脏首点）

**收益**：B站 API 在**冻结**与**补量**时会出现"值不动"或"值回退"，
现有 `algorithms/data_cleaner.py` 只有 `detect_view_reversal` + `zscore_filter` + SG 平滑 +
`interpolate_outliers`，对四类伪影覆盖不全 → 清洗不准会直接污染速率估计与预测。
（项目已用 MAD 剪除处理部分场景，本项是**补齐 + 更早发现**。）

**实现方案**：扩展 `algorithms/data_cleaner.py`

| 新增/扩展 | 规则（来源：bili_monitor `viz/plots.py:184-254`） |
|---|---|
| `detect_sentinel(records) -> np.ndarray` | 任一被采字段 == `-1` → 该行标记 stale（B站冻结哨兵值） |
| `detect_cumulative_rollback(records) -> np.ndarray` | **任一累计字段比上一条变小** → 标记 stale（现仅 views 有类似检查） |
| `detect_sharp_drop(views, ratio=0.9) -> np.ndarray` | `views < 前值 × 0.9` → 标记（API 抖动） |
| `drop_dirty_first_point(records)` | 首条记录**所有**累计字段 ≤1 → 丢弃（发布瞬间的脏点） |
| `clean_history(..., filter_stale=True)` | 汇总上述标记，并在速率/增量计算前剔除（保持现有签名向后兼容） |

**注意**：标记与剔除**分离**（先打 `_stale` 标记，由调用方决定"剔除/插值/仅标色"），
以免破坏现有调用方行为；返回值保持原类型（`List[Tuple]`），新增标记走附加字段或并列返回。

**验收**：`tests/test_data_cleaner_artifacts.py` —— ① 含 `-1` 的行被识别；② 累计值回退被识别；
③ 暴跌 9% 被识别、跌 11% 不触发（边界）；④ 脏首点被丢弃；⑤ 无伪影数据**零改动**（回归保护）。

---

## 3. 采集 `his_rank` / `now_rank`（历史最高排名）

**收益**：排名是**独立于播放量的曝光信号**（曾是"全站排行"，对早期爆发最敏感），
可用于：① 新的异常检测维度；② 预测特征；③ 详情页"最高排名"展示。
数据来自现有接口 `x/web-interface/view` → `data.stat.his_rank` / `data.stat.now_rank`（零额外请求）。

**实现方案（关键：三处写入点必须同步）**

1. **库表**：`core/database/video_db.py` 的 `SCHEMA_STATEMENTS` 中 `monitor_records` 增加
   `his_rank INTEGER DEFAULT 0, now_rank INTEGER DEFAULT 0`；中央库 schema 同步。
2. **迁移**：照 `core/database/video_db_danmaku.py::_migrate_danmaku_v3` 的写法加
   `ALTER TABLE monitor_records ADD COLUMN ...`（幂等、失败仅 debug）。
3. **三处 INSERT 列清单同步**（缺一处即静默丢数据）：
   - `core/database/video_db.py:545`（每视频库）
   - `core/database/central_crud.py:309`（中央库）
   - `core/database/central_backup.py:221`（镜像/备份）
4. **采集**：`core/bilibili_video.py::get_video_info` 已有 `stat` 字典 → 在监控写入处取
   `stat.get("his_rank", 0)` / `stat.get("now_rank", 0)`（监控服务见 `ui/monitor/_service.py`）。
5. **展示**：`ui/detail_panel.py` 统计条 + 图表指标项（见第 4 条的指标列表）。

**验收**：`tests/test_his_rank_roundtrip.py` —— ① 写入后三处（视频库/中央库/镜像）均可读回；
② 老库（无列）自动迁移成功；③ `stat` 缺字段时不报错、写 0。

---

## 4. 图表断线分段（`max_gap = 2h`）

**收益**：监控中断（关软件/断网）后，若把断点前后两点直连，会画出**虚假的斜率**，
直接误导用户对速率的判断（也会让"增量"看起来异常）。分段后曲线在断点处断开，语义正确。

**实现方案**
- 在 `ui/chart.py` 生成折线序列处增加分段：`gap_segments(timestamps, max_gap_seconds=7200)`，
  对每个分段独立绘制（现有 painter 已支持多段绘制路径，复用同一 `QPainterPath` 逐段 `moveTo`）。
- 断点处可选画一个空心标记 + tooltip"数据中断 ≥2h"。
- 同时为**增量/速率**计算加上"跨断点不计入"的守卫（避免把 6 小时中断当成 1 个间隔算速率）。

**注意**：`ui/detail_panel.py` 中的指标列表（图表可选指标）本轮**需先确认现有枚举位置**再扩展
（本项只改绘制与速率守卫，改动面小、可先做）。

**验收**：`tests/test_chart_gap_segments.py` —— 纯函数级：① 间隔 1h 不分段；② 间隔 3h 分段；
③ 边界 2h 整不触发；④ 跨断点的速率计算被跳过。

---

## 5. 三条运营告警（补齐 `smart_alert`）

**收益**：现有 `core/smart_alert.py::AnomalyDetector` 的 8 个检测器偏"统计异常"，
缺少**带业务阈值的运营规则**。这三条能直接回答运营问题：「这条视频要不要加推？」「是不是哑火了？」。

**实现方案**：在 `AnomalyDetector` 中新增（复用现有的 `AlertHit`、`_recent_window(records, hours)`、
`_should_alert`/`_record_hit` 去重、`_sorted_records`）

| 检测器 | 触发条件（来源：biliradar `cmd_alerts`） | 建议文案 |
|---|---|---|
| `detect_slow_start_scored` | `3 < age_h < 8` 且 `views < 500` | ⚠️ 起步慢：发布 {age_h:.1f}h 播放仅 {v} |
| `detect_hot_vs_baseline_scored` | `inc_1h > avg_inc_hourly_24h × 5` 且 `inc_1h > 200`，其中 `inc_1h = views_now − views(≈1h前)`、`avg_inc_hourly_24h = (views_now − views(≈24h前)) / 24` | 🔥 播放暴涨：近 1h +{inc}（前 24h 均 {avg:.0f}/h），疑似进入推荐流 |
| `detect_high_three_rate_scored` | `views > 1000` 且 `(like+coin+favorite) / (views × 3) > 0.15` | ✨ 优质：三连率 {x:.1f}% |

**两个必须照搬的实现细节**
1. **快照容错取数**：取"**≤ 目标时刻的最近一条**"而非要求时间戳精确对齐 —— 监控间隔不齐时这是唯一可靠做法。
2. **相对基线而非绝对阈值**：HOT 规则以"自身 24h 均速 ×5"为基准，天然适配大小 UP 主。

**验收**：`tests/test_smart_alert_ops.py` —— 每条规则的**触发/不触发**成对用例 + 边界值
（`inc_1h == 200` 不触发、`>200` 触发；三连率 `0.15` 不触发、`0.151` 触发）+ 去重（同 key 短时间只报一次）。

---

## 6. IQR 分位区间 + 样本量分级置信度

**收益**：预测面板目前的区间来自 `algorithms/conformal.py`（log 域保形）。
IQR 方案的价值不在区间本身，而在**「样本不足时明确降级并标注置信度」**：

| scope 样本量 | 置信 | 做法 |
|---|---|---|
| `< 5` | low | 不输出主估计（`primary=None`），用**全站/全局 fallback** |
| `5–29` | low | 用 global fallback |
| `30–99` | **mid** | 用 scope 样本 |
| `≥ 100` | **high** | 用 scope 样本 |

这正是本项目冷启动期最需要的诚实表达（避免用 3 个点就给出"高置信"的 ETA）。

**实现方案**
- 新增 `utils/stat_intervals.py`：`percentile(sorted_samples, p)`（**线性插值**，与上游一致）、
  `median/quartiles/iqr`、`confidence_for(n)`、`bucketize(values, edges)`。
- 与既有实现的关系：`conformal.py` 继续负责**分布无关区间**；
  `utils/stat_intervals.py` 负责**分位/置信分级**；两者在 `ui/prediction_panel.py` 并列展示（区间 + 置信徽标）。
- 先比对 `algorithms/models/advanced/prob_calibration.py` 与 `conformal_prediction.py`，
  若已有分位逻辑则扩展而非新建。
- 上游明确"数据不足不上 ML"的理由值得写入注释：**30 天数据尚未累积，硬上 regression 会 overfit**。

**验收**：`tests/test_stat_intervals.py` —— 移植上游测试向量：
`percentile([], 0.5)==0`、`percentile([42],0.25)==42`、`percentile([1,2,3,4],0.25)==1.75`、
`percentile([1,2,3],-0.5)==1`、`percentile([1,2,3],1.5)==3`；`confidence_for(29)=='low'`、
`confidence_for(30)=='mid'`、`confidence_for(100)=='high'`。

---

## 7. AHP 传播力评分（+ 一致性检验）

**收益**：把"播放/互动"多维指标合成**单一可解释评分**（含权重来源与一致性检验 CR），
用于：① 与 `quality_score.py` 交叉验证；② 周报/复盘卡的"传播力"维度；③ 训练特征（需回测验证）。

**实现方案**：新增算法 `algorithms/models/advanced/ahp_quality.py`（继承 `BaseAlgorithm`，
`category = "高级分析"`，随 `AlgorithmRegistry` 自动注册；**无需手动登记**）

**RI 表**（n=1..10）：`{1:0, 2:0, 3:0.58, 4:0.90, 5:1.12, 6:1.24, 7:1.32, 8:1.41, 9:1.45, 10:1.49}`

**三层指标（12 项，公式直接复用）**
| 准则 | 指标 |
|---|---|
| 传播广度 | `daily_views = V/A`（A=存续天数）、`share_rate = S/V` |
| 互动深度 | `reply_rate = R/V`、`danmaku_density = D/T`（T=时长秒）、`composite_interaction_rate = (R+D)/V` |
| 传播认同 | `like_rate`、`coin_rate`、`favorite_rate`、`recognition_rate = (C+F+S)/V` |
| 知识传播效果 | `cognitive_feedback_ratio = N_cf/N_all`、`question_comment_ratio = N_q/N_all`、`sentiment_polarization = (N_pos+N_neg)/N_all`（评论/弹幕情感分析结果可复用现有 LLM 管线） |

**准则判断矩阵**：`[[1,1/2,1/3,1/4],[2,1,1/2,1/3],[3,2,1,1/2],[4,3,2,1]]`（广度<深度<认同<知识效果）

**算法**
```python
eigvals, eigvecs = np.linalg.eig(matrix)
weights = np.abs(eigvecs[:, int(np.argmax(eigvals.real))].real); weights /= weights.sum()
CI = (lambda_max - n) / (n - 1);  CR = CI / RI_TABLE[n]        # n<=2 时 CI=CR=0
normalized = min_max_per_column(data)                          # range≈0 → 0
score = normalized @ global_weight_vector * 100
```
**注意**：上游文件名虽是 `ahp_entropy`（AHP+熵权），但代码里 `final_weight_vector = ahp_weight_vector`
—— **熵权法实际未参与**。若要真做熵权（见第 8 条），需自行补齐。

**验收**：`tests/test_ahp_quality.py` —— ① 用上游矩阵断言 `CR < 0.1`（一致性通过）；
② 权重和为 1；③ 单指标极端值时评分单调；④ 缺失评论情感字段时该项记 0 且不抛错。

---

## 8. 毕设类启示：可补的三个方法 + 两类特征

**收益**：本项目的 137 算法在模型侧已远超同类毕设（RF/GBDT/XGB/LGBM/ARIMA/LSTM 等均有），
但下列三类**方法**与两类**特征**是它们独有或更强调的，可作为"覆盖面补全"：

| 方法 | 作用 | 落地 | 依据 |
|---|---|---|---|
| **灰色关联度 GRA** | 小样本下量化"各指标与热度的关联度"，用于特征筛选/权重 | 新增 `algorithms/models/advanced/grey_relation.py`；或先做 `scripts/characterize_algorithms.py` 的分析工具 | 排行榜"综合得分"逆向分析（GRA + PCA） |
| **熵权法** | 客观赋权（与 AHP 主观赋权互补） | 并入第 7 条：`ahp_quality.py` 增加 `entropy_weights()`，与 AHP 权重线性组合（可配 λ） | `ahp_entropy` 的命名与实际缺口 |
| **KMeans 参与度分群** | 把视频分成"低互动普通/高点赞活跃/高评论讨论/高弹幕娱乐"四类，用于对比与告警基线 | 新增 `algorithms/models/advanced/engagement_cluster.py`（特征 = `like_rate/comment_rate/danmaku_rate`，`k=4, seed=42`） | Spark 毕设的聚类模块 |
| **发布时间（小时级）特征** | 毕设实测"发布时间对热门预测显著" | `algorithms/training/dataset.py` 增加周期性编码（`sin/cos(2π·hour/24)`、星期 one-hot） | Spark 毕设结论 |
| **分区（tname）/时长桶特征** | 不同分区的互动基准差异极大 | 同上（分区 one-hot 或目标编码；时长按上游 7 档分桶） | BiliBili-Analyzer `DURATION_BUCKETS` |

**注意**：新增特征会改变输入维度 → 需**重训/平移**已有模型（`algorithms/training/` 的
checkpoint 与 `A+B 双尺度` 目标不受影响，但输入层形状变了），应走一次完整回测
（`algorithms/rollout_backtest.py`）对比再决定是否启用，同时保留"关掉新特征"的开关。

---

## 9. 落地顺序与工作量

| 序 | 项 | 改动面 | 风险 | 预估 |
|---|---|---|---|---|
| 1 | 数据清洗细化（第 2 条） | `algorithms/data_cleaner.py` + 测试 | 低（纯函数、可回归保护） | 小 |
| 2 | 图表断线分段（第 4 条） | `ui/chart.py` + 速率守卫 | 低 | 小 |
| 3 | 三条运营告警（第 5 条） | `core/smart_alert.py` + 测试 | 低（复用既有骨架） | 小 |
| 4 | IQR + 置信分级（第 6 条） | 新 `utils/stat_intervals.py` + 面板展示 | 低（纯函数、测试向量现成） | 小 |
| 5 | `his_rank`/`now_rank`（第 3 条） | 3 处 INSERT + schema + 迁移 + 中央库 | **中**（漏一处静默丢数据） | 中 |
| 6 | HDS + VDR（第 1 条） | 新 `utils/derived_metrics.py` + 面板 | 中（需先比对 `engagement_rate.py`） | 中 |
| 7 | AHP 传播力评分（第 7 条） | 新算法 + 测试 | 中（新增算法需同步文档数量） | 中 |
| 8 | GRA / 熵权 / KMeans / 新特征（第 8 条） | 新算法 + `dataset.py` + 回测 | **高**（改输入维度需重训） | 大 |

**统一验收（每项都要过）**：`black --line-length=120`、`python scripts/lint_gate.py`、
`python scripts/type_gate.py`、`python -m pytest tests/ -q`；
若改动了 `core/bilibili_*.py` 等签名清单内文件，还需
`python scripts/update_hashes.py --hashes-only` 并确认 `python main.py` 启动无完整性报错。

## 10. 来源与许可

| 来源 | 许可 | 本文使用方式 |
|---|---|---|
| `ID-izlq-Github/bili_monitor` | MIT | HDS/VDR 公式、清洗规则、断线阈值、留存参数（仅借鉴，未采用其清理机制） |
| `lepockyio-ops/biliradar` | MIT | 三条告警规则与阈值、快照容错取数 |
| `BlackishGreen33/BiliBili-Analyzer` | MIT | IQR 分位实现、样本量分级置信、时长分桶 |
| `Michaelwu0905/fastapi-video-analyses` | 未声明（Apache 风格） | AHP 指标公式、RI 表、判断矩阵（**仅借鉴做法，不复制代码**） |
| 各类毕设/博客 | 不明 | 方法清单（GRA/熵权/KMeans/特征）**仅作方向参考** |

> 本项目为 MIT 且分发可执行文件：**所有 GPL/AGPL 来源只能借鉴"事实与思路"，不得复制代码**。
