# B站接口契约（本项目实现依据）

> 本文是**实现规格**：每条规则都对应到具体代码位置与验收方式。改动 `core/bilibili_*.py`
> 的登录/WBI 逻辑前先读本文；实现与本文冲突时，以本文为准（本文以官方 OpenAPI 快照为据）。

## 0. 来源、时效与不确定性（先读）

| 来源 | 性质 | 快照时间 | 覆盖 |
|---|---|---|---|
| `bacnext.apifox.cn`（`BACNext/BACNext`，MIT） | **权威、在维护** | OpenAPI 同步 **2026-06-16**；线上 `llms.txt` 抓于 **2026-09-15** | 登录态全链、Wbi、视频/UP、空间、关系、安全中心 |
| `Goooler/bilibili-API-collect@trunk` | 镜像、**已冻结** | 内容最后更新 **2026-01-28/29** | 含**弹幕/评论**（BACNext 没有） |
| `BACNext/bilibili-API-collect-backup` | **原文档完整备份**（36 个 docs 目录，未归档） | 备份于 **2026-01-30** | 含 `comment/`、`danmaku/`、`misc/sign/wbi.md` 等 |
| 本项目实测 | 最终裁决 | — | 一切与文档冲突处以实测为准 |

**已死来源**：`SocialSisterYi/bilibili-API-collect` 原仓因 **2026-01-18 律师函**关停（仅剩 README）；
依赖 `bilibili-api-python`（`Nemo2011/bilibili-api`）**已归档**（2026-07-06，size 0）→ 上游不再修复，
本项目不得新增对其登录/签名逻辑的依赖，现有兜底调用应逐步替换为本文实现。

**BACNext 的覆盖边界（实测确认，2026-09-15）**：跨 6 个模块（`main` 115 路径 / `passport` 26 /
`live` 3 / `vc` 3 / `hyg` 0 / `biligame` 0）与线上 `llms.txt` 全量目录检索
`/dm`、`danmaku`、`reply`、`comment`、"弹幕/评论/回复" —— **0 命中**。

- **弹幕、评论：BACNext 完全没有**；已从其原文档备份仓 `BACNext/bilibili-API-collect-backup` 取回
  `docs/comment/`（3 文件，含 141 KB 的 `list.md`）与 `docs/danmaku/`（10 文件），离线留档在
  [`docs/bilibili-api/original-backup/`](bilibili-api/original-backup/) → 评论契约见 §8。
- `main` 模块的「历史记录」是**观看历史**，**不是**本项目使用的历史弹幕（`x/v2/dm/history`），勿混。

**未实测项（实现时按"保守 + 可回退"处理）**：① `exchange_cookie` 与旧文档 `cookie/refresh` 的关系；
② 密码登录各字段在 2026-06 后的服务端行为；③ 弹幕/评论接口在 2026-01 后的变更。

来源快照（离线留档，防上游再次消失）：[`docs/bilibili-api/`](bilibili-api/) 与
`%TEMP%\opencode\bacnext\{main,passport,live,vc,hyg,biligame}.json`。

## 1. WBI 签名

**规范**（BACNext《Wbi 签名》，与旧 `wbi.md` 一致）：

```javascript
const mixinKeyEncTab = [
  46, 47, 18,  2, 53,  8, 23, 32, 15, 50, 10, 31, 58,  3, 45, 35, 27, 43,  5, 49,
  33,  9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48,  7, 16, 24, 55, 40,
  61, 26, 17,  0,  1, 60, 51, 30,  4, 22, 25, 54, 21, 56, 59,  6, 63, 57, 62, 11,
  36, 20, 34, 44, 52
]
const getMixinKey = (orig) => mixinKeyEncTab.map(n => orig[n]).join('').slice(0, 32)
```

签名步骤（顺序不可变）：

1. 取密钥：`GET https://api.bilibili.com/x/web-interface/nav` → `data.wbi_img.img_url` / `sub_url`，
   各自截取**最后一个 `/` 之后、最后一个 `.` 之前**的片段；`img_key + sub_key` 共 64 字符。
2. `mixin_key = getMixinKey(img_key + sub_key)` —— **按上表重排后取前 32 字符**。
   密钥有效期 **600 s**（Apifox 脚本 `WBI_KEY_EXPIRE = now + 600`），过期须重取。
3. 参数加 `wts = 当前秒级时间戳`（**字符串**参与拼接）。
4. key **升序排序**；对**值**先 `replace(/[!'()*]/g, '')`；
   k 与 v 都做 `encodeURIComponent`（Python：`urllib.parse.quote(s, safe='')`）；`&` 连接。
5. `w_rid = md5(query + mixin_key)`。

**验证向量（可离线锁定实现）**：`img_key = 7cd084941338484aae1ad9425b84077c`、
`sub_key = 4932caff0ff746eab6f01bf08b70ac45`（nav 响示例）→
`mixin_key = ea1db124af3c7062474693fa704f4ff8`。参数 `{foo:'114', bar:'514', zab:1919810, wts:1702204169}`
→ query `bar=514&foo=114&wts=1702204169&zab=1919810` → 拼 `mixin_key` 后取 MD5 即 `w_rid`。

**补充事实**（原文档 `misc/sign/wbi.md`）：`img_key`/`sub_key` 全站统一、**每日更替** → 必须缓存并刷新；
百分号编码要求**十六进制大写**、空格编码为 `%20`（**不是** `+`）→ Python 用 `urllib.parse.quote(s, safe="")`；
签名缺失或错误时部分接口返回 **`v_voucher`**（风控票据）而非单纯 `-403`。
另：`img_key`/`sub_key` 亦可从 `bili_ticket` 响应（`GenWebTicket` 的 `nav.img`/`nav.sub`）获取，与 nav 等价。

**本项目实现要求**

| 要求 | 位置 |
|---|---|
| 派生用 `mixinKeyEncTab` 重排取前 32（**不是** `md5(img_key+sub_key)`） | `core/bilibili_api.py::_refresh_wbi_key` |
| 缓存 600 s（`_wbi_key_expire`），过期重取 | 同上 |
| 密钥片段用「最后 `/` 到最后的 `.`」截取（兼容 `.png` 之外的后缀） | 同上 |
| 值过滤 `!'()*`、k/v 都 URL 编码、key 排序、`wts` 字符串 | `core/bilibili_api.py::_wbi_sign` |
| 三个调用点共用同一实现：历史弹幕、UP 主、视频信息 | `core/bilibili_danmaku.py`、`core/bilibili_up.py`、`core/bilibili_video.py` |

**历史缺陷**：旧实现 `_wbi_key = md5(img_key + sub_key)` 且 `_wbi_sign` 用 `f"{k}={v}"` 裸拼
（无编码、无过滤）→ 服务端验签失败（`-403`）。

## 2. 密码登录 `POST /x/passport-login/web/login`

**官方先决条件**：「本接口需要先**申请验证码**和**获取公钥&盐**」；并且
「此登录方式**在极大部分情况下**均需要进行二次验证，因此**除非必要，不建议使用此登录方式**」
→ 本项目策略：**扫码登录为主**，密码登录为可选路径。

**密文**：`password = base64_encode(RSA_encrypt(pubkey, salt + plain_password))`（PKCS#1 v1.5）
→ **base64，不是 hex**。盐（`hash` 字段）有效期文档说法不一（20 s / 120 s）→ 实现按**保守 20 s**，
**每次提交前重新取 key/salt**。

**请求体必填字段**（`application/x-www-form-urlencoded`）：

| 字段 | 说明 |
|---|---|
| `username` | 账号 |
| `password` | **base64** 密文 |
| `validate` | 极验通过返回 |
| `token` | 极验 `token`（来自申请验证码接口） |
| `seccode` | **`validate + "\|jordan"`** |
| `challenge` | 极验 `challenge` |

可选：`go_url`。**注意**：不存在 `captcha` / `captcha_type` 字段（旧实现误用）。

**成功判定：必须看 `data.status`，不能只看 `code`**

| 场景 | 响应 |
|---|---|
| 真成功 | `code: 0` + `data.status: 0` + `data.url`（crossDomain，含 5 个 Cookie）+ `refresh_token` |
| **风控（需手机验证）** | **`code: 0`** + `data.status: 2` + `message: 本次登录环境存在风险, 需使用手机号进行验证或绑定` + `data.url`（`h5-app/passport/risk/verify`）+ `refresh_token: ''` |
| 密码时间戳过期 | `code: -662`（= 盐过期，须重取 key/salt 重试） |
| 验证码错误 | `code: -105` |
| 用户名或密码错误 | `code: -629` |

**历史缺陷**：`_password_login_result` 不看 `data.status` → 风控时取不到 Cookie 却返回
`{"code": 0, "message": "登录成功", "cookies": {}}` → UI **误报登录成功**。

## 3. 扫码登录

- `GET /x/passport-login/web/qrcode/generate` → `qrcode_key` + `url`；
- `GET /x/passport-login/web/qrcode/poll?qrcode_key=...`，`data.code`：`0` 成功、
  `86101` 未扫码、`86090` 已扫码待确认、`86038` 二维码失效；
- 成功时 Cookie 经 **`Set-Cookie` 下发 5 个**：`SESSDATA`、`bili_jct`、`DedeUserID`、
  **`DedeUserID__ckMd5`**、**`sid`**；响应体另给 `refresh_token`（有效期长，用于续期）。
  本项目须**收全 5 个**（现仅收 3 个）；
- `data.message` 可能是风控文案「本次登录环境存在风险, 需使用手机号进行验证或绑定」→ 必须**原样呈现给用户**。

## 4. Cookie 续期链（长跑不掉登录）

1. `GET /x/passport-login/web/cookie/info`（需 `SESSDATA`，可选 `csrf`）→ `data.refresh`（bool）、
   `data.timestamp`；`-101` = 未登录；
2. 需要续期时，由 `refresh_<毫秒时间戳>` 经 **RSA-OAEP（固定 JWK）加密后转小写 base16** 得 `CorrespondPath`；
3. `GET /correspond/1/{CorrespondPath}`（"主站 Correspond 续期"）取得 `CorrespondPath` Cookie；
4. 用 refresh_token 换新 Cookie：**`POST /x/passport-login/web/exchange_cookie`**（官方名"获取 Cookie"）；
5. 刷新结果确认：`GET /x/passport-login/web/confirm/refresh`。

**历史缺陷**：`core/bilibili_auth.py::_exchange_qr_refresh_token` 调用
`/x/passport-login/web/exchange` —— 该路径**不在任何文档中**，正确名为 **`exchange_cookie`**
→ 扫码的 refresh_token 兜底长期静默失败。

## 5. 登录态可观测性

- `core/bilibili_request.py` 在 `api_code == -101` 时置 `_logged_out`，但**全仓无人读取**（死信号）
  → 掉登录必须可见（日志 + 状态栏/通知），并触发续期或重登提示。
- 登录态唯一判定入口仍是 `core/bilibili_api.py::get_status()`；新增消费方不得绕过它。

## 6. 环境约束（踩过的坑，勿回归）

- UA **不得含** `curl` / `python` / `awa`；`buvid` 相关接口不可短时重复请求；
- 部分接口校验 `Referer`（如空间"导航栏状态数"）；用户粉丝接口要求**登录 + Referer 为 bilibili 子域
  + UA 不含 `python`** 才返回列表；
- 本项目实际 `Cookie`/`buvid` 注入出口唯一：`core/bilibili_api.py`（`session.cookies.update`）与
  `core/bilibili_request.py` 的每请求头注入 —— 新增签名/票据逻辑必须走同一出口。

## 7. 契约 → 实现 → 验收 映射

| # | 契约条目 | 实现位置 | 验收 | 状态（2026-09-15 核对） |
|---|---|---|---|---|
| 1 | WBI mixin key 重排取前 32 | `core/bilibili_api.py::_refresh_wbi_key` | 测试向量（固定 img/sub → 已知 mixin_key） | ✅ `tests/test_wbi_signing.py` |
| 2 | WBI 值过滤 + URL 编码 + 排序 + wts | `core/bilibili_api.py::_wbi_sign` | 签名回归测试 + 真实接口非 `-403` | ✅ 同上 |
| 3 | WBI 密钥 600 s 缓存 | 同上 | 缓存命中/过期的单元测试 | ✅ 同上 |
| 4 | 密码密文 base64 | `core/bilibili_auth.py::login_with_password` | 断言 `password` 为 base64（非 hex） | ❌ **未修**：`bilibili_auth.py:278` 仍是 `encrypted.hex()` |
| 5 | 每次提交前重取 key/salt | 同上 | 断言调用两次 key 接口 | ⚠ 部分：首次提交前取（L256-257），但极验重提（L310）复用旧密文，未重取 |
| 6 | 极验 6 必填字段 + `seccode=\|jordan` | `_submit_geetest_login` / `_try_auto_geetest_login` | 断言请求体字段齐全 | ❌ **未修**：全仓 grep 无 `jordan`，`seccode` 未加该后缀 |
| 7 | 成功判定 `data.status` | `_password_login_result` / `login_with_password` | 风控响应不得返回"登录成功" | ❌ **未修**：`_password_login_result`（L120-143）不读 `data.status`，`code==0` 即报成功 |
| 8 | `exchange` → `exchange_cookie` | `_exchange_qr_refresh_token` | 断言请求 URL | ❌ **未修**：`bilibili_auth.py:525` 仍是 `web/exchange` |
| 9 | 扫码收全 5 个 Cookie | `_collect_qr_response_cookies` | 断言 5 键 | ⚠ 部分：只收 `SESSDATA`/`bili_jct`/`DedeUserID`（L505-517），缺 `DedeUserID__ckMd5`/`sid`（`_extract_login_cookies` 已有 8 键名单可复用） |
| 10 | `-101` 掉登录可见 | `core/bilibili_request.py` + 通知 | 断言信号被消费（日志/回调） | ⚠ 部分：信号已产生（`_logged_out` / `risk_state()` 已进 `get_status()`），但**全仓无人读取** → 状态栏/托盘/通知未接（见 `risk_control_playbook.md` §10、§13） |

> **未修项小结（4 个真缺陷同在 `core/bilibili_auth.py`，可直接照此修）**
> ④ `encrypted.hex()` → `base64.b64encode(encrypted).decode()`（明文为 `hash + password`，PKCS#1 v1.5）；
> ⑥ `seccode` 统一加 `"|jordan"` 后缀（3 处请求体）；
> ⑦ `code == 0 且 data.status != 0` 必须判为风控失败（当前会误报"登录成功"并写入无效 Cookie）；
> ⑧ `https://passport.bilibili.com/x/passport-login/web/exchange` → `.../web/exchange_cookie`。
> ⑤⑨ 属健壮性补强（重取 key/salt、补齐 Cookie 键）。
> 验收：新增 `tests/test_password_login_contract.py`（断言密文 base64 可解回 `hash+password`、
> 请求体含 `validate`/`seccode` 且带 `|jordan`、`code:0 + status!=0` 返回失败、exchange URL 正确）。

## 8. 评论抓取（`x/v2/reply` 族）

来源：`docs/bilibili-api/original-backup/comment/{list,readme,action}.md`（原文档备份，2026-01-30）。

| 端点 | 用途 | 备注 |
|---|---|---|
| `GET /x/v2/reply/wbi/main` | 评论主列表（分页） | **需 WBI 签名**；旧 `/x/v2/reply/main` 已废弃 |
| `GET /x/v2/reply/reply` | 楼中楼（指定评论的回复） | `root` / `ps` / `pn` |
| `GET /x/v2/reply/dialog/cursor` | 评论对话流 | |
| `GET /x/v2/reply/hot` | 热门评论 | |
| `GET /x/v2/reply/info` | 指定评论信息 | |
| `GET /x/v2/reply/count` | 评论数量 | |

> **本项目现状（2026-09-15 核对）**：`core/bilibili_api.py:171` 的 `COMMENT_URL` 仍指向**已废弃**的
> `/x/v2/reply/main`，`core/bilibili_video.py::get_video_comments`（L183）仍用它 + `pn` 翻页
> → 待迁移到 `/x/v2/reply/wbi/main`（WBI 签名 + `pagination_str` 游标）。
> **迁移办法**：直接让 `get_video_comments` 复用已实现的新模块 `core/bilibili_comment.py`
> （已走 `/x/v2/reply/wbi/main` + 楼中楼 `/x/v2/reply/reply`，含重试与风控分流），
> 不要再写一份分页逻辑。

**主接口参数**：`type`（评论区类型，**必要**；视频 = `1`，全表见 `comment/readme.md`）、
`oid`（目标 id，**必要**；视频为 **aid**）、`mode`（`0`/`1`/`2`/`3` 排序）、
`pagination_str`（`{"offset":"<上次响应 data.cursor.pagination_reply.next_offset>"}`）、
`plat=1`、`seek_rpid`、`web_location=1315875`；鉴权 Cookie（`SESSDATA`）或 APP `access_key`。

**分页**：`data.cursor.is_end` 判结束；`data.cursor.pagination_reply.next_offset` 回填下一次的
`pagination_str.offset`；其中 `offset.type` 随 `mode` 变化（`mode=2` → `3`，`mode=3` → `1`）。

**错误码**：`0` 成功、`-400` 请求错误、`-404` 无内容、`12002` 评论区已关闭、`12009` 评论区类型不合法。
**签名错误**：`-403` 或 `-352` → 即 §1 的 WBI 缺陷会直接阻断评论抓取。

**游标语义（实测结论：`BiliStalkerMCP` PR#6 + 线上抓包）**

- 主接口是**游标**翻页，`pn` 被忽略（实测 `pn=1` 与 `pn=2` 返回完全相同内容）；
- `mode=3`（热度）时 `cursor.next` 恰为顺序页码（1→2→3）→ `next=页码` 偶然可用；
- `mode=2`（时间）时 `cursor.next` 是**内容相关的非顺序游标**（如 78→67→…）→ 无状态页码**无法**推导，
  必须原样回传上一页的 `next_cursor`；
- 旧 `/x/v2/reply`（无 `wbi`）已基本废弃（`pn>1` 返回空、无子回复预览）→ 不得使用。

**其它实测**：只读评论只需 `SESSDATA`（**无需** `bili_jct`）；`-412`/`-509` 应按**可重试**处理并留间隔；
楼中楼 `/x/v2/reply/reply` 走传统 `pn` 页码翻页。

**可参考的开源实现**（真实调用同一接口）

| 项目 | 参考价值 |
|---|---|
| `NanmiCoder/MediaCrawler` → `media_platform/bilibili/client.py` | **标杆**：`/x/v2/reply/wbi/main` + `/reply/reply`，含 WBI 签名、限速、代理 |
| `ShilongLee/Crawler` → `service/bilibili/logic/{comments,replys}.py` | `pagination_str` + 首页 `seek_rpid` + `next_offset` 完整翻页 |
| `sansan0/bilibili-comment-analyzer`（GPL-3.0） | 评论**情感分析**，与本项目用途最接近 |
| `whiteguo233/OpenBiliClaw`（MIT）、`sigcli/sigcli`（MIT） | 简洁的只读实现 |
| ⚠️ `Turing-Project/AntiFraudChatBot`、`ASoulCnki` 等多数老项目 | 仍用**已废弃**的 `/x/v2/reply/main` → 不可照抄 |
