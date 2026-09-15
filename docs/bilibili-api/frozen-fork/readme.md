# 鐧诲綍鎿嶄綔

浜烘満楠岃瘉鏂瑰紡鐧诲綍鍖呭惈**璐﹀彿瀵嗙爜鐧诲綍**涓?*鎵嬫満鐭俊楠岃瘉鐮佺櫥褰?*

**娉細鎵爜鐧诲綍**涓嶉渶瑕佽繘琛?*浜烘満楠岃瘉**锛屾晠**涓嶄娇鐢?*浠ヤ笅鎺ュ彛

## 鎵爜鐧诲綍

- [鎵爜鐧诲綍](QR.md)

## 楠岃瘉鐧诲綍

浜烘満楠岃瘉娴佺▼锛?
1. 璇锋眰楠岃瘉鐮佸弬鏁帮紝寰楀埌鐧诲綍瀵嗛挜`key`涓庢瀬楠宨d`gt`鍜屾瀬楠孠EY`challenge`
2. 杩涜婊戝姩or鐐瑰嚮楠岃瘉
3. 杩斿洖楠岃瘉缁撴灉`validate`涓巂seccode`锛岃繘琛岀煭淇℃垨瀵嗙爜鐧诲綍

### 鐢宠captcha楠岃瘉鐮?
> https://passport.bilibili.com/x/passport-login/captcha?source=main_web

*璇锋眰鏂瑰紡锛欸ET*

娉? 鍙﹀鍙傝 [瀵嗙爜鐧诲綍-鎵嬫満鍙烽獙璇?鑾峰彇 captcha](password.md#鑾峰彇-captcha)

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁   | 绫诲瀷 | 鍐呭     | 澶囨敞         |
| ------ | ---- | -------- | --------- |
| code   | num  | 杩斿洖鍊?  | 0锛氭垚鍔?    |
| message   | str  | 杩斿洖淇℃伅   | |
| ttl   | num  | 1 |  |
| data   | obj  | 淇℃伅鏈綋 | |

`data`瀵硅薄锛?
| 瀛楁      | 绫诲瀷  | 鍐呭     | 澶囨敞     |
| -------- | ----- | ------ | -------- |
| geetest   | obj   | 鏋侀獙captcha鏁版嵁 |  |
| tencent   | obj   | (?) | **浣滅敤灏氫笉鏄庣‘** |
| token    | str   | 鐧诲綍 API token | 涓?captcha 鏃犲叧锛屼笌鐧诲綍鎺ュ彛鏈夊叧 |
| type     | str   | 楠岃瘉鏂瑰紡 | 鐢ㄤ簬鍒ゆ柇浣跨敤鍝竴绉嶉獙璇佹柟寮忥紝鐩墠鎵€瑙佸彧鏈夋瀬楠?br />geetest锛氭瀬楠?|

`geetest`瀵硅薄锛?
| 瀛楁      | 绫诲瀷  | 鍐呭     | 澶囨敞     |
| -------- | ----- | ------ | -------- |
| gt | str | 鏋侀獙id | 涓€鑸负鍥哄畾鍊?|
| challenge | str | 鏋侀獙KEY | 鐢盉绔欏悗绔骇鐢熺敤浜庝汉鏈洪獙璇?|

**绀轰緥锛?*

```shell
curl 'https://passport.bilibili.com/x/passport-login/captcha?source=main_web'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "type": "geetest",
        "token": "00fbe75cc2864ba0af969231f193a974",
        "geetest": {
            "challenge": "a57d9be17505d4a15ed84694c48fbf74",
            "gt": "ac597a4506fee079629df5d8b66dd4fe"
        },
        "tencent": {
            "appid": ""
        }
    }
}
```

</details>

### 鐢宠captcha楠岃瘉鐮?(鏃х増)

> http://passport.bilibili.com/web/captcha/combine

*璇锋眰鏂瑰紡锛欸ET*

璇ユ帴鍙ｆ浘浠庢枃妗ｇЩ闄よ繃, 缁忚繃娴嬭瘯浠嶅彲姝ｅ父浣跨敤

**URL鍙傛暟:**

| 鍙傛暟鍚?| 绫诲瀷 | 鍐呭         | 蹇呰鎬?| 澶囨敞 |
| ------ | ---- | ------------ | ------ | ---- |
| plat   | num  | 骞冲彴绫诲瀷     | 蹇呰   | 榛樿涓?6 |

**JSON鍥炲:**

鏍瑰璞★細

| 瀛楁   | 绫诲瀷 | 鍐呭     | 澶囨敞         |
| ------ | ---- | -------- | --------- |
| code   | num  | 杩斿洖鍊?  | 0锛氭垚鍔?    |
| data   | obj  | 淇℃伅鏈綋 | |

`data`瀵硅薄锛?
| 瀛楁      | 绫诲瀷  | 鍐呭     | 澶囨敞     |
| -------- | ----- | ------ | -------- |
| result   | obj   | 濂椾簡涓▋ |  |
| type     | num   | 1      | **浣滅敤灏氫笉鏄庣‘** |

`result`瀵硅薄锛?
| 瀛楁      | 绫诲瀷  | 鍐呭     | 澶囨敞     |
| -------- | ----- | ------ | -------- |
| success | num | 1 | **浣滅敤灏氫笉鏄庣‘** |
| gt | str | 鏋侀獙id | 涓€鑸负鍥哄畾鍊?|
| challenge | str | 鏋侀獙KEY | 鐢盉绔欏悗绔骇鐢熺敤浜庝汉鏈洪獙璇?|
| key | str | 鐧诲綍绉橀挜 | 涓?captcha 鏃犲叧, 涓庣櫥褰曟帴鍙ｆ湁鍏? 浜︿綔 token |

**绀轰緥:**

```shell
curl 'https://passport.bilibili.com/web/captcha/combine?plat=6'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
  "code": 0,
  "data": {
    "result": {
      "success": 1,
      "gt": "bd111e81eda1cbb9f54425aafc0908ac",
      "challenge": "2903a8eb967a1d990444cb23ea42f417",
      "key": "76fb59fbd83a4d9d816162c5156fc964"
    },
    "type": 1
  }
}
```

</details>

### 杩涜楠岃瘉

鏈枃妗ｄ负 Bilibili 鏂囨。锛岄獙璇佺爜涓?[geetest 鏋侀獙](https://docs.geetest.com/sensebot/start/) 鎻愪緵锛屾晠涓嶆彁渚涚浉鍏?API

闄? [鎵嬪姩楠岃瘉鍣╙(https://kuresaru.github.io/geetest-validator/)
[鍙婂叾婧愮爜](https://github.com/kuresaru/geetest-validator)

1. 鎵撳紑鎵嬪姩楠岃瘉鍣紝鍦?銆?鍒嗗埆濉叆涓婇潰API杩斿洖鐨刞gt`鍜宍challenge`
2. 鐐瑰嚮鎸夐挳3锛岀◢绛夊姞杞介獙璇佺爜锛岀偣鍑绘寜閽?杩涜楠岃瘉
3. 楠岃瘉瀹屾垚鍚庯紝鐐瑰嚮鎸夐挳5鐢熸垚楠岃瘉缁撴灉
4. 浣跨敤鏈€寮€濮嬭幏寰楀埌鐨刞key`銆乣challenge`鍜屽垰鑾峰緱鍒扮殑`validate`銆乣seccode`缁х画涔嬪悗鐨勭櫥褰曟搷浣?
### 缁х画鐧诲綍

- [鐭俊鐧诲綍](SMS.md)
- [瀵嗙爜鐧诲綍](password.md)
