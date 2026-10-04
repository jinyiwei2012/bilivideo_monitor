# 精确过线时刻（Precision Crossing）

把「越过阈值（如 10,000,000 播放量）的时刻」从「检测到的时刻」收窄为亚秒级的模型估计，
持久化到每视频库，并附加到达标通知里。

## 背景

B 站播放量以阶梯方式刷新（实测刷新周期约 75 秒，且会缓慢漂移、偶发「换挡」）。
阶梯之间的累积不可直接观测，因此：

- 「显示追上」只给出一个观测窗口（旧值最后一帧 → 新值第一帧）；
- 「真实越线」需要在该窗口与相邻阶梯之间插值估计。

## 机制（四步）

1. **高频采样**：目标接近时提速——剩余 ≤ `near_remaining` 用 5 秒步长，≤ `close_remaining` 用 1 秒步长；
2. **阶梯检测**：相邻采样值变化即一次刷新，区间 `(上帧时刻, 本帧时刻]`；
3. **插值**：在包围目标的两级阶梯值之间取比例 `f = (target - v_before) / (v_after - v_before)`，得到越线区间与中心估计；
4. **网格收束（可选）**：以 `T_k = T0 + k·P` 联立多级阶梯区间，解析求周期可行域并投影收窄阶梯时刻后重算越线区间；
   刷新节奏换挡时该步自动拒绝，退回插值。

## 组件

| 组件 | 位置 | 说明 |
|---|---|---|
| 纯计算 | `core/crossing_precision.py` | 无 I/O；`StepBracket` / `estimate_crossing` / `fit_rigid_grid` / `refine_crossing` |
| 观测服务 | `ui/monitor/_precision_watch.py` | 线程化、有界；依赖全部可注入（可离线测试） |
| 存储 | `crossing_events` 表（每视频库） | 阈值唯一，重复触发保持首条 |
| 通知 | `core/threshold_escalation._precise_crossing_line` | 达标通知附加「精确过线区间」一行 |
| 接线 | `ui/monitor/_service.py` | 集中拉取启动时创建；每次拉取后对最近未达标阈值 offer |

## 配置（`data/settings.json` → `precision_watch`）

```json
{
  "enabled": true,
  "near_remaining": 10000,
  "close_remaining": 1000,
  "interval_near_s": 5,
  "interval_close_s": 1,
  "max_duration_s": 5400,
  "max_requests": 4000,
  "max_active": 3,
  "stop_margin_s": 180
}
```

高频窗口只在阈值邻近时开启，且受时长（90 分钟）、请求数（4000）与并发（3 个视频）三重上限约束；
出错自动退避，不影响常规 75 秒主循环。

## 结果字段

- `display_window_start/end`：显示追及的观测窗口；
- `range_start/end` + `estimate`：插值越线区间与中心估计；
- `period_lo/hi` + `refined_start/end`：周期可行域与网格收束后的区间（可能为空）；
- `rtt_median_us`：高频窗口内请求 RTT 的中位数；
- `corrected_range_start/end` + `corrected_estimate`：按半 RTT 修正后的插值区间与中心估计。

## 观测时间与网络延迟

常规监控和高频观测都在请求前记录墙钟 `t0` 与单调钟，在响应返回后立即记录接收时刻 `t1`
及 `rtt = monotonic1 - monotonic0`。`monitor_records` 保存 `request_start_us`、`observed_at_us` 和
`rtt_us`，其中播放量归属于响应接收边界 `observed_at_us`，不会再被后续在线人数请求推迟。

高频观测另采用对称网络延迟近似 `t_server ≈ t_receive - rtt / 2`，对每个阶梯边界分别校正后重算
`corrected_*`。该修正仍受上下行不对称、服务端排队、缓存刷新延迟和 NTP 校准误差影响，因此原始区间、
修正区间及 RTT 中位数会同时保留；区间宽度仍是主要不确定性表达，而不是实测保证。

## 局限

- 插值依赖「阶梯间平滑累积」假设，是估计而非实测；
- 刷新节奏可能换挡，跨换挡的网格拟合会失败并退回插值；
- 观测墙钟使用 NTP 校准时间，超时与 RTT 使用单调钟；网络不对称和服务端处理时间仍无法从客户端观测中分离。
