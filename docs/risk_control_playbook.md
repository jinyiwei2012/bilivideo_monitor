# 风控应对手册（412 / 352 / v_voucher / 设备标识）

> 本文是**待实现规格 + 现有缺陷清单**：本项目的风控相关改动都以此为准。
> 接口侧的字段与端点见 [docs/bilibili_api_contract.md](bilibili_api_contract.md)；指标与告警见
> [docs/analysis_enhancements.md](analysis_enhancements.md)。

## 0. 先分清：哪些能本地造，哪些只能由服务端签发

| 值 | 本地可否构造 | 说明 |
|---|---|---|
| `w_rid` + `wts`（WBI 签名） | ✅ **完全可算** | mixin_key 置换表 + MD5（已实现并验证） |
| `bili_ticket` 请求签名 `hexsign` | ✅ 可算 | `HMAC_SHA256("XgwSnGZ1p", "ts"+ts)`；**票据本身**仍由服务端签发 JWT |
| `buvid3` / `buvid4` / `b_nut` / `_uuid` / `b_lsid` / `buvid_fp` | ⚠️ 可生成，但**必须格式合法** | 文档给的是"获取"路径；我们当前**伪造的 32 位无横线 hex 与官方样例不符** → 更易被判风险 |
| `w_webid` | ✅ 可获取（非构造） | 从空间页 `__RENDER_DATA__.access_id` 取，**按天缓存** |
| `v_voucher` | ❌ **不可构造** | 服务端签发的一次性句柄（同值只能 `register` 一次），自造值必失败 |
| `grisk_id` / `gaia_vtoken` | ❌ 不可构造 | 只能由服务端在验证码通过后签发 |

**结论**：能做的只有"**降低被挑战概率**"（签名正确 + 设备标识齐全 + 请求节律 + 会话隔离），
真被挑战才走 `gaia-vgate` 链（需用户过验证码）。

## 1. 错误码语义与处置分流

| 码 | 含义（来源：原文档 `misc/errcode.md`） | 正确处置 | 本项目现状 |
|---|---|---|---|
| `-101` | 账号未登录 | 提示重登 / 触发续期；**不得重试** | 置 `_logged_out` 但**无人读取** ✗ |
| `-352` | **风控校验失败（UA 或 wbi 参数不合法）** | **重取 WBI 密钥 + 校正 UA/Referer**；**换 IP 无效** | ✗ 未被识别，按"空数据"静默吞掉 |
| `v_voucher` | 风控挑战票据（可出现在 `-352`，**也可出现在 `code:0`**） | 记录 + 走 gaia 兜底（交互式） | ✗ 未检测 |
| `-412` | **请求被拦截（客户端 IP 被服务端风控）** | **长冷却（600s 起）+ 换 IP**；**不要改签名** | 与 `-509` 混同处理 |
| `-509` | 超出限制 | 短冷却 + 降速 | 与 `-412` 混同 |
| `-799` | 请求过于频繁，请稍后再试 | 短冷却 + 降速 | 未单独处理（消息匹配会命中 412 分支 ✓） |
| `-403` | 访问权限不足（常见于签名错误） | 重取密钥 + 重签 | 未单独处理 |
| `-404` | 无内容（评论已关闭等） | 正常终止，不算错误 | — |

## 2. 现有实现缺陷与改法（`core/bilibili_request.py`）

### 2.1 缺陷清单（已核对代码）

| 位置 | 现状 | 问题 |
|---|---|---|
| `_is_412_error`（L75-80） | `code in [-412, -509, -10403] or "请求过于频繁" in message` | `-352` **不在其中**（方向正确），但也没有**任何** 352 分支 |
| `_handle_successful_response`（L193-195） | 非 0 码统一 `logger.error` 后 `return data.get("data")` | **`-352` 的响应体只含 `v_voucher`、没有 `replies`** → 调用方看到"空数据"，把风控当成"没有评论/没有弹幕" ✗✗ |
| `_apply_bypass_measures`（L59-73） | 统一执行：换 UA → 提高 `_min_request_interval`（×2，上限 5s）→ **换代理** | 对 `-352` 换 IP 是**无效动作**（352 与 IP 无关），白耗代理额度 |
| `_handle_http_412_response`（L148-160） | `_consecutive_412_errors += 1` + 指数退避 + 绕过措施 | 冷却上限由 `max_retry_delay` 决定，**没有"IP 级封禁长冷却"概念**（上游实践：412 → 600s 起、上限 1800s） |

### 2.2 改法（规格）

```python
# core/bilibili_request.py 新增模块级常量（数值来源：OpenBiliClaw，MIT）
RISK_COOLDOWN_VOUCHER = 180.0     # 352 / v_voucher：短冷却，先修签名
RISK_COOLDOWN_IP = 600.0          # 真 412：IP 级，长冷却
RISK_COOLDOWN_MAX = 1800.0
RISK_VOUCHER_BLOCK_THRESHOLD = 3  # 连续 3 次 voucher 才升级为全局冷却（单次不牵连整轮）

def _is_risk_challenge(data: Dict[str, Any]) -> bool:
    """-352 或响应体携带 v_voucher（注意：code 可能为 0）。"""

def _risk_response_header_voucher(self: Any, response: Any) -> bool:
    """响应头 x-bili-gaia-vvoucher 也存在 → 同样判定为挑战。"""
```

改动点：
1. `_handle_successful_response`：在 `api_code == 0` 之前**先判 `_is_risk_challenge`**，
   命中则**返回结构化信号**（新增 `RiskChallenge` 异常或返回哨兵对象），**不得**再退化成 `None`；
2. 新增 `self._risk_cooldown_until` / `self._voucher_streak`；`_request()` 入口若处于冷却期 →
   立即返回并记 `info`（**避免继续撞墙**，这也是上游"不把额度浪费在冷却期"的做法）；
3. `-352` 分支：`_refresh_wbi_key()`（重取密钥）→ 换 UA → **不换 IP** → 短冷却后重试**一次**；
4. `-412` 分支：长冷却 + `_apply_bypass_measures`（换 IP，保留现有行为）→ 若 `_consecutive_412_errors`
   达到阈值则**停止本轮任务并上报**（类似 HarukaBot 的"IP 被风控，请稍后再试"），而不是无限重试；
5. 冷却状态暴露：`self.risk_state()` → `{cooldown_until, voucher_streak, consecutive_412}` 供 UI/日志展示。

**验收**（`tests/test_risk_split.py`，用 monkeypatch 注入假响应）：
① `-352` 响应不再被当作空数据，且**触发的是重取密钥而非换代理**；
② `code:0 + data.v_voucher` 被识别为挑战；
③ `-412` 触发长冷却，第 3 次后停止重试并上报；
④ 冷却期内不再发起真实请求（断言 HTTP 调用次数为 0）；
⑤ `-404` 仍正常终止、不报错。

## 3. `bili_ticket`（降低反复风控）

**依据**：原文档 `misc/sign/bili_ticket.md` —— `bili_ticket` 放在 Cookie 中，**可降低反复风控**；
文档 `misc/sign/v_voucher.md` 的排查清单里也把它列为"应存在"的 Cookie 之一。

```python
# POST https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket
# 参数：key_id=ec02, hexsign=HMAC_SHA256("XgwSnGZ1p", "ts"+<毫秒时间戳>), context[ts]=<毫秒>, csrf 可选
# 响应：data.ticket（JWT，约 3 天）、data.nav.img / data.nav.sub（可直接用于 WBI 密钥！）
```

**实现方案**：新增 `core/bilibili_ticket.py`
- `ensure_ticket(self) -> str`：读持久化值 → 若缺失或 `bili_ticket_expires` 已过 → 刷新；
  **建议刷新周期 2 天**（有效期 3 天，留 1 天余量），照上游 `get_bili_ticket()` 存
  `ticket` + `expires` 两个字段；
- **顺带收益**：响应里的 `nav.img` / `nav.sub` 可直接刷新 WBI 密钥 → 省一次 nav 请求，
  并在 `nav` 被风控时仍能拿到密钥；
- 持久化：与现有 Cookie 同一出口（`core/bilibili_auth.py::set_cookies` + `_persist_cookies`），
  加密走 `utils/crypto.py::encrypt`；**不得**写进源码或明文配置；
- 注入：在 `core/bilibili_request.py::_get_request_cookies` 里 `cookies.setdefault("bili_ticket", ...)`。

**验收**：`tests/test_bili_ticket.py` —— ① 首次调用生成并持久化（`ticket` + `expires`）；
② `expires` 未到时**不重复请求**；③ HMAC 输入拼接与文档一致（固定 ts 断言 hexsign 长度与确定性）；
④ 请求失败时**不阻塞**主流程（返回空串并记 warning）。

## 4. 设备标识与 UA 硬约束

**目标**：把"伪造的 32 位 hex buvid3/4"换成**服务端下发/格式合法**的标识，并补齐文档要求存在的 Cookie。

**实现方案**（新增 `core/device_identity.py`，或并入 `bilibili_api.py` 的初始化）
1. **buvid3/buvid4**：优先 `GET https://api.bilibili.com/x/frontend/finger/spi`；
   其次访问 `https://www.bilibili.com/` 从 `Set-Cookie` 取 `buvid3` 与 **`b_nut`**；
   替换 `core/bilibili_api.py:241-242`（`self._buvid3 = self._gen_buvid()`）的伪造路径（保留为最后兜底）。
2. **`b_nut`**：与 buvid3 同时从首页 `Set-Cookie` 取；无 Cookie 请求时 `b_nut` = 当前秒级时间戳；
   仅有 buvid3 时为 `100`（文档规则）。
3. **`_uuid` / `b_lsid`**：`_uuid` = 32 位 hex（可本地生成）；`b_lsid` = 8 位 hex + `_` + 毫秒 hex
   （来源 Y2A-Auto 的 `gen_b_lsid`）。
4. **`buvid_fp`**：`murmur3_x64_128(key, seed=31)` 取 `hex(m & (MOD-1))[2:] + hex(m >> 64)[2:]`
   （来源 Bili23-Downloader / Y2A-Auto 的 `gen_buvid_fp`）。
5. **UA 硬约束**（文档明令）：UA **不得包含** `curl` / `python` / `awa`，
   且**同一 UA 不得短时重复请求** → 在 `_rotate_user_agent`（L28）加断言/过滤，命中即替换。
6. **`ExClimbWuzhi` 设备激活（可选）**：`POST /x/internal/gaia-gateway/ExClimbWuzhi`，
   把指纹"登记"给服务端（Bili23-Downloader 的 `init_cookie_info()` 流程：get_buvid → get_bili_ticket → exclimbwuzhi）；
   建议做成**可开关**（`enable_device_activate`），默认关闭，观察效果后再打开。

**注意**：`_uuid`/`b_lsid`/`buvid_fp` 都是**长期标识**，需持久化（同 §3 的出口），
不要每次启动重新生成（频繁变化的指纹本身就是风险信号）。

**验收**：`tests/test_device_identity.py` —— ① 生成值格式符合文档样例（正则）：
`buvid3 = ^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\d+infoc$`、
`b_lsid = ^[0-9A-F]{8}_[0-9A-F]+$`；② `buvid_fp` 对固定输入**确定性**（可复现）；
③ UA 过滤函数拦下含 `python`/`curl`/`awa` 的 UA；④ 持久化后重启不重新生成。

## 5. `w_webid`（新风险参数）

**依据**：`magicdawn/Bilibili-Gate`（MIT，2026-09 活跃）的 `src/modules/bilibili/risk-control/w_webid.ts`；
另见 `chen-zeong/DTV`（MIT）与 `yichengchen/ATV-Bilibili-demo`（GPL-2.0，仅借事实）。

**要点**
- 取值：GET `https://space.bilibili.com/<mid>` → 解析 `#__RENDER_DATA__` → URL 解码 → 取 `access_id`；
  **不区分目标 mid**（用自己的 mid 取一次即可）；**按天缓存**（上游 `dailyCache`）。
  备选取法：GET `https://live.bilibili.com/lol` 后从页面取（DTV 做法）。
- 使用范围：**仅部分 WBI 接口需要**（上游仅在 `x/space/wbi/acc/info` 一带带上）→
  本项目优先用于 `core/bilibili_up.py` 的空间/UP 类 WBI 接口（这是**我们可能被拦的点**）。
- **参与签名**：`w_webid` 与 `w_rid`/`wts` 一起做参数排序（上游按 `["w_webid","w_rid","wts"]` 处理排序细节），
  即在 `_wbi_sign(params)` 之前把 `w_webid` 放进 params。

**验收**：`tests/test_w_webid.py` —— ① 从固定 HTML 片段解析出 `access_id`；
② 同一天内第二次调用**不发请求**（缓存命中）；③ 跨天过期后重取；
④ `w_webid` 出现在签名后的 query 中且排序正确。

**实现状态（2026-09）**：`core/w_webid.py` 已完成并可全部验收（11 项测试）：
`extract_access_id`（URL 编码 / 明文 / 嵌套）、按天缓存（`data/w_webid.json`）、
`fetch_access_id`（先自己的空间页、空则直播页备选）、`get_w_webid`（命中缓存零请求，
失败回退旧值且不抛错）、`with_w_webid(api, params)`（**必须在 `_wbi_sign` 之前调用**）。

⚠ **暂未主动注入任何现有请求**，原因（代码核查结论）：本仓库调用的是
`/x/space/acc/info`、`/x/space/arc/search` 等**非 WBI** 变体（`core/bilibili_up.py` L46/48/106/133），
唯一已签名的 WBI 调用是 UP 搜索 `/x/web-interface/wbi/search/type`（L26）——
上游只在 `x/space/wbi/acc/info` 一带带 `w_webid`，在未验证的接口上加未知参数有触发 `-352` 的风险，
因此留作**显式接入**：等改用 `/x/space/wbi/acc/info` 或确认搜索接口也需要时，
把 `params = self._wbi_sign(params)` 改为 `params = self._wbi_sign(with_w_webid(self, params))`。


## 6. 会话隔离（评论 / 搜索等高频接口）

**依据**：`whiteguo233/OpenBiliClaw`（MIT）—— B站按 **session/接口**限流，
共享 client 会把其它策略的历史累加进来从而**更容易触发 `v_voucher`**；其做法是对搜索接口**单独新建 client**。

**实现方案**
- 监控轮询、评论抓取、搜索发现**各自持有独立的 `BilibiliAPI` 实例**（各自 session/代理绑定/WBI 密钥缓存）；
- 评论抓取已在设计中：`core/bilibili_comment.py::CommentFetcher(api=...)` 默认自建实例（见评论模块）；
- **注意**：Cookie/WBI 密钥可共享读取，但**请求计数与限速必须各自独立**。

**验收**：`tests/test_session_isolation.py` —— 两个实例的 `session` 与 `_min_request_interval` 互不影响；
冷却状态不跨实例传染。

## 7. `v_voucher` → gaia-vgate 兜底链（交互式）

**何时用**：只在前述手段都不奏效、且**用户在场**时。文档明确：**captcha 是最后的选择**，
且"**不是所有风控都可以用本方式通过 captcha 解决**"（`register` 返回 `geetest: null` 即为不可解）。

**流程**（来源：原文档 `misc/sign/v_voucher.md`，实现参考 `Oecxuan/2233TicketBuy::src/gaia.py`，MIT）
```
1) 命中 v_voucher（code -352 或 data.v_voucher / 响应头 x-bili-gaia-vvoucher）
2) POST /x/gaia-vgate/v1/register   body: v_voucher (+ csrf=bili_jct)
   → data.type=geetest, data.token, data.geetest{gt, challenge}   # 同值只能 register 一次，须尽快验证
3) 复用现有 utils/geetest_solver.py::solve(gt, challenge) → validate, seccode
4) POST /x/gaia-vgate/v1/validate  body: challenge, token, validate, seccode (+ csrf)
   → data.grisk_id (= gaia_vtoken)
5) 原请求带上：URL 参数 gaia_vtoken=<grisk_id> + Cookie x-bili-gaia-vtoken=<grisk_id>
```
**实现方案**：新增 `core/gaia_vgate.py`
- `handle_challenge(self, v_voucher: str) -> Optional[str]`（返回 `grisk_id` 或 None）；
- **必须由 UI 触发**（`ui/comment_panel.py` / 设置页弹「需要验证码，是否现在验证？」），
  不允许后台静默求解（会失败且消耗风控额度）；
- `grisk_id` 有效期有限 → 持久化到会话级缓存（同 §3 出口），过期即失效，不做长期存储；
- 失败路径要**可解释**：`geetest: null` → "该风控无法用验证码解除，请稍后重试或更换网络"。

**验收**：`tests/test_gaia_vgate.py` —— ① 5 步流程在假响应下串通（断言请求顺序与字段名）；
② `geetest: null` 时返回明确原因而非抛异常；③ 未注入 `grisk_id` 时不修改请求参数（默认无副作用）。

**实现状态（2026-09）**：`core/gaia_vgate.py` 已完成并全部验收（11 项测试）：
`register`（第 2 步）/ `validate`（第 4 步）/ `solve_challenge`（第 2-4 步，`solver` 可注入，
默认 `utils.geetest_solver.solve`）/ `store_vtoken`·`current_vtoken`·`clear_vtoken`（**会话级**缓存，
实例属性 + Cookie，10 分钟保守 TTL，**不持久化**）/ `with_gaia_vtoken`（无 token 时零副作用）/
`gaia_state` 观测。`v_voucher` 留空时自动回退 `api._risk_last_voucher`（§2 已记录的值）。

**UI 触发入口（已接）**：评论面板的「⚠ 解除风控」按钮（默认禁用，`blocked` 结束时启用）→
确认弹窗 → 后台线程求解 → 日志给结果；命中风控时**保留同一会话**（`CommentFetcher.close(close_api=False)`
+ 面板持有 `_risk_api`），重试时复用该会话，并且**重试请求会带上 `gaia_vtoken`**。

⚠ 两个刻意的设计决定（都有理由）：

1. `gaia_vtoken` 在 **`_wbi_sign` 之后**附加（见 `core/bilibili_comment.py::_fetch_main_page`）——
   它由 gaia 网关层消费，不参与 `w_rid` 计算；这样过期/缺失的 token 也**不会破坏签名**
   （失败模式更安全：宁可不带，也别把签名搞坏）。
2. **绝不后台静默求解**：求解要过人机验证、失败还消耗风控额度，且 `geetest: null` 明确不可解 ——
   只能由用户在界面里点确认。

⚠ 未验证部分（如实标注）：本机无法对线上风控实测，因此「能否真的解除」未经端到端验证；
已验证的是**流程正确性**（请求顺序、字段名、状态流转、零副作用）与 UI 可达性。


## 8. Cookie 续期链（长跑不掉登录）

**字段与端点细节见** [bilibili_api_contract.md](bilibili_api_contract.md) §4；留档原文见
`docs/bilibili-api/frozen-fork/cookie_refresh.md`。**已实现**：`core/bilibili_cookie_refresh.py`。

1. `GET https://passport.bilibili.com/x/passport-login/web/cookie/info` → `data.refresh` / `data.timestamp`；
   `code=-101` → 直接判"已掉登录"（与 §1 的 `_logged_out` 打通）；
2. `refresh_{timestamp}` 经 **RSA-OAEP（SHA-256，固定公钥）** 加密后转**小写 base16** = `CorrespondPath`；
3. `GET https://www.bilibili.com/correspond/1/{CorrespondPath}` → **返回的是 HTML 页面**，
   其中 `<div id="1-name">` 的内容才是实时口令 `refresh_csrf`（不是 Cookie！）；
4. `POST https://passport.bilibili.com/x/passport-login/web/cookie/refresh`
   （`csrf`=当前 `bili_jct`、`refresh_csrf`、`source=main_web`、`refresh_token`=**旧** ac_time_value）
   → **新 Cookie 只在 `Set-Cookie` 响应头里**，body 里只有**新的** `refresh_token`
   （错误码：`-101` 未登录 / `-111` csrf 失败 / `86095` token 与 Cookie 不匹配）；
5. `POST https://passport.bilibili.com/x/passport-login/web/confirm/refresh`
   （`csrf`=**新** Cookie 里的 `bili_jct`，`refresh_token`=**旧**值，用来让旧凭证失效）；
6. 结果经 `core/bilibili_auth.py::set_cookies` + `_persist_cookies` 落盘（加密），
   并把新的 `refresh_token` 写回账号记录（否则重启后又用回旧值）。

> 2026-09 订正：本节旧稿把第 4 步写成 `web/exchange_cookie`，那是**扫码登录**用的接口；
> Web 续期用的是 `web/cookie/refresh`。第 5 步是 **POST** 不是 GET。

**触发时机**：`refresh_now()` 为单次执行入口，`maybe_refresh(api, interval_hours=12)` 按间隔节流
（未到间隔**不发请求**）。当前已接入：设置页「账号」的*检查登录*（`ui/settings_account.py::_verify_login`
→ `_maybe_renew_cookies`）。**未接入**：应用启动后一次与后台定时器——留待后续批次（见 §11 ⑩）。

**验收**：`tests/test_cookie_refresh.py`（14 项）—— ① `refresh=false` 时不动作且零请求；
② `-101` 判掉登录并给出「需重新登录」原因；③ 五步的 URL 与字段名断言（含第 5 步用**新** csrf + **旧** token）；
④ 成功后续期后的 5 个新 Cookie 落盘、`refresh_token` 回写账号；⑤ `86095`/`-111` 分流；
⑥ 确认步骤失败仍保留新 Cookie（状态为 `refreshed_unconfirmed`）；⑦ 节流生效；
⑧ 固定公钥可加载且为 1024 位（防手抄 PEM 出错）。


## 9. 零登录策略（缩小暴露面）

**事实**：`lepockyio-ops/biliradar`（MIT）与 BiliBili-Analyzer 都**只用公共接口**
`/x/web-interface/view`，**无需 Cookie、无 WBI 签名**就拿到播放/点赞/投币/收藏/分享/弹幕/评论/时长/发布时刻。

**对本项目的意义（重要）**：我们的**主监控轮询**（纯视频指标）完全可以**零登录**运行：

| 功能 | 是否必须登录 | 建议 |
|---|---|---|
| 视频指标监控（播放/互动/在线） | ❌ 不需要 | **默认不带 Cookie**（独立无登录实例）→ 风控面最小、且不牵连账号 |
| UP 主 / 空间 WBI 接口 | ⚠️ 部分需要（还可加 `w_webid`） | 带 Cookie |
| 历史弹幕（`x/v2/dm/history`） | ✅ 需要 | 带 Cookie；失败静默返回空（现状）→ 应改为**明确提示** |
| 评论抓取 | ⚠️ 只读评论多数可匿名（但易触发 voucher） | 优先匿名 + 独立 session；触发挑战再用登录态 |
| 热门发现 / 搜索 | ⚠️ 匿名更易被打 voucher | 带 Cookie，独立 session |

**实现方案**：给 `BilibiliAPI` 增加 `with_cookies: bool = True` 构造参数（或 `clone_anonymously()`），
监控 worker 使用匿名实例；**并在 UI 上标注**哪些功能需要登录。

**验收**：`tests/test_anonymous_client.py` —— 匿名实例的请求 Cookie 仅含 buvid/设备标识、
不含 `SESSDATA`/`bili_jct`；监控路径在无登录态下仍能取到 `view` 数据（用假响应断言）。

## 10. 可观测性与 `_logged_out` 死信号

**现状**：`core/bilibili_request.py:178` 在 `-101` 时置 `self._logged_out = True`，
**全仓无人读取** → 用户掉登录完全无感知。

**改法**
1. `get_status()`（`core/bilibili_api.py`）已返回 `isLogin` 与 `has_buvid3` → 在此基础上补充
   `has_bili_ticket` / `has_b_nut` / `risk_state()`；
2. 掉登录时：日志 warning + **状态栏/托盘提示** + 一次通知（`core/notification.py`）+ 触发 §8 续期；
3. 统计并暴露：`{voucher_hits, http_412_count, cooldown_until}` → 设置页"网络诊断"展示，
   便于用户判断"是不是该换代理"。

**验收**：`tests/test_risk_observability.py` —— ① `-101` 后 `get_status()` 的登录项为 False 且
产生一次通知调用（mock 断言）；② `risk_state()` 字段完整。

## 11. 落地顺序与许可

| 序 | 项 | 改动面 | 风险 | 预估 | 状态（2026-09-15） |
|---|---|---|---|---|---|
| 1 | **`-352` 识别 + 分流（§2）** | `core/bilibili_request.py` | 中（改重试主路径，需真测试） | 小 | ✅ 完成 `b6b73e5`（`tests/test_risk_control.py` 10 项） |
| 2 | **`_logged_out` 接线 + 风险观测（§10）** | 请求层 + 状态栏/通知 | 低 | 小 | ⚠ 只做了**信号产生**：`_logged_out`/`risk_state()` 已有并进 `get_status()["risk"]`；**消费端（状态栏/托盘/通知/网络诊断页）未做** |
| 3 | **会话隔离（§6）** | 调用方建实例处 | 低 | 小 | ✅ 完成 `f60ee89`（`tests/test_session_isolation.py` 5 项） |
| 4 | **`bili_ticket`（§3）** | 新模块 + 注入点 | 低（可开关） | 中 | ✅ 完成 `f60ee89`（`tests/test_bili_ticket.py` 12 项） |
| 5 | **设备标识补齐（§4）** | 新模块 + 初始化 | 中（格式错反而更糟，需正则测试） | 中 | ✅ 完成 `81f81a4`（13 项；**不含** `buvid_fp`，见 §4 与 §13） |
| 6 | **零登录监控（§9）** | `BilibiliAPI` 构造 + 监控 worker | 中（功能回归需覆盖） | 中 | ⬜ **未做**（用户 2026-09 明确「暂缓」，勿擅自开工） |
| 7 | **Cookie 续期链（§8）** | 新模块 + 定时器 | 中（涉及登录态） | 中 | ⚠ 链路完成 `80327dc`（14 项）；**启动后一次 + 后台定时器未接**——目前仅设置页「检查登录」触发（`ui/settings_account.py:309`） |
| 8 | **`w_webid`（§5）** | 签名前注入 + 日缓存 | 中（仅部分接口需要） | 中 | ⚠ 模块完成 `ce9c401`（11 项）；**无已验证注入点**（本项目相关接口非 WBI），helper 备好待用 |
| 9 | **gaia 兜底链（§7）** | 新模块 + UI 交互 | 高（依赖用户在场，且不保证可解） | 大 | ✅ 完成 `3199699`（11 项 + 评论面板「⚠ 解除风控」按钮 + 重试带 `gaia_vtoken`）；⚠ 线上「能否真的解除」**未端到端验证**（见 §7 注） |

**统一验收**：`black --line-length=120`、`lint_gate`、`type_gate`、`pytest tests/ -q`；
改动 `core/bilibili_*.py` 后需 `python scripts/update_hashes.py --hashes-only` 并确认启动无完整性报错
（这些文件在 `scripts/sign.py::CORE_FILES` 内）。

**来源与许可**

| 来源 | 许可 | 使用方式 |
|---|---|---|
| `whiteguo233/OpenBiliClaw` | MIT | 冷却参数（180/600/1800、连续 3 次）与会话隔离 |
| `magicdawn/Bilibili-Gate`、`chen-zeong/DTV` | MIT | `w_webid` 取法与日缓存 |
| `Oecxuan/2233TicketBuy` | MIT | gaia-vgate 5 步流程 |
| `ScottSloan/Bili23-Downloader`、`fqscfqj/Y2A-Auto` | GPL-3.0 | `b_lsid`/`buvid_fp` 生成算法与 Cookie 组合清单（**仅借鉴事实，不复制代码**） |
| `RayWangQvQ/BiliBiliToolPro` | MIT+GPL 混合 | "Cookie 完整性闸门"思路 |
| 原文档 `misc/{errcode,sign/*,buvid3_4}.md` | 归档 | 错误码语义与硬约束（已离线留档） |

## 12. 明确不做 / 无效的事

1. **不要构造 `v_voucher`**：它是服务端一次性句柄，自造值 `register` 必失败。
2. **不要把 `-352` 当作限流去换 IP**：352 是签名/UA 问题，换 IP 无效且白耗代理。
3. **不要把 captcha 当常规手段**：需用户操作，且部分风控不可解。
4. **不要硬编码静态 Cookie/指纹**（多个老项目的通病）：一旦泄漏即账号风险，且会随失效静默失败。
5. **不要拷贝 GPL/AGPL 项目代码**：本项目 MIT 且分发 exe，只能借鉴"事实与思路"。
6. **不要为了绕过风控而提升请求频率**：文档与所有活跃项目的一致结论是**降频 + 合规头 + 合法标识**。

## 13. 尚未完成清单（截至 2026-09-15，对齐代码核实）

> 本节是「下一步做什么」的唯一入口。每条都注明了**为何没做**与**怎么算做完**（验收），
> 避免下次接手时把已完成项重做、或把暂缓项当成遗漏。

| # | 待办 | 现状与原因 | 验收 |
|---|---|---|---|
| 1 | **§10 掉登录的消费端** | `_logged_out` / `risk_state()` 只在 core 内部产生，**全仓无人读取**（已 grep 核实）→ 用户掉登录仍无感知 | 状态栏/托盘提示 + 一次 `core/notification.py` 通知 + 设置页「网络诊断」显示 `{voucher_hits, http_412_count, cooldown_until}`；新增 `tests/test_risk_observability.py` |
| 2 | **§8 续期定时接入** | 链路已通，但只在设置页「检查登录」触发（`ui/settings_account.py:309` 调 `maybe_refresh`）→ 长期挂机不会自动续期 | 启动后一次 + `ui/main_gui_tick.py`（1s tick）内按 12h 间隔调用 `maybe_refresh`；断言「未登录时零请求」 |
| 3 | **§4 `buvid_fp` + `ExClimbWuzhi`** | 未做：本机无 `mmh3`，离线留档只覆盖 **APP 端**算法，**无可验证参考向量** → 凭空写不可验（当前请求也不发这些字段） | 先取得可核对向量（真实请求体或 mmh3 实现）再实现；否则保持现状并在 UI 不承诺 |
| 4 | **§9 零登录监控** | **用户明确要求暂缓**（2026-09） | `BilibiliAPI(with_cookies=False)` / `clone_anonymously()`；新增 `tests/test_anonymous_client.py`（匿名请求 Cookie 不含 `SESSDATA`/`bili_jct`，监控仍能取 `view` 数据） |
| 5 | **§5 `w_webid` 注入** | 模块 + 日缓存已完成，但核查发现本项目通路（`/x/space/acc/info`、`/x/space/arc/search`）**非 WBI**，唯一已签名 WBI 是 UP 搜索（`core/bilibili_up.py:26`）→ 不拿在跑通路赌未知参数 | 先确认某接口确实要求 `w_webid`（对线上取证）再注入；注入必须用现成 `with_w_webid` 且放在 `_wbi_sign` **之前** |
| 6 | **完整性清单决策** | `scripts/sign.py::CORE_FILES` 是显式清单，**不含** `device_identity` / `bili_ticket` / `cookie_refresh` / `w_webid` / `gaia_vgate` / `bilibili_comment`（已 grep 核实）→ 这 6 个模块被篡改不会触发启动完整性告警 | **需用户决策**：是否纳入（纳入须同步跑 `scripts/sign.py` 并提交清单变更） |
| 7 | **契约 §7 的 4 个密码登录缺陷** | 全部未修，分布在 `core/bilibili_auth.py`：密文用 hex（应 base64，L278）、`seccode` 缺 `\|jordan`、`code:0 + status!=0` 误报成功（L120）、`exchange` 应改 `exchange_cookie`（L525） | 详见 `docs/bilibili_api_contract.md` §7 小结；新增 `tests/test_password_login_contract.py` |
| 8 | **契约 §8 评论接口迁移** | `core/bilibili_api.py:171` 的 `COMMENT_URL` 仍是**已废弃**的 `/x/v2/reply/main`，`core/bilibili_video.py::get_video_comments`（L183）仍用它 + `pn` 翻页 | 让 `get_video_comments` 复用 `core/bilibili_comment.py`（新端点 + 游标），删掉重复分页逻辑；断言走 `/x/v2/reply/wbi/main` |

**已完成的验证基线**（下次改 `core/bilibili_*.py` 后必须复现）：
`black --line-length=120 .`、`python scripts/lint_gate.py`、`python scripts/type_gate.py`、
`python -m pytest tests/ -q`（**440 passed**）、`python scripts/update_hashes.py --hashes-only`、
`python main.py` 启动 18-20s 无异常。

