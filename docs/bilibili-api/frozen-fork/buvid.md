# 鑾峰彇 buvid3 / buvid4 / b_nut

## 浠呰幏鍙?buvid3

> https://api.bilibili.com/x/web-frontend/getbuvid

*璇锋眰鏂瑰紡: GET*

<!--{
  "gh": [338]
}-->

**JSON鍥炲:**

鏍瑰璞?

| 瀛楁    | 绫诲瀷 | 鍐呭     | 澶囨敞     |
| ------- | ---- | -------- | -------- |
| code    | num  | 杩斿洖鍊?  | 0锛氭垚鍔? |
| data    | obj  | 鏁版嵁鏈綋 |          |

`data`瀵硅薄:

| 瀛楁 | 绫诲瀷 | 鍐呭   | 澶囨敞 |
| ---- | ---- | ------ | ---- |
| buvid | str  | buvid3 | 闇€鎵嬪姩瀛樻斁鑷?cookie 涓?|

**绀轰緥:**

娉? 涓嶈澶嶅埗

```shell
curl -G 'https://api.bilibili.com/x/web-frontend/getbuvid'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥:</summary>

```json
{
  "code": 0,
  "data": {
    "buvid": "54E5EFC1-3C8F-F690-2261-439E4F6A20A979439infoc"
  }
}
```

</details>

## 鎺ュ彛鑾峰彇 buvid3 / buvid4

> https://api.bilibili.com/x/frontend/finger/spi

*璇锋眰鏂瑰紡: GET*

**JSON鍥炲:**

鏍瑰璞?

| 瀛楁    | 绫诲瀷 | 鍐呭     | 澶囨敞     |
| ------- | ---- | -------- | -------- |
| code    | num  | 杩斿洖鍊?  | 0锛氭垚鍔? |
| message | str  | 淇℃伅     | ok: 鎴愬姛 |
| data    | obj  | 鏁版嵁鏈綋 |          |

`data`瀵硅薄:

| 瀛楁 | 绫诲瀷 | 鍐呭   | 澶囨敞 |
| ---- | ---- | ------ | ---- |
| b_3  | str  | buvid3 | 闇€鎵嬪姩瀛樻斁鑷?cookie 涓?|
| b_4  | str  | buvid4 | 鍚屼笂 |

**绀轰緥:**

娉? 寤鸿鑷鐢熸垚, 涓嶈澶嶅埗鏈绀轰緥鐨?buvid3 / buvid4.

```shell
curl -G 'https://api.bilibili.com/x/frontend/finger/spi'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥:</summary>

```json
{
  "code": 0,
  "data": {
    "b_3": "D9656DA8-9BEF-F464-5B72-C4849AFD336379044infoc",
    "b_4": "F6E0FD4B-520C-1902-4F7B-E461D8D1F5AB79044-024072309-666onEZSnlHVPjoRp4kDYg=="
  },
  "message": "ok"
}
```

</details>

## 浠庡搷搴斿ご鑾峰彇 buvid3 / b_nut

浣跨敤 `GET` 鎴?`HEAD` 鏂规硶璇锋眰 `https://www.bilibili.com/`, 涓旇姹傚ご涓?`User-Agent` 瀛楁涓嶅寘鍚?`curl` `python` `awa` 绛夋晱鎰熷瓙瀛楃涓? 涓旂浉鍚?`User-Agent` 瀛楁涓嶅緱鐭椂澶氭璇锋眰. 鍦ㄥ搷搴斿ご涓殑 `Set-Cookie` 瀛楁涓? 鍗冲彲鎵惧埌 `buvid3` 鍜?`b_nut`.

鑻ヤ笉甯︿换浣?Cookie 璇锋眰, 鍒?`b_nut` 涓哄搷搴旂敓鎴愭椂鍒荤殑 UNIX 绉掔骇鏃堕棿鎴?
鑻ヨ姹?Cookie 浠呭甫鏈?`buvid3`, 鍒?`b_nut` 涓?`100`.
鑻ヨ姹?Cookie 浠呭甫鏈?`b_nut`, 鍒欎笌涓嶅甫浠讳綍 Cookie 鐨勫搷搴旂浉鍚?
鑻ヨ姹?Cookie 浠呭甫鏈?`buvid3` 鍜?`b_nut`, 鍒欏搷搴旀棤 `Set-Cookie` 瀛楁.
鑻ヨ姹?Cookie 甯︽湁鍏朵粬瀛楁, 鏃犲奖鍝?

**绀轰緥:**

```shell
curl -I "https://www.bilibili.com/" -A "awa"
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥:</summary>

```http
HTTP/2 200 
date: Fri, 26 Jul 2024 06:38:43 GMT
content-type: text/html; charset=utf-8
support: nantianmen
set-cookie: buvid3=805E4894-96A2-0684-6F00-C6EA1FFB911023315infoc; path=/; expires=Sat, 26 Jul 2025 06:38:43 GMT; domain=.bilibili.com
set-cookie: b_nut=1721975923; path=/; expires=Sat, 26 Jul 2025 06:38:43 GMT; domain=.bilibili.com
vary: Origin,Accept-Encoding
idc: shjd
expires: Fri, 26 Jul 2024 06:38:42 GMT
cache-control: no-cache
x-cache-webcdn: MISS from blzone01
x-cache-time: 0
x-save-date: Fri, 26 Jul 2024 06:38:43 GMT
```

</details>
