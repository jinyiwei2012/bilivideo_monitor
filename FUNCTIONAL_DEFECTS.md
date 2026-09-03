# 功能性缺陷清单（审查报告 + 修复追踪）

> 生成时间：由代码审查（5 路并行子代理 + 人工复核）产出。
> 每项均经代码证据或运行测试验证，误报已剔除。
> 严重度：🔴 高（必然/高频触发、功能全坏）｜🟠 中（静默失败、数据错误）｜🟡 低（边缘场景、体验问题）

---

## 🔴 高严重度

### D1. float32 存储 unix 时间戳导致速度特征系统性失真
- **位置**: `algorithms/registry.py:237-239`、`algorithms/base.py:195`
- **现象**: unix 秒时间戳 ~1.78e9 存入 `np.float32`（ulp=128 秒 > 75 秒采样间隔），相邻采样点大量被舍入成相同值。实测 9 个点中 3 个相邻差为 0 → `np.polyfit` 斜率失真，`velocity_polyfit` 作为预计算速度注入全部 120+ 算法，系统性污染预测。
- **修复**: 时间戳数组改用 `np.float64`（两处）。

### D2. `_LRUDict` 缓存写满即抛 KeyError → 预测管线中断
- **位置**: `algorithms/registry.py:35-38`（`_derived_cache`、`_surge_cache`）
- **现象**: `__setitem__` 触发淘汰时 `popitem(last=False)` 内部调用子类 `__getitem__` → `move_to_end` 对已删键抛 KeyError。实测第 maxsize+1 次写入必崩。约 200 轮预测后 `predict_all` 异常，预测/推流检测静默失效。
- **修复**: 淘汰改为 `next(iter(self))` + `del self[key]`，绕开 `popitem` 的 `__getitem__` 调用链。

### D3. 退出流程第一行崩溃：`log_panel.cleanup()` 不存在
- **位置**: `ui/main_gui_events.py:282` + `ui/log_panel.py`
- **现象**: `on_exit` 调用不存在的 `LogPanel.cleanup()` → AttributeError → `QApplication.quit()` 永不执行，线程池/数据库/监控线程全部不清理，进程关不掉。
- **修复**: 为 `LogPanel` 补 `cleanup()`（停自动刷新 + 冲刷日志）。

### D4. 自动刷新开关双重取反 + 调用不存在的方法
- **位置**: `ui/main_gui.py:566-573` + `ui/main_gui_events.py:439-447`
- **现象**: `_toggle_auto_refresh` 设置状态后又 `not cur` 翻回；`bottom_bar._draw_toggle` 全项目无定义 → AttributeError。开关行为与 UI 相反，刷新定时器状态错乱。
- **修复**: 统一状态语义，去掉重复取反；删除对不存在方法的调用。

### D5. 工作线程中 `QTimer.singleShot` 永不触发（2 处）
- **位置**: `ui/main_gui_events.py:640`（添加监控）、`ui/main_gui_events.py:379-386`（启动激活模型）
- **现象**: `fire_and_forget` 纯线程里调用 `QTimer.singleShot(0, ...)`，无事件循环 → 回调永不执行。添加监控对话框永远卡死；启动时模型状态刷新缺失。
- **修复**: 改用 `ui.invoker.invoke()` 调度到主线程。

### D6. 删除监控调用不存在的方法 `remove_card`
- **位置**: `ui/main_gui_events.py:697` + `ui/video_list_panel.py`
- **现象**: `VideoListPanel` 无 `remove_card` → AttributeError。数据已删除但卡片残留、撤销未登记、watch_list 未保存，重启后视频"复活"。
- **修复**: 为 `VideoListPanel` 补 `remove_card(bvid)`，并保证 UI/数据一致。

### D7. WBI 签名漏掉 `wts` → 评论/搜索/弹幕接口验签失败
- **位置**: `core/bilibili_api.py:357-372`
- **现象**: 标准实现（对照已安装 bilibili-api-python `_enc_wbi`）先加 `wts` 再排序拼接 md5；本项目先 md5 再加 `wts` → `w_rid` 不匹配，服务端 -403。
- **修复**: 签名前把 `wts` 加入参数参与哈希。

### D8. 增长模型单例共享可变状态（多视频互相污染）
- **位置**: `algorithms/registry.py:132` + `algorithms/models/growth/logistic_growth.py:127-128,191-213`（gompertz/richards 同类）
- **现象**: 每个算法全局单实例，`predict` 内修改 `self.K/r/t0` → 线程池并发时视频 A 的拟合参数被视频 B 覆盖。
- **修复**: 拟合结果改为局部变量，不在实例上存每轮拟合状态（保留默认值字段）。

### D9. 备份同步去重键与 UNIQUE 约束不一致 → 备份库永久停更
- **位置**: `core/database/central_backup.py:281-340` + `core/database/central_crud.py:472`
- **现象**: 按 `(algorithm, predicted_time)` 去重后裸 INSERT，中央库 UNIQUE 是 `(bvid, algorithm, target_threshold)`。预测每轮更新 predicted_time → 第二次同步必撞约束 → 整个备份事务回滚，且 `GROUP BY algorithm, predicted_time` 会合并同轮多阈值行。
- **修复**: 去重键改为 `(algorithm, target_threshold)`，`GROUP BY` 同步修改，INSERT 改 `INSERT OR REPLACE`。

---

## 🟠 中严重度

### D10. 每视频库 `videos.owner_name` 恒为空（键名写错）
- **位置**: `core/database/video_db.py:459`
- **现象**: `video_info.get("owner_name")`，但调用方 dict 键是 `"author"`（`map_api_to_video_dict`）→ UP 主名全空，`central_backup.py:182` 同步时也拿空。
- **修复**: 改为 `video_info.get("author", "")`。

### D11. 镜像库从未初始化（冗余备份静默丢弃）
- **位置**: `core/database/video_db.py:73-100`
- **现象**: `_ensure_mirror()` 只在零调用的 `_execute_on_all()` 内调用 → `_mirror_conn` 永远 None，所有镜像写入静默 return。
- **修复**: 移除死代码（镜像写入在每视频库主路径 + 备份同步下无实际价值），或接通初始化。→ 选择接通：构造时初始化镜像连接（带异常保护）。

### D12. 登录态失效（-101）被静默吞掉；refresh_token 存而不用
- **位置**: `core/bilibili_request.py:158-180`、`core/bilibili_api.py:134,211,229`
- **现象**: -101 与网络故障无法区分，监控线程照常轮询但写不了数据；SESSDATA 过期后需登录接口全部静默失效。
- **修复**: -101 单独记录 WARNING 并置登录失效标记（供 UI 提示），避免被当作普通网络错误。

### D13. 保形预测区间永远冷启动 ±20%
- **位置**: `algorithms/registry.py:695`（`update_ensemble_accuracy` 零调用）
- **现象**: conformal 校准集永远为空，区间宽度从不修正。
- **修复**: 在 `ui/monitor/_prediction.py` 每轮预测后用上一轮预测值 vs 实际值调用 `update_ensemble_accuracy`。

### D14. predictions 表 `is_reached/actual_time/error_rate` 无写入路径
- **位置**: `core/database/video_db.py:535-625`、`core/database/central_crud.py:474-490`
- **现象**: 表有列但所有 INSERT 都不含 → 达峰标记永远默认值。
- **修复**: `add_predictions_batch` 写入 `is_reached`/`actual_time`（当前播放量已达阈值时置位）。

### D15. 时间戳格式不统一破坏去重/排序/备份同步
- **位置**: `ui/monitor/_service.py:213,226,236`（`isoformat` T+微秒）vs `ui/entry_tab.py:638`（`%Y-%m-%d %H:%M:%S`）
- **现象**: 同一列两种格式 → UNIQUE 去重失效、字符串排序错乱、备份 MAX 比较漏同步。
- **修复**: `_service.py` 统一改为 `%Y-%m-%d %H:%M:%S`。

### D16. 代理失败归因竞态（误伤健康代理）
- **位置**: `core/proxy_manager.py:37,113,179`
- **现象**: `_current_request_proxy_idx` 实例级共享，失败回调不传 idx → 多线程并发时归因错误。
- **修复**: 失败回调带上实际使用的代理 idx。

### D17. `_apply_window_weights` 白算（被 coherence 覆盖）
- **位置**: `algorithms/registry.py` `predict_all` 内
- **现象**: coherence 用旧的 `valid_predictions` 里 w 覆盖 window 调整后的权重 → 历史偏差惩罚从未生效。
- **修复**: 两阶段之间重建 `valid_predictions`。

### D18. 删除视频后 predictor 线程泄漏，重加复用过期 dict
- **位置**: `ui/monitor/_service.py`（`_predictors`）、`ui/main_gui_events.py`（remove 流程）
- **现象**: 删除不停线程；重加同 bvid 复用旧 predictor，`self.video` 指向已删除 dict → 预测用旧数据。
- **修复**: 提供 `_stop_predictor(bvid)`，删除视频时调用。

### D19. invoke 队列无异常隔离 → 回调积压
- **位置**: `ui/invoker.py:33-39`
- **现象**: 任一回调抛异常中断 `_drain` 循环，剩余回调滞留、队列无限增长。
- **修复**: 单回调 try/except + 日志。

### D20. QR 登录未知状态码乐观判成功
- **位置**: `core/bilibili_auth.py:476-488`
- **现象**: 未知 status 走 else 返回"登录成功"，但 cookie 提取落空 → 游客身份静默使用。
- **修复**: 未知状态返回失败提示，不进入成功分支。

### D21. UP 总播放量少算（只取第一页 50 条）
- **位置**: `core/up_fetcher.py:228-260`
- **现象**: 投稿 >50 的 UP 主 total_views/total_likes 永久偏小。
- **修复**: 按总数分页拉全，或优先用权威 upstat。

### D22. 配置加载即解密，保存时明文密钥回写磁盘
- **位置**: `config/__init__.py:84-95` + `ui/main_gui_data.py:63-68`
- **现象**: `load_config()` 原地解密，`save_watch_list`/`set_update_channel` 直接保存解密后的明文 → cookie 加密失效。
- **修复**: `save_config` 对敏感字段做幂等加密（已加密则跳过）。

### D23. 训练取消误报"训练完成"
- **位置**: `ui/training_panel.py:756-765`
- **现象**: 取消后仍无条件上报 `all_done` → 显示完成并触发重新预测。
- **修复**: 取消时不发 `all_done`。

---

## 🟡 低严重度

### D24. 代理健康检查把 -403/-404 判为可用
- **位置**: `core/proxy_manager.py:306-326`
- **修复**: 仅 code==0 判可用；-403/-404/-412 判失败。

### D25. Playwright 兜底异常时浏览器进程泄漏
- **位置**: `core/browser_fallback.py:61-115`
- **修复**: try/finally 保证 `browser.close()`。

### D26. Chrome/Edge cookie v10 前缀未剥离，导入必失败
- **位置**: `utils/browser_cookies.py:51-60`
- **修复**: `encrypted_value[3:]` 去除 v10 前缀。

### D27. 弹幕拉取绕过主 HTTP 管道（无代理/无 412 退避）
- **位置**: `core/bilibili_danmaku.py:214,265,382,418`
- **修复**: 直连请求带代理绑定 + 重试/降级到非 wbi seg.so。

### D28. 派生特征缓存键不含数据内容 → 跨视频串键
- **位置**: `algorithms/registry.py:226-230` + `ui/crossover_analysis.py:558`（不传 bvid）
- **修复**: 缓存键加入历史内容摘要（首末点时间戳/播放量）。

### D29. 预测面板 hero 卡对 None 解引用
- **位置**: `ui/prediction_panel.py:154-155`
- **修复**: 增量更新前判 None。

### D30. 历史时间戳解析无异常保护 + NameError
- **位置**: `ui/video_compare_enhanced.py:175-184,236-245`
- **修复**: try/except 包裹解析；`base_t` 初始化。

### D31. ARIMA 把每个采样点当 1 天 → 达标时间放大 1152 倍
- **位置**: `algorithms/models/time_series/arima_simple.py:172,244`
- **修复**: 用实际采样间隔（时间戳中位差）换算小时。

### D32. 详情面板视频缓存删除后重加不失效
- **位置**: `ui/detail_panel.py:710-719`
- **修复**: 缓存改为每次从 `monitored_videos` 现查或删除时失效。

### D33. 里程碑面板切换指标不重绘
- **位置**: `ui/milestone_stats.py:485-499`
- **修复**: `_on_metric_changed` 后重绘。

### D34. 更新检查两套版本比较逻辑不一致
- **位置**: `utils/update_checker.py:247-273`
- **修复**: 统一用版本元组比较。

### D35. 退出时 `_stop_all_predictors` 持锁逐个 join(3s) → 冻结 3N 秒
- **位置**: `ui/monitor/_service.py:117-123`
- **修复**: 先收集再释放锁，锁外 join。

### D36. 在线人数 fallback 返回 str 与主路径 int 混用
- **位置**: `core/bilibili_video.py:116-126`
- **修复**: fallback 统一 int。

---

## 修复状态

| 编号 | 状态 | 说明 |
|------|------|------|
| D1 | ✅ 已修复 | 时间戳数组改 float64（registry.py + base.py polyfit 两处）；并修复单位换算 `slope/3600`→`slope*3600`（原本低估 1296 万倍） |
| D2 | ✅ 已修复 | 淘汰改为 `next(iter(self))+del`，绕开 popitem 的 __getitem__ 调用链；`get()` 改 `[]`+KeyError 保持 LRU 语义 |
| D3 | ✅ 已修复 | LogPanel 补 `cleanup()`（停定时器+冲刷日志） |
| D4 | ✅ 已修复 | `toggle_auto_refresh` 不再取反（QCheckBox.toggled 自带新状态），删除 `_draw_toggle` 调用 |
| D5 | ✅ 已修复 | 两处工作线程 `QTimer.singleShot` 改用 `invoker.invoke` |
| D6 | ✅ 已修复 | VideoListPanel 补 `remove_card(bvid)` |
| D7 | ✅ 已修复 | wts 先入参再哈希，与官方 bilibili-api-python `_enc_wbi` 一致（已验证签名一致） |
| D8 | ✅ 已修复 | logistic/gompertz/richards/weibull 拟合参数改为局部变量返回（保留默认字段），并发不再互相污染 |
| D9 | ✅ 已修复 | GROUP BY 与去重键改 target_threshold，INSERT OR REPLACE，不再整事务回滚 |
| D10 | ✅ 已修复 | video_db `author` 键读取 |
| D11 | ✅ 已修复 | `__init__` 接通 `_ensure_mirror()`（异常防护） |
| D12 | ✅ 已修复 | -101 单独 WARNING + 置 `_logged_out` 标记 |
| D13 | ✅ 已修复 | `_predict_single` 每轮用上轮集成预测值调 `update_ensemble_accuracy` 校准 |
| D14 | ✅ 已修复 | add_predictions_batch 补 is_reached/actual_time（主库+镜像 12 列） |
| D15 | ✅ 已修复 | _service.py 4 处统一 `%Y-%m-%d %H:%M:%S` |
| D16 | ✅ 已修复 | proxy_idx 经 `_prepare_request_kwargs`/`_request` 透传到所有失败回调（4 处） |
| D17 | ✅ 已修复 | window 与 coherence 两阶段间重建 valid_predictions |
| D18 | ✅ 已修复 | `_stop_predictor(bvid)` 删除时停止线程；撤销时 `_ensure_predictor` 重建 |
| D19 | ✅ 已修复 | invoke 单回调 try/except 隔离 |
| D20 | ✅ 已修复 | 未知扫码状态返回 -1，不再误报登录成功 |
| D21 | ✅ 已修复 | up 投稿分页累加（最多 10 页防御） |
| D22 | ✅ 已修复 | save_config 幂等加密；并修复 `is_encrypted` 启发式误判（改为解密试算）——实测明文不再落盘 |
| D23 | ✅ 已修复 | all_done 包进 `if not self._cancel_flag[0]` |
| D24 | ✅ 已修复 | 仅 code==0 判可用，-403/-404 分别报错 |
| D25 | ✅ 已修复 | try/finally 保证 browser.close() |
| D26 | ✅ 已修复 | 剥离 v10 前缀 |
| D27 | ✅ 已修复 | 4 处弹幕直连挂代理（peek_proxy→get_proxy_binding 真实地址） |
| D28 | ✅ 已修复 | 缓存键加内容摘要 md5（registry.py `_content_digest`） |
| D29 | ✅ 已修复 | rate_lbl None 守卫 |
| D30 | ✅ 已修复 | 时间戳解析 try/except + base_t 初始化 |
| D31 | ✅ 已修复 | ARIMA 用实际采样间隔（时间戳中位差）换算小时 |
| D32 | ✅ 已修复 | `_get_selected_video` 去缓存现查 + `_header_video` 对象身份判断 |
| D33 | ✅ 已修复 | `_on_metric_changed` 末尾调 `_redraw_compare()` |
| D34 | ✅ 已修复 | 两路径统一 `_parse_version` 元组比较 |
| D35 | ✅ 已修复 | 先收集再锁外 join |
| D36 | ✅ 已修复 | fallback 返回 int |

**验证**：`pytest tests/` 85 通过；全部改动文件 `py_compile` 通过；WBI 签名与官方实现一致性、LRU 淘汰、float64 时间戳精度、配置密文落盘均实测通过。

**回归测试**：新增 `tests/test_defect_regressions.py`（30 项），覆盖 D1/D2/D7/D8/D9/D10/D13/D14/D19/D20/D22/D24/D28/D31/D34/D36 的修复，`pytest tests/` 共 115 项全绿。

### 额外发现并修复
- **速度单位换算 bug（原报告未列）**：`base.py:326` 与 `registry.py` polyfit 分支 `slope / 3600` 应为 `slope * 3600`——与 2 点分支矛盾且违反测试期望（`test_two_points_positive` 期望 50 views/h）。修复后实测 75s/+5 播放 → 240 views/h ✅。
- `is_encrypted` 启发式判断缺陷（D22 修复过程中发现，明文 `sk-secret-123` 曾被误判为密文）。
