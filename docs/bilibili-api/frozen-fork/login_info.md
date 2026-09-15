# 鐧诲綍鍩烘湰淇℃伅

## 瀵艰埅鏍忕敤鎴蜂俊鎭?
> ~~https://api.bilibili.com/nav锛堝甫鏈夎浆涔夛級~~ (宸插け鏁?
>
> https://api.bilibili.com/x/web-interface/nav锛堝師濮嬫暟鎹級

*璇锋眰鏂瑰紡锛欸ET*

璁よ瘉鏂瑰紡锛氫粎鍙疌ookie锛圫ESSDATA锛?
**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁    | 绫诲瀷 | 鍐呭     | 澶囨敞                          |
| ------- | ---- | -------- | ----------------------------- |
| code    | num  | 杩斿洖鍊?  | 0锛氭垚鍔?br />-101锛氳处鍙锋湭鐧诲綍 |
| message | str  | 閿欒淇℃伅 | 榛樿涓?                       |
| ttl     | num  | 1        |                               |
| data    | obj  | 淇℃伅鏈綋 |                               |

`data`瀵硅薄锛?
| 瀛楁                 | 绫诲瀷 | 鍐呭             | 澶囨敞                                              |
| -------------------- | ---- | ---------------- | ------------------------------------------------- |
| isLogin              | bool | 鏄惁宸茬櫥褰?      | false锛氭湭鐧诲綍<br />true锛氬凡鐧诲綍                   |
| email_verified       | num  | 鏄惁楠岃瘉閭鍦板潃 | 0锛氭湭楠岃瘉<br />1锛氬凡楠岃瘉                          |
| face                 | str  | 鐢ㄦ埛澶村儚 url     |                                                   |
| level_info           | obj  | 绛夌骇淇℃伅         |                                                   |
| mid                  | num  | 鐢ㄦ埛 mid         |                                                   |
| mobile_verified      | num  | 鏄惁楠岃瘉鎵嬫満鍙?  | 0锛氭湭楠岃瘉<br />1锛氬凡楠岃瘉                          |
| money                | num  | 鎷ユ湁纭竵鏁?      |                                                   |
| moral                | num  | 褰撳墠鑺傛搷鍊?      | 涓婇檺涓?0                                          |
| official             | obj  | 璁よ瘉淇℃伅         |                                                   |
| officialVerify       | obj  | 璁よ瘉淇℃伅 2       |                                                   |
| pendant              | obj  | 澶村儚妗嗕俊鎭?      |                                                   |
| scores               | num  | 锛堬紵锛?          |                                                   |
| uname                | str  | 鐢ㄦ埛鏄电О         |                                                   |
| vipDueDate           | num  | 浼氬憳鍒版湡鏃堕棿     | 姣 鏃堕棿鎴?                                      |
| vipStatus            | num  | 浼氬憳寮€閫氱姸鎬?    | 0锛氭棤<br />1锛氭湁                                  |
| vipType              | num  | 浼氬憳绫诲瀷         | 0锛氭棤<br />1锛氭湀搴﹀ぇ浼氬憳<br />2锛氬勾搴﹀強浠ヤ笂澶т細鍛?|
| vip_pay_type         | num  | 浼氬憳寮€閫氱姸鎬?    | 0锛氭棤<br />1锛氭湁                                  |
| vip_theme_type       | num  | 锛堬紵锛?          |                                                   |
| vip_label            | obj  | 浼氬憳鏍囩         |                                                   |
| vip_avatar_subscript | num  | 鏄惁鏄剧ず浼氬憳鍥炬爣 | 0锛氫笉鏄剧ず<br />1锛氭樉绀?                           |
| vip_nickname_color   | str  | 浼氬憳鏄电О棰滆壊     | 棰滆壊鐮?                                           |
| wallet               | obj  | B甯侀挶鍖呬俊鎭?     |                                                   |
| has_shop             | bool | 鏄惁鎷ユ湁鎺ㄥ箍鍟嗗搧 | false锛氭棤<br />true锛氭湁                           |
| shop_url             | str  | 鍟嗗搧鎺ㄥ箍椤甸潰 url |                                                   |
| allowance_count      | num  | 锛堬紵锛?          |                                                   |
| answer_status        | num  | 锛堬紵锛?          |                                                   |
| is_senior_member     | num  | 鏄惁纭牳浼氬憳     | 0锛氶潪纭牳浼氬憳<br />1锛氱‖鏍镐細鍛?                   |
| wbi_img              | obj  | Wbi 绛惧悕瀹炴椂鍙ｄ护 | 璇ュ瓧娈靛嵆浣跨敤鎴锋湭鐧诲綍涔熷瓨鍦?                       |
| is_jury              | bool | 鏄惁椋庣邯濮斿憳     | true锛氶绾鍛?br />false锛氶潪椋庣邯濮斿憳             |

`data`涓殑`level_info`瀵硅薄锛?
| 瀛楁          | 绫诲瀷 | 鍐呭                     | 澶囨敞 |
| ------------- | ---- | ------------------------ | ---- |
| current_level | num  | 褰撳墠绛夌骇                 |      |
| current_min   | num  | 褰撳墠绛夌骇缁忛獙鏈€浣庡€?      |      |
| current_exp   | num  | 褰撳墠缁忛獙                 |      |
| next_exp      | 灏忎簬6绾ф椂锛歯um<br />6绾ф椂锛歴tr | 鍗囩骇涓嬩竴绛夌骇闇€杈惧埌鐨勭粡楠?|褰撶敤鎴风瓑绾т负Lv6鏃讹紝鍊间负`--`锛屼唬琛ㄦ棤绌峰ぇ |

`data`涓殑`official`瀵硅薄锛?
| 瀛楁  | 绫诲瀷 | 鍐呭     | 澶囨敞                                              |
| ----- | ---- | -------- | ------------------------------------------------- |
| role  | num  | 璁よ瘉绫诲瀷 | 瑙乕鐢ㄦ埛璁よ瘉绫诲瀷涓€瑙圿(../user/official_role.md) |
| title | str  | 璁よ瘉淇℃伅 | 鏃犱负绌?                                           |
| desc  | str  | 璁よ瘉澶囨敞 | 鏃犱负绌?                                           |
| type  | num  | 鏄惁璁よ瘉 | -1锛氭棤<br />0锛氳璇?                              |

`data`涓殑`official_verify`瀵硅薄锛?
| 瀛楁 | 绫诲瀷 | 鍐呭     | 澶囨敞                |
| ---- | ---- | -------- | ------------------- |
| type | num  | 鏄惁璁よ瘉 | -1锛氭棤<br />0锛氳璇?|
| desc | str  | 璁よ瘉淇℃伅 | 鏃犱负绌?             |

`data`涓殑`pendant`瀵硅薄锛?
| 瀛楁   | 绫诲瀷 | 鍐呭        | 澶囨敞 |
| ------ | ---- | ----------- | ---- |
| pid    | num  | 鎸備欢id      |      |
| name   | str  | 鎸備欢鍚嶇О    |      |
| image  | str  | 鎸備欢鍥剧墖url |      |
| expire | num  | 锛堬紵锛?     |      |

`data`涓殑`vip_label`瀵硅薄锛?
| 瀛楁        | 绫诲瀷 | 鍐呭     | 澶囨敞                                                         |
| ----------- | ---- | -------- | ------------------------------------------------------------ |
| path        | str  | 锛堬紵锛?  |                                                              |
| text        | str  | 浼氬憳鍚嶇О |                                                              |
| label_theme | str  | 浼氬憳鏍囩 | vip锛氬ぇ浼氬憳<br />annual_vip锛氬勾搴﹀ぇ浼氬憳<br />ten_annual_vip锛氬崄骞村ぇ浼氬憳<br />hundred_annual_vip锛氱櫨骞村ぇ浼氬憳 |

`data`涓殑`wallet`瀵硅薄锛?
| 瀛楁            | 绫诲瀷 | 鍐呭          | 澶囨敞 |
| --------------- | ---- | ------------- | ---- |
| mid             | num  | 鐧诲綍鐢ㄦ埛mid   |      |
| bcoin_balance   | num  | 鎷ユ湁B甯佹暟     |      |
| coupon_balance  | num  | 姣忔湀濂栧姳B甯佹暟 |      |
| coupon_due_time | num  | 锛堬紵锛?       |      |

`data`涓殑`wbi_img`瀵硅薄锛?
| 瀛楁    | 绫诲瀷 | 鍐呭                            | 澶囨敞                                     |
| ------- | ---- | ------------------------------- | ---------------------------------------- |
| img_url | str  | Wbi 绛惧悕鍙傛暟 `imgKey`鐨勪吉瑁?url | 璇﹁鏂囨。 [Wbi 绛惧悕](../misc/sign/wbi.md) |
| sub_url | str  | Wbi 绛惧悕鍙傛暟 `subKey`鐨勪吉瑁?url | 璇﹁鏂囨。 [Wbi 绛惧悕](../misc/sign/wbi.md) |

**绀轰緥锛?*

**鐧诲綍鐘舵€侊細**

```shell
curl 'https://api.bilibili.com/x/web-interface/nav' \
	-b 'SESSDATA=xxx'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "isLogin": true,
        "email_verified": 1,
        "face": "https://i0.hdslb.com/bfs/face/aebb2639a0d47f2ce1fec0631f412eaf53d4a0be.jpg",
        "face_nft": 0,
        "face_nft_type": 0,
        "level_info": {
            "current_level": 6,
            "current_min": 28800,
            "current_exp": 52689,
            "next_exp": "--"
        },
        "mid": 293793435,
        "mobile_verified": 1,
        "money": 172.4,
        "moral": 70,
        "official": {
            "role": 0,
            "title": "",
            "desc": "",
            "type": -1
        },
        "officialVerify": {
            "type": -1,
            "desc": ""
        },
        "pendant": {
            "pid": 2511,
            "name": "鍒濋煶鏈潵13鍛ㄥ勾",
            "image": "https://i0.hdslb.com/bfs/garb/item/4f8f3f1f2d47f0dad84f66aa57acd4409ea46361.png",
            "expire": 0,
            "image_enhance": "https://i0.hdslb.com/bfs/garb/item/fe0b83b53e2342b16646f6e7a9370d8a867decdb.webp",
            "image_enhance_frame": "https://i0.hdslb.com/bfs/garb/item/127c507ec8448be30cf5f79500ecc6ef2fd32f2c.png"
        },
        "scores": 0,
        "uname": "绀句細鏄撳QwQ",
        "vipDueDate": 1707494400000,
        "vipStatus": 1,
        "vipType": 2,
        "vip_pay_type": 0,
        "vip_theme_type": 0,
        "vip_label": {
            "path": "",
            "text": "骞村害澶т細鍛?,
            "label_theme": "annual_vip",
            "text_color": "#FFFFFF",
            "bg_style": 1,
            "bg_color": "#FB7299",
            "border_color": "",
            "use_img_label": true,
            "img_label_uri_hans": "",
            "img_label_uri_hant": "",
            "img_label_uri_hans_static": "https://i0.hdslb.com/bfs/vip/8d4f8bfc713826a5412a0a27eaaac4d6b9ede1d9.png",
            "img_label_uri_hant_static": "https://i0.hdslb.com/bfs/activity-plat/static/20220614/e369244d0b14644f5e1a06431e22a4d5/VEW8fCC0hg.png"
        },
        "vip_avatar_subscript": 1,
        "vip_nickname_color": "#FB7299",
        "vip": {
            "type": 2,
            "status": 1,
            "due_date": 1707494400000,
            "vip_pay_type": 0,
            "theme_type": 0,
            "label": {
                "path": "",
                "text": "骞村害澶т細鍛?,
                "label_theme": "annual_vip",
                "text_color": "#FFFFFF",
                "bg_style": 1,
                "bg_color": "#FB7299",
                "border_color": "",
                "use_img_label": true,
                "img_label_uri_hans": "",
                "img_label_uri_hant": "",
                "img_label_uri_hans_static": "https://i0.hdslb.com/bfs/vip/8d4f8bfc713826a5412a0a27eaaac4d6b9ede1d9.png",
                "img_label_uri_hant_static": "https://i0.hdslb.com/bfs/activity-plat/static/20220614/e369244d0b14644f5e1a06431e22a4d5/VEW8fCC0hg.png"
            },
            "avatar_subscript": 1,
            "nickname_color": "#FB7299",
            "role": 3,
            "avatar_subscript_url": "",
            "tv_vip_status": 0,
            "tv_vip_pay_type": 0,
            "tv_due_date": 1640793600
        },
        "wallet": {
            "mid": 293793435,
            "bcoin_balance": 5,
            "coupon_balance": 5,
            "coupon_due_time": 0
        },
        "has_shop": true,
        "shop_url": "https://gf.bilibili.com?msource=main_station",
        "allowance_count": 0,
        "answer_status": 0,
        "is_senior_member": 1,
        "wbi_img": {
            "img_url": "https://i0.hdslb.com/bfs/wbi/653657f524a547ac981ded72ea172057.png",
            "sub_url": "https://i0.hdslb.com/bfs/wbi/6e4909c702f846728e64f6007736a338.png"
        },
        "is_jury": false
    }
}
```

</details>

**鏈櫥褰曠姸鎬侊細**

```shell
curl 'https://api.bilibili.com/x/web-interface/nav'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": -101,
    "message": "璐﹀彿鏈櫥褰?,
    "ttl": 1,
    "data": {
        "isLogin": false,
        "wbi_img": {
            "img_url": "https://i0.hdslb.com/bfs/wbi/653657f524a547ac981ded72ea172057.png",
            "sub_url": "https://i0.hdslb.com/bfs/wbi/6e4909c702f846728e64f6007736a338.png"
        },
    }
}
```

</details>

## ~~鐧诲綍鐢ㄦ埛淇℃伅浠呴儴鍒嗭紙宸插純鐢級~~

<details>
<summary>鏌ョ湅鎶樺彔鍐呭</summary>

> https://account.bilibili.com/home/userInfo

*璇锋眰鏂瑰紡锛欸ET*

璁よ瘉鏂瑰紡锛氫粎鍙疌ookie锛圫ESSDATA锛?
閴存潈鏂瑰紡锛欳ookie涓璥DedeUserID`瀛樺湪涓斾笉涓?

甯︽湁杞箟

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁   | 绫诲瀷 | 鍐呭     | 澶囨敞                          |
| ------ | ---- | -------- | ----------------------------- |
| code   | num  | 杩斿洖鍊?  | 0锛氭垚鍔?br />-101锛氳处鍙锋湭鐧诲綍 |
| status | bool | true     | 浣滅敤灏氫笉鏄庣‘                  |
| data   | obj  | 淇℃伅鏈綋 |                               |

`data`瀵硅薄锛?
| 瀛楁              | 绫诲瀷 | 鍐呭              | 澶囨敞                            |
| ----------------- | ---- | ----------------- | ------------------------------- |
| level_info        | obj  | 绛夌骇淇℃伅          |                                 |
| bCoins            | num  | 鎷ユ湁B甯佹暟         |                                 |
| coins             | num  | 鎷ユ湁纭竵鏁?       |                                 |
| face              | str  | 鐧诲綍鐢ㄦ埛澶村儚url   |                                 |
| nameplate_current | null | ???               | 浣滅敤灏氫笉鏄庣‘                    |
| nameplate_current | str  | 鐧诲綍鐢ㄦ埛鍕嬬珷url   |                                 |
| pendant_current   | str  | 鐧诲綍鐢ㄦ埛澶村儚妗唘rl |                                 |
| uname             | str  | 鐧诲綍鐢ㄦ埛鏄电О      |                                 |
| userStatus        | str  | 鐧诲綍鐢ㄦ埛鐘舵€?     |                                 |
| vipType           | num  | 澶т細鍛樼被鍨?       | 0锛氭棤<br />1锛氭湀搴?br />2锛氬勾搴?|
| vipStatus         | num  | 浼氬憳寮€閫氱姸鎬?     | 0锛氭棤<br />1锛氭湁                |
| official_verify   | num  | 鏄惁璁よ瘉          | -1锛氭棤<br />0锛氳璇?            |
| pointBalance      | num  | 0                 | 浣滅敤灏氫笉鏄庣‘                    |

`data`涓殑`level_info`瀵硅薄锛?
| 瀛楁          | 绫诲瀷 | 鍐呭                     | 澶囨敞 |
| ------------- | ---- | ------------------------ | ---- |
| current_level | num  | 褰撳墠绛夌骇                 |      |
| current_min   | num  | 褰撳墠绛夌骇缁忛獙鏈€浣庡€?      |      |
| current_exp   | num  | 褰撳墠缁忛獙                 |      |
| next_exp      | num  | 鍗囩骇涓嬩竴绛夌骇闇€杈惧埌鐨勭粡楠?|      |

**绀轰緥锛?*

```shell
curl 'https://account.bilibili.com/home/userInfo' \
-b 'SESSDATA=xxx;DedeUserID=1;'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
	"code": 0,
	"status": true,
	"data": {
		"level_info": {
			"current_level": 5,
			"current_min": 10800,
			"current_exp": 14270,
			"next_exp": 28800
		},
		"bCoins": 10,
		"coins": 2.5,
		"face": "http:\/\/i2.hdslb.com\/bfs\/face\/480e2e98513aaeb65d2f2c76dbae750c4de722e9.jpg",
		"nameplate_current": null,
		"pendant_current": "http:\/\/i0.hdslb.com\/bfs\/face\/6550f53324c330f201a528e70ef305cb10ac2c01.png",
		"uname": "\u793e\u4f1a\u6613\u59d0QwQ",
		"userStatus": "\u6b63\u5f0f\u4f1a\u5458",
		"vipType": 2,
		"vipStatus": 1,
		"official_verify": -1,
		"pointBalance": 0
	}
}
```

</details>

</details>

## 鐧诲綍鐢ㄦ埛淇℃伅锛圓PP绔級

> https://app.bilibili.com/x/v2/account/myinfo 

*璇锋眰鏂瑰紡锛欸ET*

璁よ瘉鏂瑰紡锛氫粎鍙疉PP

閴存潈鏂瑰紡锛歛ppkey

**url鍙傛暟锛?*

| 鍙傛暟鍚?    | 绫诲瀷 | 鍐呭         | 蹇呰鎬?     | 澶囨敞 |
| ---------- | ---- | ------------ | ----------- | ---- |
| access_key | str  | APP鐧诲綍Token | APP鏂瑰紡蹇呰 |      |
| appkey     | str  | APP瀵嗛挜      | APP鏂瑰紡蹇呰 |      |
| ts         | num  | 褰撳墠鏃堕棿鎴?  | APP鏂瑰紡蹇呰 |      |
| sign       | str  | APP绛惧悕      | APP鏂瑰紡蹇呰 |      |

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁    | 绫诲瀷 | 鍐呭     | 澶囨敞                                                         |
| ------- | ---- | -------- | ------------------------------------------------------------ |
| code    | num  | 杩斿洖鍊?  | 0锛氭垚鍔?br />-3锛欰PI鏍￠獙瀵嗗寵閿欒<br />-101锛氳处鍙锋湭鐧诲綍<br />-400锛氳姹傞敊璇?|
| message | str  | 閿欒淇℃伅 | 榛樿涓?                                                      |
| ttl     | num  | 1        |                                                              |
| data    | obj  | 淇℃伅鏈綋 |                                                              |

`data`瀵硅薄锛?
| 瀛楁           | 绫诲瀷 | 鍐呭             | 澶囨敞                          |
| -------------- | ---- | ---------------- | ----------------------------- |
| mid            | num  | 鐢ㄦ埛mid          |                               |
| name           | str  | 鐢ㄦ埛鏄电О         |                               |
| sign           | str  | 鐢ㄦ埛绛惧悕         |                               |
| coins          | num  | 鎷ユ湁纭竵鏁?      |                               |
| birthday       | str  | 鐢ㄦ埛鐢熸棩         | YYYY-MM-DD                    |
| face           | str  | 鐢ㄦ埛澶村儚url      |                               |
| sex            | num  | 鐢ㄦ埛鎬у埆         | 0锛氱瀵?br />1锛氱敺<br />2锛氬コ |
| level          | num  | 鐢ㄦ埛绛夌骇         | 0-6                           |
| rank           | num  | 1000             | **浣滅敤灏氫笉鏄庣‘**              |
| silence        | num  | 鐢ㄦ埛鏄惁琚皝绂?  | 0锛氭甯?br />1锛氬皝绂?         |
| vip            | obj  | 浼氬憳淇℃伅         |                               |
| email_status   | num  | 鏄惁楠岃瘉閭鍦板潃 | 0锛氭湭楠岃瘉<br />1锛氬凡楠岃瘉      |
| tel_status     | num  | 鏄惁楠岃瘉鎵嬫満鍙?  | 0锛氭湭楠岃瘉<br />1锛氬凡楠岃瘉      |
| official       | obj  | 璁よ瘉淇℃伅         |                               |
| identification | num  | 1                | **浣滅敤灏氫笉鏄庣‘**              |
| invite         | obj  |                  |                               |
| is_tourist     | num  | 0                | **浣滅敤灏氫笉鏄庣‘**              |
| pin_prompting  | num  | 0                | **浣滅敤灏氫笉鏄庣‘**              |

`data`涓殑`vip`瀵硅薄锛?
| 瀛楁             | 绫诲瀷 | 鍐呭             | 澶囨敞                            |
| ---------------- | ---- | ---------------- | ------------------------------- |
| type             | num  | 澶т細鍛樼被鍨?      | 0锛氭棤<br />1锛氭湀搴?br />2锛氬勾搴?|
| status           | num  | 浼氬憳寮€閫氱姸鎬?    | 0锛氭棤<br />1锛氭湁                |
| due_date         | num  | 澶т細鍛樺埌鏈熸椂闂?  | 姣 鏃堕棿鎴?                    |
| vip_pay_type     | num  | 浼氬憳寮€閫氱姸鎬?    | 0锛氭棤<br />1锛氭湁                |
| theme_type       | num  | 浼氬憳寮€閫氱姸鎬?    | 0锛氭棤<br />1锛氭湁                |
| label            | obj  | 澶т細鍛樹俊鎭?      |                                 |
| avatar_subscript | num  | 鏄惁鏄剧ず浼氬憳鍥炬爣 | 0锛氫笉鏄剧ず<br />1锛氭樉绀?         |
| nickname_color   | str  | 浼氬憳鏄电О棰滆壊     | 棰滆壊鐮?                         |

`vip`涓殑`label`瀵硅薄锛?
| 瀛楁        | 绫诲瀷 | 鍐呭         | 澶囨敞             |
| ----------- | ---- | ------------ | ---------------- |
| path        | str  | 绌?          | **浣滅敤灏氫笉鏄庣‘** |
| text        | str  | 浼氬憳绫诲瀷鏂囧瓧 |                  |
| label_theme | str  | 浼氬憳绫诲瀷     |                  |

`data`涓殑`official`瀵硅薄锛?
| 瀛楁  | 绫诲瀷 | 鍐呭     | 澶囨敞                                              |
| ----- | ---- | -------- | ------------------------------------------------- |
| role  | num  | 璁よ瘉绫诲瀷 | 0锛氭棤<br />1 2 7锛氫釜浜鸿璇?br />3 4 5 6锛氭満鏋勮璇?|
| title | str  | 璁よ瘉淇℃伅 | 鏃犱负绌?                                           |
| desc  | str  | 璁よ瘉澶囨敞 | 鏃犱负绌?                                           |
| type  | num  | 璁よ瘉澶囨敞 | 鏃犱负绌?                                           |

`data`涓殑`invite`瀵硅薄锛?
| 瀛楁          | 绫诲瀷 | 鍐呭 | 澶囨敞             |
| ------------- | ---- | ---- | ---------------- |
| invite_remind | num  | 1    | **浣滅敤灏氫笉鏄庣‘** |
| display       | bool | true | **浣滅敤灏氫笉鏄庣‘** |

**绀轰緥锛?*

```shell
curl -G 'https://app.bilibili.com/x/v2/account/myinfo' \
--data-urlencode 'access_key=xxx' \
--data-urlencode 'appkey=4409e2ce8ffd12b8' \
--data-urlencode 'ts=0' \
--data-urlencode 'sign=b8fb8480049c525994be6507a97ae0b6'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "mid": 293793435,
        "name": "绀句細鏄撳QwQ",
        "sign": "楂樹腑鎶€鏈畢涓€鏋氾紝鐖卞ソMC&鐢靛瓙&8-bit闊充箰&鏁扮爜&缂栫▼锛岃祫娣辩尶鍘紝绮変笣缇わ細1136462265",
        "coins": 33.4,
        "birthday": "2002-03-05",
        "face": "http://i1.hdslb.com/bfs/face/aebb2639a0d47f2ce1fec0631f412eaf53d4a0be.jpg",
        "sex": 1,
        "level": 5,
        "rank": 10000,
        "silence": 0,
        "vip": {
            "type": 2,
            "status": 1,
            "due_date": 1612454400000,
            "vip_pay_type": 1,
            "theme_type": 0,
            "label": {
                "path": "",
                "text": "骞村害澶т細鍛?,
                "label_theme": "annual_vip"
            },
            "avatar_subscript": 1,
            "nickname_color": "#FB7299"
        },
        "email_status": 1,
        "tel_status": 1,
        "official": {
            "role": 0,
            "title": "",
            "desc": "",
            "type": -1
        },
        "identification": 1,
        "invite": {
            "invite_remind": 1,
            "display": true
        },
        "is_tourist": 0,
        "pin_prompting": 0
    }
}
```

</details>


## 鐧诲綍鐢ㄦ埛鐘舵€佹暟锛堝弻绔級

> https://api.bilibili.com/x/web-interface/nav/stat

*璇锋眰鏂瑰紡锛欸ET*

璁よ瘉鏂瑰紡锛欳ookie锛圫ESSDATA锛夋垨APP

**url鍙傛暟锛?*

| 鍙傛暟鍚?    | 绫诲瀷 | 鍐呭         | 蹇呰鎬?     | 澶囨敞 |
| ---------- | ---- | ------------ | ----------- | ---- |
| access_key | str  | APP鐧诲綍Token | APP鏂瑰紡蹇呰 |      |

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁    | 绫诲瀷 | 鍐呭     | 澶囨敞                          |
| ------- | ---- | -------- | ----------------------------- |
| code    | num  | 杩斿洖鍊?  | 0锛氭垚鍔?br />-101锛氳处鍙锋湭鐧诲綍 |
| message | str  | 閿欒淇℃伅 | 榛樿涓?                       |
| ttl     | num  | 1        |                               |
| data    | obj  | 淇℃伅鏈綋 |                               |

| 瀛楁          | 绫诲瀷 | 鍐呭       | 澶囨敞 |
| ------------- | ---- | ---------- | ---- |
| following     | num  | 鍏虫敞鏁?    |      |
| follower      | num  | 绮変笣鏁?    |      |
| dynamic_count | num  | 鍙戝竷鍔ㄦ€佹暟 |      |

**绀轰緥锛?*

褰撳墠鐧诲綍鐢ㄦ埛鐨勭姸鎬佹暟涓虹矇涓?96锛屽叧娉?54锛屽彂閫佺殑鍔ㄦ€?52

Cookie鏂瑰紡锛?
```shell
curl 'https://api.bilibili.com/x/web-interface/nav/stat' \
-b 'SESSDATA=xxx'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "following": 754,
        "follower": 596,
        "dynamic_count": 252
    }
}
```

</details>

APP鏂瑰紡锛?
```shell
curl -G 'https://api.bilibili.com/x/web-interface/nav/stat' \
--data-urlencode 'access_key=d907f51122c59599d580ade2315af971'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "following": 754,
        "follower": 596,
        "dynamic_count": 252
    }
}
```

</details>

## 鑾峰彇纭竵鏁?
>  https://account.bilibili.com/site/getCoin

*璇锋眰鏂瑰紡锛欸ET*

璁よ瘉鏂瑰紡锛氫粎鍙疌ookie锛圫ESSDATA锛?
閴存潈鏂瑰紡锛欳ookie涓璥 DedeUserID `瀛樺湪涓斾笉涓?

**json鍥炲锛?*

鏍瑰璞★細

| 瀛楁   | 绫诲瀷 | 鍐呭     | 澶囨敞                          |
| ------ | ---- | -------- | ----------------------------- |
| code   | num  | 杩斿洖鍊?  | 0锛氭垚鍔?br />-101锛氳处鍙锋湭鐧诲綍 |
| status | bool | true     | 浣滅敤灏氫笉鏄庣‘                  |
| data   | obj  | 淇℃伅鏈綋 |                               |

`data`瀵硅薄锛?
| 瀛楁  | 绫诲瀷                                   | 鍐呭       | 澶囨敞 |
| ----- | -------------------------------------- | ---------- | ---- |
| money | 纭竵涓烘鏁版椂锛歯um<br />纭竵涓?鏃讹細null | 褰撳墠纭竵鏁?|      |

**绀轰緥锛?*

```shell
curl 'https://account.bilibili.com/site/getCoin' \
-b 'SESSDATA=xxx;DedeUserID=1;'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>


```json
{
    "code": 0,
    "status": true,
    "data": {
        "money": 42.4
    }
}
```

</details>
