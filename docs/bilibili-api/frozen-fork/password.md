# 瀵嗙爜鐧诲綍

## 瀵嗙爜鐧诲綍娴佺▼(浼唬鐮?

```python
璐﹀彿 = '2333333'
瀵嗙爜瀛楃涓?= 'password'

# 1.浜烘満楠岃瘉姝ラ
token, gt, challenge = 鑾峰彇楠岃瘉鐮?)
validate = 濉啓楠岃瘉鐮?gt, challenge) # 杩欎竴姝ュ～鍐欓獙璇佺爜 (璁块棶鏋侀獙API锛屽緱鍒皏alidate)

# 2.瀵嗙爜鍔犲瘑姝ラ
pubkey, salt = 鑾峰彇鍏挜鍜岀洂()
鍔犲瘑鍚庣殑瀵嗙爜 = RSA鍏挜鍔犲瘑(pubkey, salt+瀵嗙爜瀛楃涓? # 鐩愰渶瑕佸姞鍦ㄥ瘑鐮佸瓧绗︿覆鍓?base64缂栫爜鍚庣殑瀵嗘枃 = base64缂栫爜(鍔犲瘑鍚庣殑瀵嗙爜)

# 3.寮€濮嬬櫥褰?cookie = 瀵嗙爜鐧诲綍(璐﹀彿, base64缂栫爜鍚庣殑瀵嗘枃, token, challenge, validate)
瀛樺偍cookie(cookie)
SSO鐧诲綍椤甸潰璺宠浆()
```

## web绔瘑鐮佺櫥褰?
### 鑾峰彇鍏挜&鐩?web绔?

> https://passport.bilibili.com/x/passport-login/web/key

*璇锋眰鏂瑰紡锛欸ET*

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁      | 绫诲瀷  | 鍐呭   | 澶囨敞   |
|---------|-----|------|------|
| code    | num | 杩斿洖鍊? | 0锛氭垚鍔?|
| message | str | 閿欒淇℃伅 |      |
| ttl     | num | 1    |      |
| data    | obj | 淇℃伅鏈綋 |      |

`data`瀵硅薄锛?
| 瀛楁   | 绫诲瀷  | 鍐呭     | 澶囨敞                                       |
|------|-----|--------|------------------------------------------|
| hash | str | 瀵嗙爜鐩愬€?  | 鏈夋晥鏃堕棿涓?20s<br />鎭掍负 16 瀛楃<br />闇€瑕佹嫾鎺ュ湪鏄庢枃瀵嗙爜涔嬪墠 |
| key  | str | rsa 鍏挜 | PEM 鏍煎紡缂栫爜<br />鍔犲瘑瀵嗙爜鏃堕渶瑕佷娇鐢?                 |

**绀轰緥锛?*

```shell
curl 'https://passport.bilibili.com/x/passport-login/web/key'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>


```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "hash": "9333681c87fd8d6e",
        "key": "-----BEGIN PUBLIC KEY-----\nMIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDjb4V7EidX/ym28t2ybo0U6t0n\n6p4ej8VjqKHg100va6jkNbNTrLQqMCQCAYtXMXXp2Fwkk6WR+12N9zknLjf+C9sx\n/+l48mjUU8RqahiFD1XT/u2e0m2EN029OhCgkHx3Fc/KlFSIbak93EH/XlYis0w+\nXl69GV6klzgxW6d2xQIDAQAB\n-----END PUBLIC KEY-----\n"
    }
}
```

</details>

### 鐧诲綍鎿嶄綔(web绔?

> https://passport.bilibili.com/x/passport-login/web/login

*璇锋眰鏂瑰紡锛歅OST*

楠岃瘉鐧诲綍鎴愬姛鍚庝細杩涜璁剧疆浠ヤ笅 cookie 椤癸細

`sid` `DedeUserID` `DedeUserID__ckMd5` `SESSDATA` `bili_jct`

**姝ｆ枃鍙傛暟 (application/x-www-form-urlencoded)锛?*

| 鍙傛暟鍚?   | 绫诲瀷 | 鍐呭                   | 蹇呰鎬?| 澶囨敞                                                         |
| --------- | ---- | ---------------------- | ------ | ------------------------------------------------------------ |
| username  | str  | 鐢ㄦ埛鐧诲綍璐﹀彿           | 蹇呰   | 鎵嬫満鍙锋垨閭鍦板潃                                             |
| password  | str  | 鍔犲瘑鍚庣殑甯︾洂瀵嗙爜       | 蹇呰   | base64 鏍煎紡                                                  |
| keep      | num  | 0                      | 蹇呰   |                                                              |
| token     | str  | 鐧诲綍 token             | 蹇呰   | 鍦╗鐢宠 captcha 楠岃瘉鐮乚(readme.md#鐢宠captcha楠岃瘉鐮?鎺ュ彛澶勮幏鍙?|
| challenge | str  | 鏋侀獙 challenge         | 蹇呰   | 鍦╗鐢宠 captcha 楠岃瘉鐮乚(readme.md#鐢宠captcha楠岃瘉鐮?鎺ュ彛澶勮幏鍙?|
| validate  | str  | 鏋侀獙 result            | 蹇呰   | 鏋侀獙楠岃瘉鍚庡緱鍒?                                              |
| seccode   | str  | 鏋侀獙 result +`\|jordan` | 蹇呰   | 鏋侀獙楠岃瘉鍚庡緱鍒?                                              |
| go_url    | str  | 璺宠浆 url               | 闈炲繀瑕?| 榛樿涓?https://www.bilibili.com                              |
| source    | str  | 鐧诲綍鏉ユ簮               | 闈炲繀瑕?| `main_web`锛氱嫭绔嬬櫥褰曢〉<br />`main_mini`锛氬皬绐楃櫥褰?           |

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁      | 绫诲瀷                    | 鍐呭   | 澶囨敞                                                                                                                                                                                              |
|---------|-----------------------|------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| code    | num                   | 杩斿洖鍊? | 0锛氭垚鍔?br />-105锛氶獙璇佺爜閿欒<br />-400锛氳姹傞敊璇?br />-629锛氳处鍙锋垨瀵嗙爜閿欒<br />-653锛氱敤鎴峰悕鎴栧瘑鐮佷笉鑳戒负绌?br />-662锛氭彁浜よ秴鏃?璇烽噸鏂版彁浜?br />-2001锛氱己灏戝繀瑕佺殑鐨勫弬鏁?br />-2100锛氶渶楠岃瘉鎵嬫満鍙锋垨閭<br />2400锛氱櫥褰曠閽ラ敊璇?br />2406锛氶獙璇佹瀬楠屾湇鍔″嚭閿?br />86000锛歊SA瑙ｅ瘑澶辫触 |
| message | str                   | 閿欒淇℃伅 |                                                                                                                                                                                                 |
| data    | 鎴愬姛鏃讹細obj<br />澶辫触鏃讹細null | 鏁版嵁鏈綋 |                                                                                                                                                                                                 |

data 瀵硅薄锛?
| 瀛楁            | 绫诲瀷  | 鍐呭                | 澶囨敞                     |
|---------------|-----|-------------------|------------------------|
| message       | str | 鎵爜鐘舵€佷俊鎭?           | 鑻ユ彁绀?`鏈鐧诲綍鐜瀛樺湪椋庨櫓, 闇€浣跨敤鎵嬫満鍙疯繘琛岄獙璇佹垨缁戝畾`, 鍙傝 [鎵嬫満鍙烽獙璇乚(#鎵嬫満鍙烽獙璇? |
| refresh_token | str | 鍒锋柊`refresh_token` |                        |
| status        | num | 0                 |                        |
| timestamp     | num | 鐧诲綍鏃堕棿              | 鏈櫥褰曚负`0`<br />鏃堕棿鎴?鍗曚綅涓烘绉?|
| url           | str | 娓告垙鍒嗙珯璺ㄥ煙鐧诲綍 url      |                        |

**绀轰緥锛?*

渚嬪鐢ㄦ埛璐﹀彿涓篳12345678900`锛屽姞瀵嗗悗鐨勫瘑鐮佷负`xxx`锛岀櫥褰曠閽ヤ负`aabbccdd`锛屾瀬楠宑hallenge涓篳2333`锛屾瀬楠岀粨鏋滀负`666666`锛岃繘琛岄獙璇佺櫥褰曟搷浣?
```shell
curl 'https://passport.bilibili.com/x/passport-login/web/login' \
--data-urlencode 'username=12345678900' \
--data-urlencode 'password=xxx' \
--data-urlencode 'keep=0' \
--data-urlencode 'source=main_web' \
--data-urlencode 'token=aabbccdd' \
--data-urlencode 'challenge=2333' \
--data-urlencode 'validate=666666' \
--data-urlencode 'seccode=666666|jordan'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>


```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "status": 0,
        "message": "",
        "url": "https://passport.biligame.com/crossDomain?DedeUserID=***&DedeUserID__ckMd5=***&Expires=***&SESSDATA=***&bili_jct=***&gourl=https%3A%2F%2Fwww.bilibili.com%2F",
        "refresh_token": "***",
        "timestamp": 1662452570273
    }
}

```

</details>

**鍝嶅簲澶撮儴鎶撳寘淇℃伅锛?*

鍙槑鏄剧湅瑙佽缃簡鍑犱釜 cookie

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```http
HTTP/1.1 200 OK
Date: Mon, 13 Jul 2020 06:56:00 GMT
Content-Type: application/json;charset=UTF-8
Content-Length: 273
Connection: keep-alive
Server: Apache-Coyote/1.1
Set-Cookie: DedeUserID=***; Domain=.bilibili.com; Expires=Sat, 09-Jan-2021 06:39:43 GMT; Path=/
Set-Cookie: DedeUserID__ckMd5=***; Domain=.bilibili.com; Expires=Sat, 09-Jan-2021 06:39:43 GMT; Path=/
Set-Cookie: SESSDATA=***; Domain=.bilibili.com; Expires=Sat, 09-Jan-2021 06:39:43 GMT; Path=/; HttpOnly
Set-Cookie: bili_jct=***; Domain=.bilibili.com; Expires=Sat, 09-Jan-2021 06:39:43 GMT; Path=/
Content-Security-Policy-Report-Only: default-src 'self' data: *.bilibili.com *.hdslb.com; style-src 'self' 'unsafe-inline' *.hdslb.com static.geetest.com; img-src 'self' data: blob: *.bilibili.com *.hdslb.com http://*.hdslb.com static.geetest.com; script-src 'self' 'unsafe-inline' 'unsafe-eval' *.bilibili.com *.hdslb.com api.geetest.com static.geetest.com; object-src 'self' *.hdslb.com; media-src 'self' *.acgvideo.com http://*.acgvideo.com *.ksyungslb.com; connect-src 'self' data: wss://*.bilibili.com:* *.bilibili.com *.hdslb.com *.biliapi.net *.biliapi.com; frame-ancestors 'self' *.bilibili.com *.biligame.com; report-uri https://security.bilibili.com/csp_report
Expires: Mon, 13 Jul 2020 06:55:59 GMT
Cache-Control: no-cache
X-Cache-Webcdn: BYPASS from jd-sxhz-dx-w-01
```

</details>

## web绔瘑鐮佺櫥褰?鏃х増

浠ヤ笅涓哄瘑鐮佹壂鐮佺櫥褰?API锛屽皻鍙甯歌闂?
### 鑾峰彇鍏挜&鐩?web绔?鏃х増)

> https://passport.bilibili.com/login?act=getkey

*璇锋眰鏂瑰紡锛欸ET*

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁   | 绫诲瀷  | 鍐呭     | 澶囨敞                                       |
|------|-----|--------|------------------------------------------|
| hash | str | 瀵嗙爜鐩愬€?  | 鏈夋晥鏃堕棿涓?20s<br />鎭掍负 16 瀛楃<br />闇€瑕佹嫾鎺ュ湪鏄庢枃瀵嗙爜涔嬪墠 |
| key  | str | rsa 鍏挜 | PEM 鏍煎紡缂栫爜<br />鍔犲瘑瀵嗙爜鏃堕渶瑕佷娇鐢?                 |

**绀轰緥锛?*

```shell
curl 'https://passport.bilibili.com/login?act=getkey'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "hash":"07c6501690c1af85",
    "key":"-----BEGIN PUBLIC KEY-----\nMIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDjb4V7EidX/ym28t2ybo0U6t0n\n6p4ej8VjqKHg100va6jkNbNTrLQqMCQCAYtXMXXp2Fwkk6WR+12N9zknLjf+C9sx\n/+l48mjUU8RqahiFD1XT/u2e0m2EN029OhCgkHx3Fc/KlFSIbak93EH/XlYis0w+\nXl69GV6klzgxW6d2xQIDAQAB\n-----END PUBLIC KEY-----\n"
}
```

</details>

### 鐧诲綍鎿嶄綔(web绔?鏃х増)


> https://passport.bilibili.com/web/login/v2

*璇锋眰鏂瑰紡锛歅OST*

楠岃瘉鐧诲綍鎴愬姛鍚庝細杩涜璁剧疆浠ヤ笅cookie椤癸細

`sid` `DedeUserID` `DedeUserID__ckMd5` `SESSDATA` `bili_jct`

**姝ｆ枃鍙傛暟 锛坅pplication/x-www-form-urlencoded锛夛細**


| 鍙傛暟鍚?     | 绫诲瀷 | 鍐呭                   | 蹇呰鎬?| 澶囨敞                                                         |
| ----------- | ---- | ---------------------- | ------ | ------------------------------------------------------------ |
| captchaType | num  | 6                      | 蹇呰   | 蹇呴』涓篳6`                                                    |
| username    | str  | 鐢ㄦ埛鐧诲綍璐﹀彿           | 蹇呰   | 鎵嬫満鍙锋垨閭鍦板潃                                             |
| password    | str  | 鍔犲瘑鍚庣殑甯︾洂瀵嗙爜       | 蹇呰   | base64 鏍煎紡                                                  |
| keep        | bool | 鏄惁璁颁綇鐧诲綍           | 蹇呰   | `true`锛氳浣忕櫥褰?br />`false`锛氫笉璁颁綇鐧诲綍                    |
| key         | str  | 鐧诲綍 token             | 蹇呰   | 鍦╗鐢宠 captcha 楠岃瘉鐮乚(readme.md#鐢宠captcha楠岃瘉鐮?鎺ュ彛澶勮幏鍙?|
| challenge   | str  | 鏋侀獙 challenge         | 蹇呰   | 鍦╗鐢宠 captcha 楠岃瘉鐮乚(readme.md#鐢宠captcha楠岃瘉鐮?鎺ュ彛澶勮幏鍙?|
| validate    | str  | 鏋侀獙 result            | 蹇呰   | 鏋侀獙楠岃瘉鍚庡緱鍒?                                              |
| seccode     | str  | 鏋侀獙 result +`\|jordan` | 蹇呰   | 鏋侀獙楠岃瘉鍚庡緱鍒?                                              |

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁      | 绫诲瀷  | 鍐呭    | 澶囨敞                                                                                                                                                                              |
|---------|-----|-------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| code    | num | 杩斿洖鍊?  | 0锛氭垚鍔?br />-400锛氳姹傞敊璇?br />-629锛氳处鍙锋垨瀵嗙爜閿欒<br />-653锛氱敤鎴峰悕鎴栧瘑鐮佷笉鑳戒负绌?br />-662锛氭彁浜よ秴鏃?璇烽噸鏂版彁浜?br />-2001锛氱己灏戝繀瑕佺殑鐨勫弬鏁?br />-2100锛氶渶楠岃瘉鎵嬫満鍙锋垨閭<br />2400锛氱櫥褰曠閽ラ敊璇?br />2406锛氶獙璇佹瀬楠屾湇鍔″嚭閿?br />86000锛歊SA瑙ｅ瘑澶辫触 |
| ts      | num | 褰撳墠鏃堕棿鎴?| 鎴愬姛鏃舵棤姝ら」                                                                                                                                                                          |
| message | str | 閿欒淇℃伅  | 榛樿涓?                                                                                                                                                                            |
| data    | obj | 鏁版嵁鏈綋  | 鎴愬姛鏃舵湁姝ら」                                                                                                                                                                          |

`data`瀵硅薄锛?
**鏈櫥褰曟椂锛?*

| 瀛楁          | 绫诲瀷  | 鍐呭           | 澶囨敞  |
|-------------|-----|--------------|-----|
| redirectUrl | str | 娓告垙鍒嗙珯璺ㄥ煙鐧诲綍 url |     |

**宸茬櫥褰曟椂锛?*

| 瀛楁      | 绫诲瀷   | 鍐呭                       | 澶囨敞  |
|---------|------|--------------------------|-----|
| isLogin | bool | true                     |     |
| goUrl   | str  | https://www.bilibili.com |     |

**闇€楠岃瘉鎵嬫満鍙锋垨閭鏃?*

| 瀛楁       | 绫诲瀷  | 鍐呭                       | 澶囨敞         |
|----------|-----|--------------------------|------------|
| mid      | num | 鐢ㄦ埛 mid                   |            |
| tel      | str | 缁戝畾鐨勬墜鏈哄彿                   | 鏄熷彿闅愯棌閮ㄥ垎淇℃伅   |
| email    | str | 缁戝畾鐨勯偖绠?                   | 鏄熷彿闅愯棌閮ㄥ垎淇℃伅   |
| sorce    | num | 0                        | **浣滅敤灏氫笉鏄庣‘** |
| keeptime | num | 1                        | **浣滅敤灏氫笉鏄庣‘** |
| goUrl    | str | https://www.bilibili.com |            |

**绀轰緥锛?*

渚嬪鐢ㄦ埛璐﹀彿涓篳12345678900`锛屽姞瀵嗗悗鐨勫瘑鐮佷负`xxx`锛岀櫥褰曠閽ヤ负`aabbccdd`锛屾瀬楠宑hallenge涓篳2333`锛屾瀬楠岀粨鏋滀负`666666`锛岃繘琛岄獙璇佺櫥褰曟搷浣?
```shell
curl 'https://passport.bilibili.com/web/login/v2' \
--data-urlencode 'captchaType=6' \
--data-urlencode 'username=12345678900' \
--data-urlencode 'password=xxx' \
--data-urlencode 'keep=true' \
--data-urlencode 'token=aabbccdd' \
--data-urlencode 'challenge=2333' \
--data-urlencode 'validate=666666' \
--data-urlencode 'seccode=666666|jordan'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>


```json
{
    "code": 0,
    "data": {
        "redirectUrl": "https://passport.biligame.com/crossDomain?DedeUserID=***&DedeUserID__ckMd5=***&Expires=15551000&SESSDATA=***&bili_jct=***&gourl=https%3A%2F%2Fwww.bilibili.com"
    }
}
```

</details>

**鍝嶅簲澶撮儴鎶撳寘淇℃伅锛?*

鍙槑鏄剧湅瑙佽缃簡鍑犱釜 cookie

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```http
HTTP/1.1 200 OK
Date: Mon, 13 Jul 2020 06:56:00 GMT
Content-Type: application/json;charset=UTF-8
Content-Length: 273
Connection: keep-alive
Server: Apache-Coyote/1.1
Set-Cookie: DedeUserID=***; Domain=.bilibili.com; Expires=Sat, 09-Jan-2021 06:39:43 GMT; Path=/
Set-Cookie: DedeUserID__ckMd5=***; Domain=.bilibili.com; Expires=Sat, 09-Jan-2021 06:39:43 GMT; Path=/
Set-Cookie: SESSDATA=***; Domain=.bilibili.com; Expires=Sat, 09-Jan-2021 06:39:43 GMT; Path=/; HttpOnly
Set-Cookie: bili_jct=***; Domain=.bilibili.com; Expires=Sat, 09-Jan-2021 06:39:43 GMT; Path=/
Content-Security-Policy-Report-Only: default-src 'self' data: *.bilibili.com *.hdslb.com; style-src 'self' 'unsafe-inline' *.hdslb.com static.geetest.com; img-src 'self' data: blob: *.bilibili.com *.hdslb.com http://*.hdslb.com static.geetest.com; script-src 'self' 'unsafe-inline' 'unsafe-eval' *.bilibili.com *.hdslb.com api.geetest.com static.geetest.com; object-src 'self' *.hdslb.com; media-src 'self' *.acgvideo.com http://*.acgvideo.com *.ksyungslb.com; connect-src 'self' data: wss://*.bilibili.com:* *.bilibili.com *.hdslb.com *.biliapi.net *.biliapi.com; frame-ancestors 'self' *.bilibili.com *.biligame.com; report-uri https://security.bilibili.com/csp_report
Expires: Mon, 13 Jul 2020 06:55:59 GMT
Cache-Control: no-cache
X-Cache-Webcdn: BYPASS from jd-sxhz-dx-w-01
```

</details>

## APP绔瘑鐮佺櫥褰?
### 鑾峰彇鍏挜&鐩?APP绔?

>  http://passport.bilibili.com/api/oauth2/getKey

*璇锋眰鏂瑰紡锛歅OST*

閴存潈鏂瑰紡锛歛ppkey

**姝ｆ枃鍙傛暟锛?application/x-www-form-urlencoded 锛夛細**

| 鍙傛暟鍚?   | 绫诲瀷  | 鍐呭    | 蹇呰鎬?    | 澶囨敞  |
|--------|-----|-------|---------|-----|
| appkey | str | APP瀵嗛挜 | APP鏂瑰紡蹇呰 |     |
| sign   | str | APP绛惧悕 | APP鏂瑰紡蹇呰 |     |

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁   | 绫诲瀷  | 鍐呭     | 澶囨敞                                       |
|------|-----|--------|------------------------------------------|
| hash | str | 瀵嗙爜鐩愬€?  | 鏈夋晥鏃堕棿涓?20s<br />鎭掍负 16 瀛楃<br />闇€瑕佹嫾鎺ュ湪鏄庢枃瀵嗙爜涔嬪墠 |
| key  | str | rsa 鍏挜 | PEM 鏍煎紡缂栫爜<br />鍔犲瘑瀵嗙爜鏃堕渶瑕佷娇鐢?                 |

**绀轰緥锛?*

```shell
curl 'https://passport.bilibili.com/api/oauth2/getKey' \
--data-urlencode 'appkey=1d8b6e7d45233436' \
--data-urlencode 'sign=17004c193f688f0b5665c1068e733aff'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "hash": "07c6501690c1af85",
    "key": "-----BEGIN PUBLIC KEY-----\nMIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDjb4V7EidX/ym28t2ybo0U6t0n\n6p4ej8VjqKHg100va6jkNbNTrLQqMCQCAYtXMXXp2Fwkk6WR+12N9zknLjf+C9sx\n/+l48mjUU8RqahiFD1XT/u2e0m2EN029OhCgkHx3Fc/KlFSIbak93EH/XlYis0w+\nXl69GV6klzgxW6d2xQIDAQAB\n-----END PUBLIC KEY-----\n"
}
```

</details>

### 鐧诲綍鎿嶄綔(APP绔?

TODO

## 鐧诲綍瀵嗙爜鐨勫姞瀵嗗疄渚?
浠ヤ笅瀹炰緥浣跨敤 Python 璇█锛屽湪浠讳綍骞冲彴锛坵eb銆丄PP锛変娇鐢ㄥ瘑鐮佺櫥褰曢兘闇€瑕佸涓嬪姞瀵嗘楠?
棣栧厛鍦ㄩ渶鎷夊彇 RSA PubKey 鍜?salt 澶囩敤

```python
import requests

resp = requests.get('https://passport.bilibili.com/x/passport-login/web/key').json()['data']
print('salt =', resp['hash'])
print('PubKey =', resp['key'])
```

`hash`瀛楁涓?salt锛岄暱搴﹀浐瀹氫负 16 瀛楃锛宼imeout 鏃堕棿鍙湁 20s

`key`瀛楁涓?RSA PubKey锛屼负 PEM 鏍煎紡锛屽姞瀵嗛渶瑕佷娇鐢?
```
salt = 9773d106a67e27d6
PubKey = -----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDjb4V7EidX/ym28t2ybo0U6t0n
6p4ej8VjqKHg100va6jkNbNTrLQqMCQCAYtXMXXp2Fwkk6WR+12N9zknLjf+C9sx
/+l48mjUU8RqahiFD1XT/u2e0m2EN029OhCgkHx3Fc/KlFSIbak93EH/XlYis0w+
Xl69GV6klzgxW6d2xQIDAQAB
-----END PUBLIC KEY-----
```

渚嬪鐧诲綍瀵嗙爜涓篳BiShi22332323`锛岀幇鍦ㄥ瀹冭繘琛屽姞鐩愬苟浣跨敤鑾峰彇鐨?PubKey 鍔犲瘑

```python
import rsa
password = 'BiShi22332323'

pubKey = rsa.PublicKey.load_pkcs1_openssl_pem(resp['key']) # 璇诲彇 PEM 瀵嗛挜
encryptedPassword = rsa.encrypt((resp['hash']+password).encode(), pubKey) # 鐩愰渶瑕佸姞鍦ㄦ槑鏂囧瘑鐮佷箣鍓嶏紝涓€骞跺姞瀵?print(encryptedPassword)
```

涓嬮潰灏嗚緭鍑轰竴娈?bytes 鏁版嵁锛?
```
b'}\x9c\xd4\xcd\x88\x92\xa7\xde\x85\xdb\xabm\xd7\xd3\x08\x02@xo\x85\xa4\xe1\x11\xd0o\x80\x03.$\xc8l\xbe\xba;\xfe\xee\xa7(\xf8S\x95\x1e\x9106\xa4\x1d\xcf\x8e\xbe\x8d\x94A\x86s\xf9"\x12\x0c\x135\xbb\xbc\xe1\xde\x1b\x90\t)P\xeb\xa9\x8fXY]\x83\x18\x81f\n:\xdb\xe1\xbe\xe8\x1e\xba\x1c D8d}B\x17\xf9\x8a\xf0i\'1\xa5\xc4\x05&\xaa;n\xf8{\xa02\xffY\xcelU\xd5\xaf\x8aJK\xdc\xf1@\xbc\x93'
```

鎺ヤ笅鏉ラ渶瑕佹妸鍔犲瘑鍚庣殑缁撴灉杩涜 base64 缂栫爜

```python
import base64
b64Password = base64.b64encode(encryptedPassword).decode()
print('result =', b64Password)
```

浠ヤ笅涓烘渶缁堝姞瀵嗙粨鏋滐紝鍙洿鎺ュ悜 API 璇锋眰浣撲紶鍙備互鐧诲綍锛?
鍥犱负 RSA 鍏挜鍔犲瘑鐨?*鏃犳硶瑙ｅ瘑鎬?*锛屾晠鏃犳硶鏈湴楠岃瘉锛屼粎鍙姹?API 楠岃瘉锛堢暐...

```
result = fZzUzYiSp96F26tt19MIAkB4b4Wk4RHQb4ADLiTIbL66O/7upyj4U5UekTA2pB3Pjr6NlEGGc/kiEgwTNbu84d4bkAkpUOupj1hZXYMYgWYKOtvhvugeuhwgRDhkfUIX+YrwaScxpcQFJqo7bvh7oDL/Wc5sVdWvikpL3PFAvJM=
```

浠ヤ笅涓哄瘑鐮佸姞瀵嗙殑Java瀹炵幇锛?
```java
package com.ho.test;

import cn.hutool.core.codec.Base64;

import javax.crypto.Cipher;
import java.security.KeyFactory;
import java.security.PublicKey;
import java.security.spec.X509EncodedKeySpec;

public class Test3 {
  public static void main(String[] args) throws Exception {
    //鐢ㄦ埛瀵嗙爜
    String password = "abcdef";
    //鑾峰彇鍒扮殑璇佷功鍐呭
    String key = "-----BEGIN PUBLIC KEY-----\nMIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDjb4V7EidX/ym28t2ybo0U6t0n\n6p4ej8VjqKHg100va6jkNbNTrLQqMCQCAYtXMXXp2Fwkk6WR+12N9zknLjf+C9sx\n/+l48mjUU8RqahiFD1XT/u2e0m2EN029OhCgkHx3Fc/KlFSIbak93EH/XlYis0w+\nXl69GV6klzgxW6d2xQIDAQAB\n-----END PUBLIC KEY-----\n";
    //鑾峰彇鍒扮殑鐩愬€?    String hash = "bb73382121594c46";
    String[] split = key.strip().split("\n");
    String newKey = split[1] + split[2] + split[3] + split[4];
    //杩涜鍔犲瘑
    KeyFactory keyFactory = KeyFactory.getInstance("RSA");
    X509EncodedKeySpec keySpec = new X509EncodedKeySpec(Base64.decode(newKey));
    PublicKey publicKey = keyFactory.generatePublic(keySpec);
    Cipher cipher = Cipher.getInstance(keyFactory.getAlgorithm());
    cipher.init(Cipher.PUBLIC_KEY, publicKey);
    byte[] bytes = cipher.doFinal((hash + password).getBytes());
    String encode = Base64.encode(bytes);
    System.out.println(encode);
  }
}

```

## 鎵嬫満鍙烽獙璇?
### 绠€杩?
鏈夋椂浣跨敤瀵嗙爜鐧诲綍鏃? 鏃犺浣跨敤缃戦〉绔繕鏄墜鏈虹鎺ュ彛, 鐢变簬 璇锋眰澶寸己澶?璇锋眰棰戠巼楂?璇锋眰IP 绛夊師鍥? 浼氳繑鍥炲涓嬪唴瀹? 姝ゆ椂闇€瑕佽繘琛屾墜鏈哄彿楠岃瘉鎴栫粦瀹?
```json
{
  "code": 0,
  "message": "0",
  "ttl": 1,
  "data": {
    "is_new": false,
    "status": 2,
    "message": "鏈鐧诲綍鐜瀛樺湪椋庨櫓, 闇€浣跨敤鎵嬫満鍙疯繘琛岄獙璇佹垨缁戝畾",
    "url": "https://passport.bilibili.com/h5-app/passport/risk/verify?tmp_token=imtmptk&request_id=imreqid&source=risk",
    "refresh_token": "",
    "timestamp": 0,
    "hint": "",
    "in_reg_audit": 0
  }
}
```

### 鑾峰彇 captcha

> https://passport.bilibili.com/x/safecenter/captcha/pre

*璇锋眰鏂规硶: POST*

**姝ｆ枃鍙傛暟 (application/x-www-form-urlencoded):**

| 鍙傛暟鍚?| 绫诲瀷 | 鍐呭 | 蹇呰鎬?| 澶囨敞 |
| ----- | ---- | ---- | ---- | ---- |
| source | str | risk | 涓嶅繀瑕?|     |

**JSON 鍥炲:**

鏍瑰璞?

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| --- | --- | --- | --- |
| code | num | 杩斿洖鍊?| 0: 鎴愬姛 |
| message | str | 閿欒淇℃伅 | 榛樿涓?0 |
| ttl | num | 1 |  |
| data | obj | 鏁版嵁鏈綋 |  |

`data` 瀵硅薄:

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| --- | --- | --- | --- |
| recaptcha_type | str | 楠岃瘉鐮佺被鍨?| 鐩墠浠?`geetest` |
| recaptcha_token | str | 楠岃瘉鐮?token |  |
| gee_challenge | str | 鏋侀獙 challenge |  |
| gee_gt | str | 鏋侀獙 gt |  |

**绀轰緥:**

```shell
curl -X POST 'https://passport.bilibili.com/x/safecenter/captcha/pre'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥:</summary>

```json
{
  "code": 0,
  "message": "0",
  "ttl": 1,
  "data": {
    "recaptcha_type": "geetest",
    "recaptcha_token": "8a418aa9eebe411599d759fc318d55e1",
    "gee_challenge": "4e5353e7ab9f9aef0c97fa5a5b1ad101",
    "gee_gt": "ac597a4506fee079629df5d8b66dd4fe"
  }
}
```

</details>

### 鍙戦€侀獙璇佺爜

> https://passport.bilibili.com/x/safecenter/common/sms/send

*璇锋眰鏂规硶: POST*

**姝ｆ枃鍙傛暟 (application/x-www-form-urlencoded):**

| 鍙傛暟鍚?| 绫诲瀷 | 鍐呭 | 蹇呰鎬?| 澶囨敞 |
| ------ | - | ---- | ---- | ---- |
| tmp_code| str | url query 涓殑 tmp_code | 蹇呰 | 鍙傝 [绠€杩癩(#绠€杩? 涓?JSON 绀轰緥涓殑 `url` |
| sms_type | str | `loginTelCheck` | 蹇呰 |  |
| recaptcha_token | str | 楠岃瘉鐮?token | 蹇呰 | 鍙傝 [鑾峰彇 captcha](#鑾峰彇-captcha) |
| gee_challenge | str | 鏋侀獙 challenge | 蹇呰 | 鍙傝 [鑾峰彇 captcha](#鑾峰彇-captcha) |
| gee_validate | str | 鏋侀獙 validate | 蹇呰 | 楠岃瘉鍚庤幏寰?|
| gee_seccode | str | 鏋侀獙 seccode | 蹇呰 | 楠岃瘉鍚庤幏寰?|

**JSON鍥炲:**

鏍瑰璞?

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| --- | --- | --- | --- |
| code | num | 杩斿洖鍊?| 0: 鎴愬姛 |
| message | str | 閿欒淇℃伅 | 榛樿涓?0 |
| ttl | num | 1 |  |
| data | obj | 鏁版嵁鏈綋 |  |

`data` 瀵硅薄:

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| --- | --- | -- | - |
| captcha_key | str | 楠岃瘉鐮?key |  |

**绀轰緥:**

鍋囪 `tmp_code` 涓?`imtmptk`,
`recaptcha_token` 涓?`kfc`,
`gee_challenge` 涓?`crazythursday`,
`gee_validate` 涓?`vivo50`,
`gee_seccode` 涓?`vivo50|jordan`

```shell
curl -X POST 'https://passport.bilibili.com/x/safecenter/common/sms/send' \
--data-urlencode 'tmp_code=imtmptk' \
--data-urlencode 'sms_type=loginTelCheck' \
--data-urlencode 'recaptcha_token=kfc' \
--data-urlencode 'gee_challenge=crazythursday' \
--data-urlencode 'gee_validate=vivo50' \
--data-urlencode 'gee_seccode=vivo50|jordan'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥:</summary>

```json
{
  "code": 0,
  "message": "0",
  "ttl": 1,
  "data": {
    "captcha_key": "42403fb08ed2cd97afff14edefbae482"
  }
}
```

</details>

### 楠岃瘉鎵嬫満楠岃瘉鐮?
> https://passport.bilibili.com/x/safecenter/login/tel/verify

*璇锋眰鏂规硶: POST*

**姝ｆ枃鍙傛暟 (application/x-www-form-urlencoded):**

| 鍙傛暟鍚?| 绫诲瀷 | 鍐呭 | 蹇呰鎬?| 澶囨敞 |
| ------ | - | ---- | ---- | ---- |
| tmp_code | str | url query 涓殑 tmp_code | 蹇呰 | 鍙傝 [绠€杩癩(#绠€杩? 涓?JSON 绀轰緥涓殑 `url` |
| captcha_key | str | 楠岃瘉鐮?key | 蹇呰 | 鍙傝 [鍙戦€侀獙璇佺爜](#鍙戦€侀獙璇佺爜) |
| type | str | `loginTelCheck` | 蹇呰 |  |
| code | num | 鎺ユ敹鍒扮殑楠岃瘉鐮?| 蹇呰 |  |
| request_id | str | url query 涓殑 request_id | 蹇呰 | 鍙傝 [绠€杩癩(#绠€杩? 涓?JSON 绀轰緥涓殑 `url` |
| source | str | risk | 蹇呰 |  |

**JSON鍥炲:**

鏍瑰璞?

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| --- | --- | --- | --- |
| code | num | 杩斿洖鍊?| 0: 鎴愬姛 |
| message | str | 閿欒淇℃伅 | 榛樿涓?0 |
| ttl | num | 1 |  |
| data | obj | 鏁版嵁鏈綋 |  |

`data` 瀵硅薄:

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| --- | --- | --- | --- |
| code | str | 浜ゆ崲浠ｇ爜 | 鐢ㄤ簬鍚庨潰 [浜ゆ崲 Cookie](#浜ゆ崲-cookie) |

**绀轰緥:**

鍋囪 `tmp_code` 涓?`imtmptk`,
`captcha_key` 涓?`42403fb08ed2cd97afff14edefbae482`,
`code` 涓?`114514`,
`request_id` 涓?`imreqid`

```shell
curl -X POST 'https://passport.bilibili.com/x/safecenter/login/tel/verify' \
--data-urlencode 'tmp_code=imtmptk' \
--data-urlencode 'captcha_key=42403fb08ed2cd97afff14edefbae482' \
--data-urlencode 'type=loginTelCheck' \
--data-urlencode 'code=114514' \
--data-urlencode'request_id=imreqid' \
--data-urlencode'source=risk'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥:</summary>

```json
{
  "code": 0,
  "message": "0",
  "ttl": 1,
  "data": {
    "code": "6eadf783c55a387b143773282b217682"
  }
}
```

</details>

### 浜ゆ崲 Cookie

> https://passport.bilibili.com/x/passport-login/web/exchange_cookie

*璇锋眰鏂规硶: POST*

**姝ｆ枃鍙傛暟 (application/x-www-form-urlencoded):**

| 鍙傛暟鍚?| 绫诲瀷 | 鍐呭 | 蹇呰鎬?| 澶囨敞 |
| ------ | - | ---- | ---- | ---- |
| source | str | risk | 蹇呰 |  |
| code | str | 浜ゆ崲浠ｇ爜 | 蹇呰 | 鍙傝 [楠岃瘉鎵嬫満楠岃瘉鐮乚(#楠岃瘉鎵嬫満楠岃瘉鐮? |

**JSON鍥炲:**

鏍瑰璞?

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| --- | --- | --- | --- |
| code | num | 杩斿洖鍊?| 0: 鎴愬姛 |
| message | str | 閿欒淇℃伅 | 榛樿涓?0 |
| ttl | num | 1 |  |
| data | obj | 鏁版嵁鏈綋 |  |

`data` 瀵硅薄:

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| --- | --- | - | - |
| url | str | 娓告垙鍒嗙珯璺ㄥ煙鐧诲綍 url |  |
| refresh_token | str | 鍒锋柊 token |  |

**绀轰緥:**

鍋囪 `code` 涓?`6eadf783c55a387b143773282b217682`

```shell
curl -X POST 'https://passport.bilibili.com/x/passport-login/web/exchange_cookie' \
--data-urlencode 'code=6eadf783c55a387b143773282b217682' \
--data-urlencode'source=risk'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥:</summary>

```json
{
  "code": 0,
  "message": "0",
  "ttl": 1,
  "data": {
    "url": "https://passport.biligame.com/x/passport-login/web/crossDomain?DedeUserID=645769214&DedeUserID__ckMd5=653409864bf9e200&Expires=1739265009&SESSDATA=11d97d2a,1739265009,928d7*82CjCKOhDRm5gROpSfgQ7B2axGVMWm5LuwNTkNDK2vjeGl7xvAsfsCINKmczXvO_Z45FsSVlJ1NHdlYlpSei1lYjdqUXRMaUpuRk9GbjVPS0psc3ZTcDFGRjhnNGhIbHRlZ0ZQRWQ1MUlUY2pnQ0lkTVRYNjlabmlUWGxHcVdkV3hrcElpa0ZEZEZRIIEC&bili_jct=3cdee5b84eb48d4f08bcfd57b58cf40b&gourl=https%3A%2F%2Fwww.bilibili.com%2F&first_domain=.bilibili.com",
    "refresh_token": "43de156ad241864640f9d9721656a682"
  }
}
```

</details>

<details>
<summary>鏌ョ湅鍝嶅簲澶撮儴绀轰緥:</summary>

```http
HTTP/2 200 OK
date: Thu, 15 Aug 2024 09:10:09 GMT
content-type: application/json; charset=utf-8
access-control-allow-credentials: true
access-control-allow-methods: GET,POST,PUT,DELETE
access-control-allow-origin: https://passport.bilibili.com
bili-status-code: 0
bili-trace-id: 175262647666bdc5
set-cookie: SESSDATA=xxxxxxx; Path=/; Domain=bilibili.com; Expires=Tue, 11 Feb 2025 09:10:09 GMT; HttpOnly; Secure
set-cookie: bili_jct=xxxxxxxxxxxxxxxxxxxxxxxxx; Path=/; Domain=bilibili.com; Expires=Tue, 11 Feb 2025 09:10:09 GMT
set-cookie: DedeUserID=114514191; Path=/; Domain=bilibili.com; Expires=Tue, 11 Feb 2025 09:10:09 GMT
set-cookie: DedeUserID__ckMd5=0123456789abcdef; Path=/; Domain=bilibili.com; Expires=Tue, 11 Feb 2025 09:10:09 GMT
set-cookie: sid=xxxxxxxx; Path=/; Domain=bilibili.com; Expires=Tue, 11 Feb 2025 09:10:09 GMT
vary: Origin
x-bili-trace-id: 60f0305e2abc511d175262647666bdc5
access-control-allow-headers: Origin,No-Cache,X-Requested-With,If-Modified-Since,Pragma,Last-Modified,Cache-Control,Expires,Content-Type,Access-Control-Allow-Credentials,DNT,X-CustomHeader,Keep-Alive,User-Agent,X-Cache-Webcdn,x-bilibili-key-real-ip,x-backend-bili-real-ip,x-risk-header
cross-origin-resource-policy: cross-origin
access-control-expose-headers: X-Bili-Gaia-Vvoucher,X-Bili-Trace-Id
expires: Thu, 15 Aug 2024 09:10:08 GMT
cache-control: no-cache
x-cache-webcdn: BYPASS from blzone01
content-encoding: br
X-Firefox-Spdy: h2
```

</details>
