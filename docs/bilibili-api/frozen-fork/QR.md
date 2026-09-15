# 浜岀淮鐮佺櫥褰?
<img src="../../../assets/img/2233login.png"/>

## 鎵爜鐧诲綍娴佺▼(浼唬鐮?

```python
token, url = 鐢宠浜岀淮鐮?)
鐢熸垚浜岀淮鐮?url) # 绛夊緟瀹㈡埛绔壂鐮?while True:
    status, cookie = 鎵爜鐧诲綍(token)
    match status:
        case 鏈壂鎻?
            continue
        case 浜岀淮鐮佽秴鏃?| 浜岀淮鐮佸け鏁?
            鎻愮ず('浜岀淮鐮佸け鏁堟垨瓒呮椂') # 闇€瑕佺敤鎴烽噸鏂版搷浣?            break
        case 宸叉壂鎻忔湭纭:
            鎻愮ず('鎵弿鎴愬姛')
        case 鐧诲綍鎴愬姛:
            鎻愮ず('鎵弿鎴愬姛')
            瀛樺偍cookie(cookie)
            SSO鐧诲綍椤甸潰璺宠浆()
            break
```

## web绔壂鐮佺櫥褰?
### 鐢宠浜岀淮鐮?web绔?

> https://passport.bilibili.com/x/passport-login/web/qrcode/generate

*璇锋眰鏂瑰紡锛欸ET*

瀵嗛挜瓒呮椂涓?80绉?
**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁      | 绫诲瀷  | 鍐呭   | 澶囨敞   |
|---------|-----|------|------|
| code    | num | 杩斿洖鍊? | 0锛氭垚鍔?|
| message | str | 閿欒淇℃伅 |      |
| ttl     | num | 1    |      |
| data    | obj | 淇℃伅鏈綋 |      |

`data`瀵硅薄锛?
| 瀛楁         | 绫诲瀷  | 鍐呭               | 澶囨敞     |
|------------|-----|------------------|--------|
| url        | str | 浜岀淮鐮佸唴瀹?(鐧诲綍椤甸潰 url) |        |
| qrcode_key | str | 鎵爜鐧诲綍绉橀挜           | 鎭掍负32瀛楃 |

**绀轰緥锛?*

`url`涓殑鍊肩敓鎴愪簩缁寸爜锛岀瓑寰呮墜鏈哄鎴风鎵弿锛屽苟灏哷qrcode_key`淇濆瓨澶囩敤

```shell
curl 'https://passport.bilibili.com/x/passport-login/web/qrcode/generate'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "url": "https://passport.bilibili.com/h5-app/passport/login/scan?navhide=1\u0026qrcode_key=8587cf8106a0b863c46d6bab913537f6\u0026from=",
        "qrcode_key": "8587cf8106a0b863c46d6bab913537f6"
    }
}
```

</details>

### 鎵爜鐧诲綍(web绔?

> https://passport.bilibili.com/x/passport-login/web/qrcode/poll

*璇锋眰鏂瑰紡锛欸ET*

**url鍙傛暟锛?*

| 鍙傛暟鍚?       | 绫诲瀷  | 鍐呭     | 蹇呰鎬?| 澶囨敞  |
|------------|-----|--------|-----|-----|
| qrcode_key | str | 鎵爜鐧诲綍绉橀挜 | 蹇呰 |     |


瀵嗛挜瓒呮椂涓?80绉?
楠岃瘉鐧诲綍鎴愬姛鍚庝細杩涜璁剧疆浠ヤ笅cookie椤癸細

`DedeUserID` `DedeUserID__ckMd5` `SESSDATA` `bili_jct`

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁      | 绫诲瀷  | 鍐呭   | 澶囨敞   |
|---------|-----|------|------|
| code    | num | 杩斿洖鍊? | 0锛氭垚鍔?|
| message | str | 閿欒淇℃伅 |      |
| data    | obj | 淇℃伅鏈綋 |      |

data 瀵硅薄锛?
| 瀛楁            | 绫诲瀷  | 鍐呭                                                             | 澶囨敞                     |
|---------------|-----|----------------------------------------------------------------|------------------------|
| url           | str | 娓告垙鍒嗙珯璺ㄥ煙鐧诲綍 url                                                   | 鏈櫥褰曚负绌?                 |
| refresh_token | str | 鍒锋柊`refresh_token`                                              | 鏈櫥褰曚负绌?                 |
| timestamp     | num | 鐧诲綍鏃堕棿                                                           | 鏈櫥褰曚负`0`<br />鏃堕棿鎴?鍗曚綅涓烘绉?|
| code          | num | 0锛氭壂鐮佺櫥褰曟垚鍔?br />86038锛氫簩缁寸爜宸插け鏁?br />86090锛氫簩缁寸爜宸叉壂鐮佹湭纭<br />86101锛氭湭鎵爜 |                        |
| message       | str | 鎵爜鐘舵€佷俊鎭?                                                        |                        |

**绀轰緥锛?*

浣跨敤鎵弿绉橀挜`c3bd5286a2b40a822f5f60e9bf3f602e`鐧诲綍

```shell
curl -G "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"\
--data-urlencode 'qrcode_key=c3bd5286a2b40a822f5f60e9bf3f602e' \
-c 'cookie.txt'
```

褰撳瘑閽ユ纭椂浣嗘湭鎵弿鏃禶code`涓篳86101`

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>


```json
{
  "code": 0,
  "message": "0",
  "ttl": 1,
  "data": {
    "url": "",
    "refresh_token": "",
    "timestamp": 0,
    "code": 86101,
    "message": "鏈壂鐮?
  }
}
```

</details>

鎵弿鎴愬姛浣嗘墜鏈虹鏈‘璁ゆ椂`code`涓篳86090`

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "url": "",
        "refresh_token": "",
        "timestamp": 0,
        "code": 86090,
        "message": "浜岀淮鐮佸凡鎵爜鏈‘璁?
    }
}
```

</details>

鎵弿鎴愬姛鎵嬫満绔‘璁ょ櫥褰曞悗锛宍code`涓篳0`锛屽苟鍚戞祻瑙堝櫒鍐欏叆cookie

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "url": "https://passport.biligame.com/crossDomain?DedeUserID=***\u0026DedeUserID__ckMd5=***\u0026Expires=***\u0026SESSDATA=***\u0026bili_jct=***\u0026gourl=https%3A%2F%2Fpassport.bilibili.com",
        "refresh_token": "***",
        "timestamp": 1662363009601,
        "code": 0,
        "message": ""
    }
}
```

</details>

**鍝嶅簲澶撮儴鎶撳寘淇℃伅锛?*

鍙槑鏄剧湅瑙佽缃簡鍑犱釜cookie

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```http
HTTP/1.1 200 OK
Date: Mon, 05 Sep 2022 07:30:09 GMT
Expires: Mon, 05 Sep 2022 07:30:08 GMT
Cache-control: no-cache
Content-encoding: br
Content-type: application/json; charset=utf-8
bili-status-code: 0
bili-trace-id: 0d23fe044a6315a5
set-cookie: SESSDATA=***; Path=/; Domain=bilibili.com; Expires=Sat, 04 Mar 2023 07:30:09 GMT; HttpOnly; Secure
set-cookie: bili_jct=***; Path=/; Domain=bilibili.com; Expires=Sat, 04 Mar 2023 07:30:09 GMT
set-cookie: DedeUserID=***; Path=/; Domain=bilibili.com; Expires=Sat, 04 Mar 2023 07:30:09 GMT
set-cookie: DedeUserID__ckMd5=***; Path=/; Domain=bilibili.com; Expires=Sat, 04 Mar 2023 07:30:09 GMT
set-cookie: sid=***; Path=/; Domain=bilibili.com; Expires=Sat, 04 Mar 2023 07:30:09 GMT
x-bili-trace-id: 2fbd8abd97dbd4db0d23fe044a6315a5
x-cache-webcdn: BYPASS from blzone02
```

</details>

浜岀淮鐮佸け鏁堟椂`code`涓篳86038`

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
      "url": "",
      "refresh_token": "",
      "timestamp": 0,
      "code": 86038,
      "message": "浜岀淮鐮佸凡澶辨晥"
    }
}
```

</details>

## web绔壂鐮佺櫥褰?鏃х増

浠ヤ笅涓烘棫鐗堟壂鐮佺櫥褰?API锛岄儴鍒嗗彲姝ｅ父璁块棶

### 鐢宠浜岀淮鐮?web绔?鏃х増)

> https://passport.bilibili.com/qrcode/getLoginUrl

*璇锋眰鏂瑰紡锛欸ET*

瀵嗛挜瓒呮椂涓?80绉?
**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁     | 绫诲瀷   | 鍐呭   | 澶囨敞     |
|--------|------|------|--------|
| code   | num  | 杩斿洖鍊? | 0锛氭垚鍔?  |
| status | bool | true | 浣滅敤灏氫笉鏄庣‘ |
| ts     | num  | 璇锋眰鏃堕棿 | 鏃堕棿鎴?   |
| data   | obj  | 淇℃伅鏈綋 |        |

`data`瀵硅薄锛?
| 瀛楁       | 绫诲瀷  | 鍐呭               | 澶囨敞     |
|----------|-----|------------------|--------|
| url      | str | 浜岀淮鐮佸唴瀹?(鐧诲綍椤甸潰 url) |        |
| oauthKey | str | 鎵爜鐧诲綍绉橀挜           | 鎭掍负32瀛楃 |

**绀轰緥锛?*

`url`涓殑鍊肩敓鎴愪簩缁寸爜锛岀瓑寰呮墜鏈哄鎴风鎵弿锛屽苟灏哷oauthKey`淇濆瓨澶囩敤

```shell
curl 'https://passport.bilibili.com/qrcode/getLoginUrl'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
	"code": 0,
	"status": true,
	"ts": 1583314311,
	"data": {
		"url": "https://passport.bilibili.com/qrcode/h5/login?oauthKey=c3bd5286a2b40a822f5f60e9bf3f602e",
		"oauthKey": "c3bd5286a2b40a822f5f60e9bf3f602e"
	}
}
```

</details>

### 鎵爜鐧诲綍(web绔?鏃х増)

**鎺ュ彛宸插け鏁堬紝璇锋眰缁撴灉濮嬬粓涓?`{ code: 20000, message: '璇ョ増鏈凡涓嶆敮鎸佸綋鍓嶅姛鑳斤紝璇峰崌绾ф柊鐗堟湰锛? }`**

> ~~https://passport.bilibili.com/qrcode/getLoginInfo~~

*璇锋眰鏂瑰紡锛歅OST*

<details>
<summary>鍐呭宸茶繃鏃讹細</summary>

瀵嗛挜瓒呮椂涓?80绉?
楠岃瘉鐧诲綍鎴愬姛鍚庝細杩涜璁剧疆浠ヤ笅cookie椤癸細

`DedeUserID` `DedeUserID__ckMd5` `SESSDATA` `bili_jct`

**姝ｆ枃鍙傛暟锛?application/x-www-form-urlencoded 锛夛細**

| 鍙傛暟鍚?     | 绫诲瀷  | 鍐呭     | 蹇呰鎬?| 澶囨敞                         |
|----------|-----|--------|-----|----------------------------|
| oauthKey | str | 鎵爜鐧诲綍绉橀挜 | 蹇呰  |                            |
| gourl    | str | 璺宠浆url  | 闈炲繀瑕?| 榛樿涓篽ttp://www.bilibili.com |

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁      | 绫诲瀷                   | 鍐呭                        | 澶囨敞                                                      |
|---------|----------------------|---------------------------|---------------------------------------------------------|
| code    | num                  | 杩斿洖鍊?                      | 0锛氭垚鍔燂紝<br />20000锛氳鐗堟湰宸蹭笉鏀寔褰撳墠鍔熻兘锛岃鍗囩骇鏂扮増鏈紒 |
| message | str                  |                           | 姝ｇ‘鏃?                                                    |
| ts      | num                  | 鎵爜鏃堕棿                      | 閿欒鏃?                                                    |
| status  | bool                 | 鎵爜鏄惁鎴愬姛                    | true锛氭垚鍔?br />false锛氭湭鎴愬姛                                  |
| data    | 姝ｇ‘鏃讹細obj<br />閿欒鏃讹細num | 姝ｇ‘鏃讹細娓告垙鍒嗙珯url<br />閿欒鏃讹細閿欒浠ｇ爜 | 鏈垚鍔熸椂锛?br />-1锛氬瘑閽ラ敊璇?br />-2锛氬瘑閽ヨ秴鏃?br />-4锛氭湭鎵弿<br />-5锛氭湭纭 |

data 瀵硅薄锛?
| 瀛楁  | 绫诲瀷  | 鍐呭           | 澶囨敞  |
|-----|-----|--------------|-----|
| url | str | 娓告垙鍒嗙珯璺ㄥ煙鐧诲綍 url |     |

**绀轰緥锛?*

浣跨敤鎵弿绉橀挜`c3bd5286a2b40a822f5f60e9bf3f602e`鐧诲綍

```shell
curl "https://passport.bilibili.com/qrcode/getLoginInfo"\
--data-urlencode 'oauthKey=c3bd5286a2b40a822f5f60e9bf3f602e' \
-c 'cookie.txt'
```

褰撳瘑閽ユ纭椂浣嗘湭鎵弿鏃禶status`涓篳false`锛宍data`涓篳-4`

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "status":false,
    "data":-4,
    "message":"Can't scan~"
}
```

</details>

鎵弿鎴愬姛浣嗘墜鏈虹鏈‘璁ゆ椂`status`涓篳false`锛宍data`涓篳-5`

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "status":false,
    "data":-5,
    "message":"Can't confirm~"
}
```

</details>

鎵弿鎴愬姛鎵嬫満绔‘璁ょ櫥褰曞悗锛宍status`涓篳true`锛宍data`涓哄璞★紝骞跺悜娴忚鍣ㄥ啓鍏ookie

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
	"code": 0,
	"status": true,
	"ts": 1583315474,
	"data": {
		"url": "https://passport.biligame.com/crossDomain?DedeUserID=***&DedeUserID__ckMd5=***&Expires=***&SESSDATA=***&bili_jct=***&gourl=http%3A%2F%2Fwww.bilibili.com"
	}
}
```

</details>

**鍝嶅簲澶撮儴鎶撳寘淇℃伅锛?*

鍙槑鏄剧湅瑙佽缃簡鍑犱釜cookie

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```http
HTTP/1.1 200 OK
Date: Wed, 04 Mar 2020 10:36:37 GMT
Content-Type: application/json;charset=UTF-8
Transfer-Encoding: chunked
Connection: keep-alive
Server: Apache-Coyote/1.1
Set-Cookie: sid=***; Domain=.bilibili.com; Expires=Thu, 04-Mar-2021 10:36:37 GMT; Path=/
Set-Cookie: DedeUserID=***; Domain=.bilibili.com; Expires=Mon, 31-Aug-2020 10:19:57 GMT; Path=/
Set-Cookie: DedeUserID__ckMd5=***; Domain=.bilibili.com; Expires=Mon, 31-Aug-2020 10:19:57 GMT; Path=/
Set-Cookie: SESSDATA=***; Domain=.bilibili.com; Expires=Mon, 31-Aug-2020 10:19:57 GMT; Path=/; HttpOnly
Set-Cookie: bili_jct=***; Domain=.bilibili.com; Expires=Mon, 31-Aug-2020 10:19:57 GMT; Path=/
Expires: Wed, 04 Mar 2020 10:36:36 GMT
Cache-Control: no-cache
X-Cache-Webcdn: BYPASS from ks-sxhz-dx-w-01
```

</details>

</details>

## TV绔壂鐮佺櫥褰?
### 鐢宠浜岀淮鐮?TV绔?

> https://passport.snm0516.aisee.tv/x/passport-tv-login/qrcode/auth_code
> 
> https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code

*璇锋眰鏂瑰紡锛歅OST*

閴存潈鏂瑰紡锛歛ppkey

瀵嗛挜瓒呮椂涓?80绉?
鏈帴鍙ｅ彲鐢宠鐢ㄤ簬TV绔疉PP鏂瑰紡鐧诲綍鐨刞access_key`

**姝ｆ枃鍙傛暟锛?application/x-www-form-urlencoded 锛夛細**

| 鍙傛暟鍚?  | 绫诲瀷 | 鍐呭       | 蹇呰鎬?      | 澶囨敞                       |
| -------- | ---- | ---------- | ------------ | -------------------------- |
| appkey   | str  | APP 瀵嗛挜   | APP 鏂瑰紡蹇呰 | [鍙敤](#appkey-鍙敤鍒楄〃)     |
| local_id | num  | TV 绔?id   | TV 绔繀瑕?   | 鍙负`0`                    |
| ts       | num  | 褰撳墠鏃堕棿鎴?| APP 鏂瑰紡蹇呰 |                            |
| sign     | str  | APP 绛惧悕   | APP 鏂瑰紡蹇呰 |                            |
| mobi_app | str  | 骞冲彴鏍囪瘑   | 闈炲繀瑕?      | 浼氳鎷兼帴鍒拌繑鍥炵殑 url query |

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁      | 绫诲瀷  | 鍐呭   | 澶囨敞                                    |
|---------|-----|------|---------------------------------------|
| code    | num | 杩斿洖鍊? | 0锛氭垚鍔?br />-3锛欰PI鏍￠獙瀵嗗寵閿欒<br />-400锛氳姹傞敊璇?|
| message | str | 閿欒淇℃伅 | 榛樿涓?                                  |
| ttl     | num | 1    |                                       |
| data    | obj | 淇℃伅鏈綋 |                                       |

`data`瀵硅薄锛?
| 瀛楁      | 绫诲瀷 | 鍐呭           | 澶囨敞         |
| --------- | ---- | -------------- | ------------ |
| url       | str  | 浜岀淮鐮佸唴瀹?url |              |
| auth_code | str  | 鎵爜鐧诲綍绉橀挜   | 鎭掍负 32 瀛楃 |

**绀轰緥锛?*

```shell
curl 'https://passport.snm0516.aisee.tv/x/passport-tv-login/qrcode/auth_code' \
--data-urlencode 'appkey=4409e2ce8ffd12b8' \
--data-urlencode 'local_id=0' \
--data-urlencode 'ts=0' \
--data-urlencode 'sign=e134154ed6add881d28fbdf68653cd9c'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
  "code": 0,
  "message": "0",
  "ttl": 1,
  "data": {
    "url": "https://passport.bilibili.com/x/passport-tv-login/h5/qrcode/auth?auth_code=0eeb635a64526709d70cb4c854a3b001",
    "auth_code": "0eeb635a64526709d70cb4c854a3b001"
  }
}
```

</details>

### 鎵爜鐧诲綍(TV绔?

> https://passport.snm0516.aisee.tv/x/passport-tv-login/qrcode/poll
> 
> https://passport.bilibili.com/x/passport-tv-login/qrcode/poll

*璇锋眰鏂瑰紡锛歅OST*

閴存潈鏂瑰紡锛歛ppkey

瀵嗛挜瓒呮椂涓?80绉?
楠岃瘉鐧诲綍鎴愬姛鍚庝細杩斿洖鍙敤浜嶢PP鏂瑰紡鐧诲綍鐨刞access_key`浠ュ強`refresh_token`

**姝ｆ枃鍙傛暟 (application/x-www-form-urlencoded)锛?*

| 鍙傛暟鍚?      | 绫诲瀷  | 鍐呭    | 蹇呰鎬?    | 澶囨敞                    |
|-----------|-----|-------|---------|-----------------------|
| appkey    | str | APP瀵嗛挜 | APP鏂瑰紡蹇呰 |[鍙敤](#appkey-鍙敤鍒楄〃)  |
| auth_code | str | 鎵爜绉橀挜  | 蹇呰      |                       |
| local_id  | num | TV绔痠d | TV绔繀瑕?  | 鍙负0                   |
| ts        | num | 褰撳墠鏃堕棿鎴?| APP鏂瑰紡蹇呰 |                       |
| sign      | str | APP绛惧悕 | APP鏂瑰紡蹇呰 |                       |

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁      | 绫诲瀷                    | 鍐呭   | 澶囨敞                                                                                                           |
|---------|-----------------------|------|--------------------------------------------------------------------------------------------------------------|
| code    | num                   | 杩斿洖鍊? | 0锛氭垚鍔?br />-3锛欰PI鏍￠獙瀵嗗寵閿欒<br />-400锛氳姹傞敊璇?br/>-404锛氬暐閮芥湪鏈?br />86038锛氫簩缁寸爜宸插け鏁?br />86039锛氫簩缁寸爜灏氭湭纭<br/>86090锛氫簩缁寸爜宸叉壂鐮佹湭纭 |
| message | str                   | 閿欒淇℃伅 | 榛樿涓?                                                                                                         |
| ttl     | num                   | 1    |                                                                                                              |
| data    | 鏈夋晥鏃讹細obj<br />鏃犳晥鏃讹細null | 淇℃伅鏈綋 |                                                                                                              |

`data`瀵硅薄锛?
| 瀛楁            | 绫诲瀷  | 鍐呭         | 澶囨敞                  |
|---------------|-----|------------|---------------------|
| mid           | num | 鐧诲綍鐢ㄦ埛mid    |                     |
| access_token  | str | APP鐧诲綍Token |                     |
| refresh_token | str | APP鍒锋柊Token |                     |
| expires_in    | num | 鏈夋晥鏃堕棿       | 榛樿锛?5552000绉掞紝绛変簬180澶?|

**绀轰緥锛?*

浣跨敤鎵弿绉橀挜`6214464b3025541abf6f654cf7569a01`杩涜楠岃瘉鐧诲綍

```shell
curl 'https://passport.snm0516.aisee.tv/x/passport-tv-login/qrcode/poll' \
--data-urlencode 'appkey=4409e2ce8ffd12b8' \
--data-urlencode 'auth_code=6214464b3025541abf6f654cf7569a01' \
--data-urlencode 'local_id=0' \
--data-urlencode 'ts=0' \
--data-urlencode 'sign=87de3d0fee7c3f4facd244537238914e' 
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
  "code": 0,
  "message": "0",
  "ttl": 1,
  "data": {
    "is_new": false,
    "mid": 10086,
    "access_token": "********************************",
    "refresh_token": "********************************",
    "expires_in": 15552000,
    "token_info": {
      "mid": 10086,
      "access_token": "********************************",
      "refresh_token": "********************************",
      "expires_in": 15552000
    },
    "cookie_info": {
      "cookies": [
        {
          "name": "SESSDATA",
          "value": "********************************",
          "http_only": 1,
          "expires": 1679988973,
          "secure": 0
        },
        {
          "name": "bili_jct",
          "value": "********************************",
          "http_only": 0,
          "expires": 1679988973,
          "secure": 0
        },
        {
          "name": "DedeUserID",
          "value": "*******",
          "http_only": 0,
          "expires": 1679988973,
          "secure": 0
        },
        {
          "name": "DedeUserID__ckMd5",
          "value": "****************",
          "http_only": 0,
          "expires": 1679988973,
          "secure": 0
        },
        {
          "name": "sid",
          "value": "********",
          "http_only": 0,
          "expires": 1679988973,
          "secure": 0
        }
      ],
      "domains": [
        ".bilibili.com",
        ".biligame.com",
        ".bigfun.cn",
        ".bigfunapp.cn",
        ".dreamcast.hk"
      ]
    },
    "sso": [
      "https://passport.bilibili.com/api/v2/sso",
      "https://passport.biligame.com/api/v2/sso",
      "https://passport.bigfunapp.cn/api/v2/sso"
    ]
  }
}
```

</details>

### appkey 鍙敤鍒楄〃

**浠呰鐩?[docs/misc/sign/APPKey](../../misc/sign/APPKey.md) 涓寘鍚殑 appkey**

|      APPKEY      |              APPSEC              | platform |      APP绫诲瀷       | neuronAppId | mobi_app<sup>2</sup> |                    澶囨敞                    |
| :--------------: | :------------------------------: | :------------------: | :----------------: | :---------------------: | :------------------: | :----------------------------------------: |
| 783bbb7264451d82 | 2653583c8873dea268ab9386918b1d65 |      `android`       |        绮夌増        |           `1`           |      `android`       |    浠呰幏鍙栫敤鎴蜂俊鎭椂浣跨敤(7.X鍙婃洿鏂扮増鏈?     |
| 8d23902c1688a798 | 710f0212e62bd499b8d3ac6e1db9302a |      `android`       | AndroidBiliThings  |            ?            |          ?           |                                            |
| bca7e84c2d947ac6 | 60698ba2f68e01ce44738920a0ffe768 |          ?           |       login        |            -            |          ?           |                                            |
| 27eb53fc9058f8c3 | c2ed53a74eeefe3cf99fbd01d8c9c375 |     `web`/`ios`?     |         -          |            -            |          -           |               绗笁鏂规巿鏉冧娇鐢?              |
| 4409e2ce8ffd12b8 | 59b43e04ad6965f34319062b478f83dd |      `android`       | 浜戣鍚皬鐢佃(TV鐗? |          `9`?           |  `android_tv_yst`?   |                                            |
| dfca71928277209b | b5475a8825547a4fc26c7d518eaaa02e |      `android`       |       HD 鐗?       |           `5`           |     `android_hd`     |                                            |

**娉ㄦ剰锛?*

閫氳繃鏌愪竴缁?APPKEY/APPSEC 鑾峰彇鍒扮殑 access_token锛屽綋鎺ュ彛闇€瑕?`sign` 绛惧悕鏃朵篃鍙兘浣跨敤璇ョ粍 APPKEY/APPSEC锛屽惁鍒欏嚭鐜?`{ code: -663, message: '閴存潈澶辫触锛岃鑱旂郴璐﹀彿缁?, ttl: 1 }` 閿欒銆?
**渚嬪锛?*

`783bbb7264451d82`/`2653583c8873dea268ab9386918b1d65` 鑾峰彇鍒扮殑 access_token 鍙厤鍚?`1d8b6e7d45233436`/`560c52ccd288fed045859ed18bffd973` 浣跨敤銆?
