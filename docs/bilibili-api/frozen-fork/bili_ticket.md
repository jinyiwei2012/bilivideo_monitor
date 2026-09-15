# BiliTicket

## 绠€杩?
`bili_ticket` 浣嶄簬璇锋眰澶?Cookie 涓? 闈炲繀闇€, 浣嗗瓨鍦ㄥ彲闄嶄綆椋庢帶姒傜巼

鐢?[@aynuarance](https://github.com/aynuarance) 浜?[#903](https://github.com/SocialSisterYi/bilibili-API-collect/issues/903) 鎻愪緵鐨勬€濊矾锛屾牴鎹椂闂存埑浣跨敤 `hmac_sha256` 绠楁硶璁＄畻 `hexsign`銆?
鏄?[JWT 浠ょ墝](https://jwt.io/)锛屾湁鏁堟椂闀夸负 259260 绉掞紝鍗?3 澶┿€?渚嬪 `eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3MDI3NDI3NDYsImlhdCI6MTcwMjQ4MzQ4NiwicGx0IjotMX0.xQgtTAc41NA1gzvd9yKUPgucUy_DKcQj6OG1vj8V7ZA`

```json
{
  "alg": "HS256",
  "kid": "s03",
  "typ": "JWT"
}
```

## 绠楁硶

1. 鑾峰彇 UNIX 绉掔骇鏃堕棿鎴冲瓨鍏ュ彉閲忓 `timestamp`
2. 璁＄畻鍙橀噺 `hexsign` 鍊硷紝浣跨敤 `hmac_sha256` 绠楁硶锛屽瘑閽ヤ负 `XgwSnGZ1p`锛屾秷鎭负瀛楃涓?`"ts"` 涓庡彉閲?`timestamp` 鍊兼嫾鎺?3. 鏋勯€犺姹傚弬鏁帮紝`key_id` 涓?`ec02`锛宍hexsign` 涓哄彉閲?`hexsign` 鍊硷紝`context[ts]` 涓哄彉閲?`timestamp` 鍊硷紝`csrf` 涓?cookie 涓殑 `bili_jct` 鍊间篃鍙负绌?4. 鍙戦€?`POST` 璇锋眰锛岃幏鍙?`data` 瀛楁涓殑 `ticket` 瀛楁鐨勫€煎嵆涓烘墍姹?
## 鎺ュ彛

> https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket

*璇锋眰鏂瑰紡: POST*

閴存潈鏂瑰紡: 璇锋眰澶?`Referer` 涓虹┖鎴?`.bilibili.com` 瀛愬煙涓嬩换鎰忛〉

**URL鍙傛暟:**

| 鍙傛暟鍚?| 绫诲瀷 | 鍐呭 | 蹇呰鎬?| 澶囨敞 |
| ----- | ---- | ---- | ------ | ---- |
| key_id | str | ec02 | 蹇呰 |      |
| hexsign | str | 鐢?`hmac_sha256` 绠楁硶璁＄畻鐨?`hexsign` 鍊?| 蹇呰 |      |
| context[ts] | num | UNIX 绉掔骇鏃堕棿鎴?| 蹇呰 |      |
| csrf | str | cookie 涓殑 `bili_jct` 鍊?| 闈炲繀瑕?|      |

**JSON鍥炲:**

鏍瑰璞?

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| ---- | ---- | ---- | ---- |
| code | num | 杩斿洖鍊?| 0: 鎴愬姛<br />400: 鍙傛暟閿欒 |
| message | str | 杩斿洖娑堟伅 | OK: 鎴愬姛 |
| data | obj | 鏁版嵁鏈綋 | |
| ttl | num | 1 |  |

`data` 瀵硅薄:

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| ---- | ---- | ---- | ---- |
| ticket | str | bili_ticket | |
| created_at | num | 鍒涘缓鏃堕棿 | UNIX 绉掔骇鏃堕棿鎴?|
| ttl | num | 鏈夋晥鏃堕暱 | 259200 绉?(3 澶? |
| context | obj | 绌?|  |
| nav | obj | wbi_img 鐩稿叧 | 鍙傝 [WBI 绛惧悕](./wbi.md) |

`nav` 瀵硅薄:

| 瀛楁 | 绫诲瀷 | 鍐呭 | 澶囨敞 |
| ---- | ---- | ---- | ---- |
| img | str | img_key 鍊?| 鍙傝 [WBI 绛惧悕](./wbi.md) |
| sub | str | sub_key 鍊?| 鍙傝 [WBI 绛惧悕](./wbi.md) |

**绀轰緥:**

<details>
<summary>鏌ョ湅鍝嶅簲绀轰緥:</summary>

```json
{
  "code": 0,
  "message": "OK",
  "data": {
    "ticket": "eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3MjM2OTMwODAsImlhdCI6MTcyMzQzMzgyMCwicGx0IjotMX0.efOwv7i4m0ykABrXEDHGAechU2AByMcP_-3EYpQrNKs",
    "created_at": 1723433820,
    "ttl": 259200,
    "context": {},
    "nav": {
      "img": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
      "sub": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png"
    }
  },
  "ttl": 1
}
```

</details>

## Demo

姝ゅ鎻愪緵 [Python](#python), [Java](#java), [JavaScript (Node.js)](#javascript-nodejs) 鐨勭ず渚嬩唬鐮?
### Python

闇€瑕?`requests` 渚濊禆

```python
import hmac
import hashlib
import requests
import time

def hmac_sha256(key, message):
    """
    浣跨敤HMAC-SHA256绠楁硶瀵圭粰瀹氱殑娑堟伅杩涜鍔犲瘑
    :param key: 瀵嗛挜
    :param message: 瑕佸姞瀵嗙殑娑堟伅
    :return: 鍔犲瘑鍚庣殑鍝堝笇鍊?    """
    # 灏嗗瘑閽ュ拰娑堟伅杞崲涓哄瓧鑺備覆
    key = key.encode('utf-8')
    message = message.encode('utf-8')

    # 鍒涘缓HMAC瀵硅薄锛屼娇鐢⊿HA256鍝堝笇绠楁硶
    hmac_obj = hmac.new(key, message, hashlib.sha256)

    # 璁＄畻鍝堝笇鍊?    hash_value = hmac_obj.digest()

    # 灏嗗搱甯屽€艰浆鎹负鍗佸叚杩涘埗瀛楃涓?    hash_hex = hash_value.hex()

    return hash_hex


if __name__ == '__main__':
    o = hmac_sha256("XgwSnGZ1p",f"ts{int(time.time())}")
    url = "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket"
    params = {
        "key_id":"ec02",
        "hexsign":o,
        "context[ts]":f"{int(time.time())}",
        "csrf": ''
    }

    headers = {
            'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
        }
    resp = requests.post(url, params=params,headers=headers).json()
    print(resp)
```

### Java

鏃犻渶绗笁鏂逛緷璧?
```java
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

public class BiliTicketDemo {

    /**
     * Convert a byte array to a hex string.
     * 
     * @param bytes The byte array to convert.
     * @return The hex string representation of the given byte array.
     */
    public static String bytesToHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder();
        for (byte b : bytes) {
            String hex = Integer.toHexString(0xff & b);
            if (hex.length() == 1) {
                sb.append('0');
            }
            sb.append(hex);
        }
        return sb.toString();
    }

    /**
     * Generate a HMAC-SHA256 hash of the given message string using the given key
     * string.
     * 
     * @param key     The key string to use for the HMAC-SHA256 hash.
     * @param message The message string to hash.
     * @throws Exception If an error occurs during the HMAC-SHA256 hash generation.
     * @return The HMAC-SHA256 hash of the given message string using the given key
     *         string.
     */
    public static String hmacSha256(String key, String message) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        SecretKeySpec secretKeySpec = new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
        mac.init(secretKeySpec);
        byte[] hash = mac.doFinal(message.getBytes(StandardCharsets.UTF_8));
        return bytesToHex(hash);
    }

    /**
     * Get a Bilibili web ticket for the given CSRF token.
     * 
     * @param csrf The CSRF token to use for the web ticket, can be {@code null} or
     *             empty.
     * @return The Bilibili web ticket raw response for the given CSRF token.
     * @throws Exception If an error occurs during the web ticket generation.
     * @see https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/misc/sign/bili_ticket.md
     */
    public static String getBiliTicket(String csrf) throws Exception {
        // params
        long ts = System.currentTimeMillis() / 1000;
        String hexSign = hmacSha256("XgwSnGZ1p", "ts" + ts);
        StringBuilder url = new StringBuilder(
                "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket");
        url.append('?');
        url.append("key_id=ec02").append('&');
        url.append("hexsign=").append(hexSign).append('&');
        url.append("context[ts]=").append(ts).append('&');
        url.append("csrf=").append(csrf == null ? "" : csrf);
        // request
        HttpURLConnection conn = (HttpURLConnection) new URI(url.toString()).toURL().openConnection();
        conn.setRequestMethod("POST");
        conn.addRequestProperty("User-Agent", "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0");
        InputStream in = conn.getInputStream();
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        int b;
        while ((b = in.read()) != -1) {
            out.write(b);
        }
        return new String(out.toByteArray(), StandardCharsets.UTF_8);
    }

    /**
     * Main method to test the BiliTicketDemo class.
     * 
     * @param args The command line arguments (not used).
     */
    public static void main(String[] args) {
        try {
            System.out.println(getBiliTicket("")); // use empty CSRF here
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

}
```

### JavaScript (Node.js)

```javascript
const crypto = require('crypto');

/**
 * Generate HMAC-SHA256 signature
 * @param {string} key     The key string to use for the HMAC-SHA256 hash
 * @param {string} message The message string to hash
 * @returns {string} The HMAC-SHA256 signature as a hex string
 */
function hmacSha256(key, message) {
    const hmac = crypto.createHmac('sha256', key);
    hmac.update(message);
    return hmac.digest('hex');
}

/**
 * Get Bilibili web ticket
 * @param {string} csrf    CSRF token, can be empty or null
 * @returns {Promise<any>} Promise of the ticket response in JSON format
 */
async function getBiliTicket(csrf) {
    const ts = Math.floor(Date.now() / 1000);
    const hexSign = hmacSha256('XgwSnGZ1p', `ts${ts}`);
    const url = 'https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket';
    const params = new URLSearchParams({
        key_id: 'ec02',
        hexsign: hexSign,
        'context[ts]': ts,
        csrf: csrf || ''
    });
    const response = await fetch(`${url}?${params.toString()}`, {
        method: 'POST',
        headers: {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0'
        }
    });
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json();
}

(async () => {
    try {
        const ticketResponse = await getBiliTicket(''); // use empty CSRF here
        console.log(ticketResponse);
    } catch (e) {
        console.error('Failed to get BiliTicket:', e);
    }
})();
```
