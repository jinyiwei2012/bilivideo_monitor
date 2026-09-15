# Web绔疌ookie鍒锋柊

鑷粠 2023 浠ユ潵锛岀ぞ鍖哄弽棣堜技涔?Web 绔殑 Cookie 浼氶殢鐫€涓€浜涙晱鎰熸帴鍙ｇ殑璁块棶閫愭笎澶辨晥锛岃€屽湪 Web 椤甸潰涓婁細鍒ゆ柇 Cookie 鏄惁闇€瑕佸埛鏂帮紝濡傞渶鍒锋柊鍒欎細浠ュ姩鎬佸姞杞?iframe 鏂瑰紡瀹炵幇锛屽悓鏃剁櫥褰曪紙浜岀淮鐮?/ 瀵嗙爜 / 鐭俊楠岃瘉鐮佺瓑锛夋帴鍙ｄ篃浼氳繑鍥瀈refresh_token`瀛楁锛岄渶瑕佹寔涔呭寲淇濆瓨锛屾槸涓€绉嶅畼鏂圭殑椋庢帶鏈哄埗瀹炵幇

鎰熻阿 [#524](https://github.com/SocialSisterYi/bilibili-API-collect/issues/524) 鎻愪緵鐩稿叧鐮旂┒鎶ュ憡浠ュ強閫嗗悜宸ョ▼缁撴灉

> cookie 涓嶄細涓诲姩鍒锋柊鐨勶紝鍙浠栨病鏈夎皟鐢ㄤ笅闈㈢殑鍒锋柊鎺ュ彛灏变笉浼氬埛鏂般€備篃灏辨槸璇达紝浣犲彧瑕佷笉鍐嶆墦寮€娴忚鍣紝鎴栬€呯洿鎺ユ妸 localStorage 鐨?ac_time_value 瀛楁鍒犻櫎浜嗐€傞偅涔?cookie 鍦ㄧ湡鐨勫け鏁堝墠锛堢櫥褰曡繃鏈熴€佽处鍙烽鎺х瓑寮哄埗涓嬬嚎锛夐兘鏄笉鍙樺寲鐨勩€?
## 鍒锋柊姝ラ锛堜吉浠ｇ爜锛?
```python
cookie, refresh_token = 杩涜鐧诲綍鎿嶄綔() # can be 浜岀淮鐮?/ 瀵嗙爜 / 鐭俊楠岃瘉鐮?
while True:
    if 姣忔棩绗竴娆¤闂帴鍙?
        if 妫€鏌ユ槸鍚﹂渶瑕佸埛鏂?cookie):
            CorrespondPath = 鐢熸垚CorrespondPath(褰撳墠姣鏃堕棿鎴?
            refresh_csrf = 鑾峰彇refresh_csrf(CorrespondPath, cookie)
            refresh_token_old = refresh_token # 杩欎竴姝ュ繀椤讳繚瀛樻棫鐨?refresh_token 澶囩敤
            cookie, refresh_token = 鍒锋柊Cookie(refresh_token, refresh_csrf, cookie)
            纭鏇存柊(refresh_token_old, cookie) # 杩欎竴姝ラ渶瑕佹柊鐨?Cookie 浠ュ強鏃х殑 refresh_token
            SSO绔欑偣璺ㄥ煙鐧诲綍(cookie)
    do_somethings(cookie) # 鍏朵粬涓氬姟閫昏緫澶勭悊
```

## 妫€鏌ユ槸鍚﹂渶瑕佸埛鏂?
> https://passport.bilibili.com/x/passport-login/web/cookie/info

*璇锋眰鏂瑰紡锛欸ET*

閴存潈鏂瑰紡锛欳ookie

**url 鍙傛暟锛?*

| 鍙傛暟鍚?| 绫诲瀷 | 鍐呭                      | 蹇呰鎬?| 澶囨敞 |
| ------ | ---- | ------------------------- | ------ | ---- |
| csrf   | str  | CSRF Token锛堜綅浜?Cookie锛?| 闈炲繀瑕?|   浣嶄簬 Cookie 涓殑bili_jct瀛楁   |

**json 鍥炲锛?*

鏍瑰璞★細

| 瀛楁    | 绫诲瀷 | 鍐呭     | 澶囨敞                          |
| ------- | ---- | -------- | ----------------------------- |
| code    | num  | 杩斿洖鍊?  | 0锛氭垚鍔?br />-101锛氳处鍙锋湭鐧诲綍 |
| message | str  | 閿欒淇℃伅 | 榛樿涓?0                      |
| ttl     | num  | 1        |                               |
| data    | obj  | 淇℃伅鏈綋 |                               |

`data`瀵硅薄锛?
| 瀛楁      | 绫诲瀷 | 鍐呭                | 澶囨敞                                                  |
| --------- | ---- | ------------------- | ----------------------------------------------------- |
| refresh   | bool | 鏄惁搴旇鍒锋柊 Cookie | `true`锛氶渶瑕佸埛鏂?Cookie<br />`false`锛氭棤闇€鍒锋柊 Cookie |
| timestamp | num  | 褰撳墠姣鏃堕棿鎴?     | 鐢ㄤ簬鑾峰彇 refresh_csrf                                 |

**绀轰緥锛?*

```bash
curl -G 'https://passport.bilibili.com/x/passport-login/web/cookie/info' \
	--data-urlencode 'csrf=xxx' \
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
        "refresh": false,
        "timestamp": 1684466082562
    }
}
```

</details>

## 鐢熸垚CorrespondPath绠楁硶

璇ョ畻娉曢€嗗悜浜庝互涓?wasm 浠ュ強 JavaScript bind 鎺ュ彛锛屾姄鍙栦簬瀹樻柟 Web 棣栭〉涓紝鎰熻阿 [#524](https://github.com/SocialSisterYi/bilibili-API-collect/issues/524) 鎻愪緵

https://s1.hdslb.com/bfs/static/jinkela/long/wasm/wasm_rsa_encrypt_bg.wasm

https://s1.hdslb.com/bfs/static/jinkela/long/wasm/wasm_ras_umd.js

### 绠楁硶缁嗚妭

灏哷refresh_${timestamp}`浣滀负娑堟伅浣擄紙鍙傛暟`timestamp`涓哄綋鍓嶆绉掓椂闂存埑锛夛紝鐢ㄤ笅鏂?PubKey 杩涜 [RSA-OAEP](https://datatracker.ietf.org/doc/html/rfc3447#section-7.1) 绠楁硶鍔犲瘑锛屼箣鍚庡瘑鏂囬€氳繃灏忓啓 Base16 缂栫爜涓哄瓧绗︿覆

JWK 鏍煎紡锛?
> {
>     "kty": "RSA",
>     "n": "y4HdjgJHBlbaBN04VERG4qNBIFHP6a3GozCl75AihQloSWCXC5HDNgyinEnhaQ_4-gaMud_GF50elYXLlCToR9se9Z8z433U3KjM-3Yx7ptKkmQNAMggQwAVKgq3zYAoidNEWuxpkY_mAitTSRLnsJW-NCTa0bqBFF6Wm1MxgfE",
>     "e": "AQAB"
> }

PEM 鏍煎紡锛?
> -----BEGIN PUBLIC KEY-----
> MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg
> Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71
> nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40
> JNrRuoEUXpabUzGB8QIDAQAB
> -----END PUBLIC KEY-----

### 鐩稿叧Demo

璇?Demo 鎻愪緵 [JavaScript](#javascript) [Python](#python) [Kotlin](#kotlin) [Java](#java) [Go](#go) 浠ュ強 [Vercel 浜戝嚱鏁癩(#vercel浜戝嚱鏁?锛屾劅璋?[#524](https://github.com/SocialSisterYi/bilibili-API-collect/issues/524) 鎻愪緵

#### JavaScript

```javascript
const publicKey = await crypto.subtle.importKey(
  "jwk",
  {
    kty: "RSA",
    n: "y4HdjgJHBlbaBN04VERG4qNBIFHP6a3GozCl75AihQloSWCXC5HDNgyinEnhaQ_4-gaMud_GF50elYXLlCToR9se9Z8z433U3KjM-3Yx7ptKkmQNAMggQwAVKgq3zYAoidNEWuxpkY_mAitTSRLnsJW-NCTa0bqBFF6Wm1MxgfE",
    e: "AQAB",
  },
  { name: "RSA-OAEP", hash: "SHA-256" },
  true,
  ["encrypt"],
)

async function getCorrespondPath(timestamp) {
  const data = new TextEncoder().encode(`refresh_${timestamp}`);
  const encrypted = new Uint8Array(await crypto.subtle.encrypt({ name: "RSA-OAEP" }, publicKey, data))
  return encrypted.reduce((str, c) => str + c.toString(16).padStart(2, "0"), "")
}

const ts = Date.now()
console.log(await getCorrespondPath(ts))
```

```text
b77f21ab5b7ce7879c410b2311dd6e7ea1a2cd1cd941073db067f4c3279fdabca3a06dfa744168ee14ad050b9f4889bd4edb8e76eb597fdd18c16804d82566b55c6dba8e225d838aa93d8e5b31cf7c56720db8244d92373f4944e0561f6ca5bf721a36ac079786060fc853605ccd1ddcb33f54617de6aedd44e3b9850d13b45f
```

#### Python

闇€瑕乣pycryptodome`渚濊禆

```python
from Crypto.Cipher import PKCS1_OAEP
from Crypto.PublicKey import RSA
from Crypto.Hash import SHA256
import binascii
import time

key = RSA.importKey('''\
-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg
Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71
nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40
JNrRuoEUXpabUzGB8QIDAQAB
-----END PUBLIC KEY-----''')

def getCorrespondPath(ts):
    cipher = PKCS1_OAEP.new(key, SHA256)
    encrypted = cipher.encrypt(f'refresh_{ts}'.encode())
    return binascii.b2a_hex(encrypted).decode()

ts = round(time.time() * 1000)
print(getCorrespondPath(ts))
```

```text
47bbd615f333d6a2c597bbb46ad47a6e59752a305a2f545d3ba5d49ca055309347796f80d257613696d36170c57443a0e9dea2b47f83b0b4224d431e46124fadd9a24c8fa468147e8bf2d2501eaacae43310e19bf58fc4a728d80c90b9401afcfc1536ba9a2f6438ea53c0b2652f8b8d01c87355dd5a5da51de998b1a35d519a
```

### Kotlin

```kotlin
import java.security.KeyFactory
import java.security.spec.MGF1ParameterSpec
import java.security.spec.X509EncodedKeySpec
import java.util.*
import javax.crypto.Cipher
import javax.crypto.spec.OAEPParameterSpec
import javax.crypto.spec.PSource


fun main() {
    println(getCorrespondPath(System.currentTimeMillis()))
}

fun getCorrespondPath(timestamp: Long): String {
    val publicKeyPEM = """
        -----BEGIN PUBLIC KEY-----
        MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg
        Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71
        nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40
        JNrRuoEUXpabUzGB8QIDAQAB
        -----END PUBLIC KEY-----
    """.trimIndent()

    val publicKey = KeyFactory.getInstance("RSA").generatePublic(
        X509EncodedKeySpec(Base64.getDecoder().decode(publicKeyPEM
            .replace("-----BEGIN PUBLIC KEY-----", "")
            .replace("-----END PUBLIC KEY-----", "")
            .replace("\n", "")
            .trim()))
    )

    val cipher = Cipher.getInstance("RSA/ECB/OAEPPadding").apply {
        init(Cipher.ENCRYPT_MODE,
            publicKey,
            OAEPParameterSpec("SHA-256", "MGF1", MGF1ParameterSpec.SHA256, PSource.PSpecified.DEFAULT)
        )
    }

    return cipher.doFinal("refresh_$timestamp".toByteArray()).joinToString("") { "%02x".format(it) }
}
```

```text
1428cbd14605ae42a0b42e22662cfe51d8e5034eeaffb36a46db46bd2f93216cbfd4d150cca2de44395add7c664b40acf44424ee8d634fc821b909423665a34d18bd7f4e77ea5388a2b612daf875e2fe8df62990e14b64a465898b0707bc1288586b68f9f4f2f20bea5cb1cada296beb8009e91bc8fb57a4b81b8923299b6eb7
```

### Go

```go
package main

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/hex"
	"encoding/pem"
	"fmt"
	"time"
)

func main() {
	result, err := getCorrespondPath(time.Now().UnixMilli())
	if err != nil {
		panic(err)
	}
	fmt.Println(result)
}

func getCorrespondPath(ts int64) (string, error) {
	const publicKeyPEM = `
-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg
Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71
nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40
JNrRuoEUXpabUzGB8QIDAQAB
-----END PUBLIC KEY-----
`
	pubKeyBlock, _ := pem.Decode([]byte(publicKeyPEM))
	hash := sha256.New()
	random := rand.Reader
	msg := []byte(fmt.Sprintf("refresh_%d", ts))
	var pub *rsa.PublicKey
	pubInterface, parseErr := x509.ParsePKIXPublicKey(pubKeyBlock.Bytes)
	if parseErr != nil {
		return "", parseErr
	}
	pub = pubInterface.(*rsa.PublicKey)
	encryptedData, encryptErr := rsa.EncryptOAEP(hash, random, pub, msg, nil)
	if encryptErr != nil {
		return "", encryptErr
	}
	return hex.EncodeToString(encryptedData), nil
}
```

```text
97759947aa357ed5d88cf9bf1172737570b7bba2d6788d39006f082b2b25ddf53b581f1f0c61ed8573317485ef525d2789faa25a277b4602a4b9cbf837681093a03e96cb9773a11df4bb1e20f1587180b3e958194de922d7dd94d0a2f0b9b0ef74e426e8041f99b99e7c02407ef4ab38040e61be81e4fdfbdb73461e3a2ad810
```

### Java

```Java
import javax.crypto.Cipher;
import javax.crypto.spec.OAEPParameterSpec;
import javax.crypto.spec.PSource;
import java.math.BigInteger;
import java.security.KeyFactory;
import java.security.PublicKey;
import java.security.spec.MGF1ParameterSpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;

public class CookieRefresh {
    private static final String PUBLIC_KEY = "-----BEGIN PUBLIC KEY-----\n" +
            "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDLgd2OAkcGVtoE3ThUREbio0Eg\n" +
            "Uc/prcajMKXvkCKFCWhJYJcLkcM2DKKcSeFpD/j6Boy538YXnR6VhcuUJOhH2x71\n" +
            "nzPjfdTcqMz7djHum0qSZA0AyCBDABUqCrfNgCiJ00Ra7GmRj+YCK1NJEuewlb40\n" +
            "JNrRuoEUXpabUzGB8QIDAQAB\n" +
            "-----END PUBLIC KEY-----";

    public static void main(String[] args) {
        try {
            String correspondPath = getCorrespondPath(String.format("refresh_%d", System.currentTimeMillis()), PUBLIC_KEY);
            System.out.println(correspondPath);
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    public static String getCorrespondPath(String plaintext, String publicKeyStr) throws Exception {
        KeyFactory keyFactory = KeyFactory.getInstance("RSA");
        publicKeyStr = publicKeyStr
                .replace("-----BEGIN PUBLIC KEY-----", "")
                .replace("-----END PUBLIC KEY-----", "")
                .replace("\n", "")
                .trim();
        byte[] publicBytes = Base64.getDecoder().decode(publicKeyStr);
        X509EncodedKeySpec x509EncodedKeySpec = new X509EncodedKeySpec(publicBytes);
        PublicKey publicKey = keyFactory.generatePublic(x509EncodedKeySpec);

        String algorithm = "RSA/ECB/OAEPPadding";
        Cipher cipher = Cipher.getInstance(algorithm);
        cipher.init(Cipher.ENCRYPT_MODE, publicKey);

        // Encode the plaintext to bytes
        byte[] plaintextBytes = plaintext.getBytes("UTF-8");

        // Add OAEP padding to the plaintext bytes
        OAEPParameterSpec oaepParams = new OAEPParameterSpec("SHA-256", "MGF1", MGF1ParameterSpec.SHA256, PSource.PSpecified.DEFAULT);
        cipher.init(Cipher.ENCRYPT_MODE, publicKey, oaepParams);
        // Encrypt the padded plaintext bytes
        byte[] encryptedBytes = cipher.doFinal(plaintextBytes);
        // Convert the encrypted bytes to a Base64-encoded string
        return new BigInteger(1, encryptedBytes).toString(16);
    }
}
```

```text
f87666152da692735123f4e49053e5a98c16854673b2e632f31a3ff0c029640772873661a9a8412db6be447a0bfa03a295d15548cbfd2bb35634e98ba5f25b1205519d6e6119b483f4c516c1e106d45b04ff98c73560949d379d3edaf3c0ecd10a1d46134fb9ca443122ab33c16d1dd48280496f949ed960a2fbcd65f10935e
```

#### vercel浜戝嚱鏁?
```bash
curl -G 'https://wasm-rsa.vercel.app/api/rsa' \
	--data-urlencode "t=$((`date '+%s'`*1000+`date '+%N'`/1000000))"
```

```json
{
    "timestamp": "1684468084078",
    "hash": "a768efe5114ef8610f9ed9ebc28c00827375f4a3448ec4ab17958cacc4fde9898e5b7aa27f649426bba1acae4aa222aafaff7d528669b15249de0b2b60d86618557d8dc90684db4ec68e8d98e41d94f1c97d1d431c288e595ceb522d033822442a9e1ee150b32771a83fbf65c13329e9fda080fbe3bc85c49c1de7ab148d228f",
    "code": 0
}
```

## 鑾峰彇refresh_csrf

> https://www.bilibili.com/correspond/1/{correspondPath}

*璇锋眰鏂瑰紡锛欸ET*

閴存潈鏂瑰紡锛欳ookie

**path 鍙傛暟锛?*

| 鍙傛暟鍚?        | 绫诲瀷 | 鍐呭                         | 蹇呰鎬?| 澶囨敞                                                         |
| -------------- | ---- | ---------------------------- | ------ | ------------------------------------------------------------ |
| correspondPath | str  | 浣跨敤褰撳墠姣鏃堕棿鎴崇敓鎴愮殑绛惧悕 | 蹇呰   | 鐢?[鐢熸垚CorrespondPath绠楁硶](#鐢熸垚CorrespondPath绠楁硶) 鍔犲瘑鑾峰緱 |

灏嗗弬鏁癭correspondPath`鎷兼帴鍦?https://www.bilibili.com/correspond/1/ 鍚庤繘琛岃姹傦紝渚嬪

> https://www.bilibili.com/correspond/1/0248397e5139a8b878894cae46f8d6742ef7c728e46403706452b5dda90fe248e58e73bd6c2da0dba515c53af107dc1ecda757ce843579bcf197fcd7800586126e9b896b646cc94c23183a5a067642e96f7b6e803880e1d3cceabc9f1dc52a121b5e3ba5619e008f6b6dcb65a09d7864084ac114f4ec9ccf6218776fe4f2fa95

璇锋眰璇?url 浼氳繑鍥炰竴涓?html 椤甸潰锛岄€氬父鐢?iframe 鏂瑰紡鍔犺浇锛屽畠閫氳繃 SSR 鏂瑰紡杩斿洖涓€涓疄鏃跺埛鏂板彛浠refresh_csrf`瀛樻斁浜?html 鏍囩涓紝骞跺湪 Client 绔€氳繃 js 璇锋眰 RestAPI 瀹屾垚涓€浜涘垪鐨勬彁浜ゅ埛鏂般€佺‘璁ゃ€丼SO 绔欑偣鐧诲綍绛夋搷浣?
鑻ュ弬鏁癭correspondPath`閿欒鎴栬繃鏈燂紝鍒欒繑鍥炰竴涓?404 Page

浠ヤ笅涓鸿繑鍥炵殑鍙傛暟锛?
| 鏍囩 id | 鍐呭         | xpath                     | 澶囨敞                              |
| ------- | ------------ | ------------------------- | --------------------------------- |
| 1-name  | refresh_csrf | //div[id='1-name']/text() | 瀹炴椂鍒锋柊鍙ｄ护<br />鐢ㄤ簬鏇存柊 Cookie |

**绀轰緥锛?*

```bash
correspondPath='0248397e5139a8b878894cae46f8d6742ef7c728e46403706452b5dda90fe248e58e73bd6c2da0dba515c53af107dc1ecda757ce843579bcf197fcd7800586126e9b896b646cc94c23183a5a067642e96f7b6e803880e1d3cceabc9f1dc52a121b5e3ba5619e008f6b6dcb65a09d7864084ac114f4ec9ccf6218776fe4f2fa95'

curl -G "https://www.bilibili.com/correspond/1/$correspondPath" \
	-b 'SESSDATA=xxx'
```

```html
<!DOCTYPE html>
<html lang="zh-Hans">

<head>
  <meta name="spm_prefix" content="333.1193">
  <link
    href="//s1.hdslb.com/bfs/static/jinkela/token-iframe/css/token-iframe.1.a035e81c3bee5fa1a05633ad534ad1f44b05e54d.css"
    rel="stylesheet">
</head>
<title>Correspond</title>
<script type="text/javascript"
  src="//www.bilibili.com/gentleman/polyfill.js?features=Promise%2CObject.assign%2CString.prototype.includes%2CNumber.isNaN2%CglobalThis"></script>

<body>
  <div id="1-name">b0cc8411ded2f9db2cff2edb3123acac</div>
  <div id="token-iframe-app"></div>
  <script type="text/javascript"
    src="//s1.hdslb.com/bfs/static/jinkela/token-iframe/2.token-iframe.a035e81c3bee5fa1a05633ad534ad1f44b05e54d.js"></script>
  <script type="text/javascript"
    src="//s1.hdslb.com/bfs/static/jinkela/token-iframe/token-iframe.a035e81c3bee5fa1a05633ad534ad1f44b05e54d.js"></script>
</body>
<script type="text/javascript">window.reportMsgObj = {};
  window.reportConfig = {
    sample: 1,
    scrollTracker: true,
    msgObjects: 'reportMsgObj',
  };

  let reportScript = document.createElement('script');
  reportScript.src = '//s1.hdslb.com/bfs/seed/log/report/log-reporter.js';
  document.getElementsByTagName('body')[0].appendChild(reportScript);</script>

</html>
```

鎵€浠ュ綋鍓嶈处鍙风殑瀹炴椂鍒锋柊鍙ｄ护`refresh_csrf`涓篳b0cc8411ded2f9db2cff2edb3123acac`

## 鍒锋柊Cookie

> https://passport.bilibili.com/x/passport-login/web/cookie/refresh

*璇锋眰鏂瑰紡锛歅OST*

閴存潈鏂瑰紡锛欳ookie

鍒锋柊鎴愬姛鍚庝細璁剧疆浠ヤ笅 Cookie 椤癸細

`sid`銆乣DedeUserID`銆乣DedeUserID__ckMd5`銆乣SESSDATA`銆乣bili_jct`

**姝ｆ枃鍙傛暟 (application/x-www-form-urlencoded)鎴?url 鍙傛暟锛?*

| 鍙傛暟鍚?       | 绫诲瀷 | 鍐呭           | 蹇呰鎬?| 澶囨敞                                                         |
| ------------- | ---- | -------------- | ------ | ------------------------------------------------------------ |
| csrf          | str  | CSRF Token     | 蹇呰   | 浣嶄簬 Cookie 涓殑`bili_jct`瀛楁                               |
| refresh_csrf  | str  | 瀹炴椂鍒锋柊鍙ｄ护   | 蹇呰   | 閫氳繃 [鑾峰彇refresh_csrf](#鑾峰彇refresh_csrf) 鑾峰緱              |
| source        | str  | 璁块棶鏉ユ簮锛?    | 蹇呰   | 涓€鑸负`main_web`                                             |
| refresh_token | str  | 鎸佷箙鍖栧埛鏂板彛浠?| 蹇呰   | localStorage 涓殑`ac_time_value`瀛楁锛屽湪鐧诲綍鎴愬姛鍚庤繑鍥炲苟淇濆瓨 |

**json 鍥炲锛?*

鏍瑰璞★細

| 瀛楁    | 绫诲瀷 | 鍐呭     | 澶囨敞                                                         |
| ------- | ---- | -------- | ------------------------------------------------------------ |
| code    | num  | 杩斿洖鍊?  | 0锛氭垚鍔?br />-101锛氳处鍙锋湭鐧诲綍<br />-111锛歝srf 鏍￠獙澶辫触<br />86095锛歳efresh_csrf 閿欒鎴?refresh_token 涓?cookie 涓嶅尮閰?|
| message | str  | 閿欒淇℃伅 | 榛樿涓?0                                                     |
| ttl     | num  | 1        |                                                              |
| data    | obj  | 淇℃伅鏈綋 |                                                              |

`data`瀵硅薄锛?
| 瀛楁          | 绫诲瀷 | 鍐呭               | 澶囨敞                                                        |
| ------------- | ---- | ------------------ | ----------------------------------------------------------- |
| status        | num  | 0                  |                                                             |
| message       | str  | 绌?                |                                                             |
| refresh_token | str  | 鏂扮殑鎸佷箙鍖栧埛鏂板彛浠?| 灏嗗瓨鍌ㄤ簬 localStorage 涓殑`ac_time_value`瀛楁锛屼互渚夸笅娆′娇鐢?|

**绀轰緥锛?*

```bash
curl -i 'https://passport.bilibili.com/x/passport-login/web/cookie/refresh' \
	--data-urlencode 'csrf=f610640a37f51f6266f6b83cfc5eedbb' \
	--data-urlencode 'refresh_csrf=b0cc8411ded2f9db2cff2edb3123acac' \
	--data-urlencode 'source=main_web' \
	--data-urlencode 'refresh_token=45240a041836905fe953e3b98b83d751' \
	-b 'SESSDATA=xxx'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

http 鍝嶅簲锛堝叧閿俊鎭凡鍋氳劚鏁忓鐞嗭級锛?
```http
HTTP/2 200
date: Fri, 19 May 2023 07:34:11 GMT
content-type: application/json; charset=utf-8
content-length: 116
bili-status-code: 0
bili-trace-id: 17f4251365646726
set-cookie: SESSDATA=***; Path=/; Domain=bilibili.com; Expires=Wed, 15 Nov 2023 07:34:10 GMT; HttpOnly; Secure
set-cookie: bili_jct=***; Path=/; Domain=bilibili.com; Expires=Wed, 15 Nov 2023 07:34:10 GMT
set-cookie: DedeUserID=***; Path=/; Domain=bilibili.com; Expires=Wed, 15 Nov 2023 07:34:10 GMT
set-cookie: DedeUserID__ckMd5=***; Path=/; Domain=bilibili.com; Expires=Wed, 15 Nov 2023 07:34:10 GMT
set-cookie: sid=***; Path=/; Domain=bilibili.com; Expires=Wed, 15 Nov 2023 07:34:10 GMT
x-bili-trace-id: 3f6f6174aaa087b517f4251365646726
expires: Fri, 19 May 2023 07:34:10 GMT
cache-control: no-cache
x-cache-webcdn: BYPASS from blzone03

{"code":0,"message":"0","ttl":1,"data":{"status":0,"message":"","refresh_token":"ae1bd1149b56af9743ffe7bbbeff3e51"}}
```

JSON Payload锛?
```json
{
    "code": 0,
    "message": "0",
    "ttl": 1,
    "data": {
        "status": 0,
        "message": "",
        "refresh_token": "ae1bd1149b56af9743ffe7bbbeff3e51"
    }
}
```

</details>

## 纭鏇存柊

> https://passport.bilibili.com/x/passport-login/web/confirm/refresh

*璇锋眰鏂瑰紡锛歅OST*

閴存潈鏂瑰紡锛欳ookie

璇ユ鎿嶄綔灏嗚鏃х殑`refresh_token`瀵瑰簲鐨?Cookie 澶辨晥

**姝ｆ枃鍙傛暟 (application/x-www-form-urlencoded)鎴?url 鍙傛暟锛?*

| 鍙傛暟鍚?       | 绫诲瀷 | 鍐呭                      | 蹇呰鎬?| 澶囨敞                                                         |
| ------------- | ---- | ------------------------- | ------ | ------------------------------------------------------------ |
| csrf          | str  | CSRF Token锛堜綅浜?cookie锛?| 蹇呰   | 浠庢柊鐨?cookie 涓幏鍙栵紝浣嶄簬 Cookie 涓殑`bili_jct`瀛楁               |
| refresh_token | str  | 鏃х殑鎸佷箙鍖栧埛鏂板彛浠?       | 蹇呰   | 鍦ㄥ埛鏂板墠 localStorage 涓殑`ac_time_value`鑾峰彇锛?*骞堕潪鍒锋柊鍚庤繑鍥炵殑鍊?* |

**json 鍥炲锛?*

鏍瑰璞★細

| 瀛楁    | 绫诲瀷 | 鍐呭     | 澶囨敞                                                         |
| ------- | ---- | -------- | ------------------------------------------------------------ |
| code    | num  | 杩斿洖鍊?  | 0锛氭垚鍔?br />-101锛氳处鍙锋湭鐧诲綍<br />-111锛歝srf 鏍￠獙澶辫触<br />-400锛氳姹傞敊璇?|
| message | str  | 閿欒淇℃伅 | 榛樿涓?0                                                     |
| ttl     | num  | 1        |                                                              |

**绀轰緥锛?*

```bash
curl 'https://passport.bilibili.com/x/passport-login/web/confirm/refresh' \
	--data-urlencode 'csrf=1e9658858e6da76be64bd92cdc0fa324' \
	--data-urlencode 'refresh_token=45240a041836905fe953e3b98b83d751' \
	-b 'SESSDATA=xxx'
```

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥锛?/summary>

```json
{
    "code": 0,
    "message": "0",
    "ttl": 1
}
```

</details>
