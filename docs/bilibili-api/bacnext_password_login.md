# 密码登录

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /x/passport-login/web/login:
    post:
      summary: 密码登录
      deprecated: false
      description: >-
        本接口需要先[申请验证码](https://bacnext.apifox.cn/412263926e0.md)和[获取公钥&盐](https://bacnext.apifox.cn/412887455e0.md)


        密码加密伪代码如下


        ```

        pubkey, salt = get_pubkey_and_salt()

        password = base64_encode(RSA_encrypt(pubkey, salt+plain_password))

        ```


        此登录方式**在极大部分情况下**均需要进行二次验证，因此**除非必要，不建议使用此登录方式**。
      tags:
        - Web
      parameters: []
      requestBody:
        content:
          application/x-www-form-urlencoded:
            schema:
              type: object
              properties:
                username:
                  example: ''
                  type: string
                password:
                  description: 加密后的base64值，加密方法请见说明
                  example: ''
                  type: string
                validate:
                  example: b3e6e5c4062374b565d92454276129b2
                  type: string
                token:
                  example: cc1478768283489aa548c8003e7b5ad1
                  type: string
                seccode:
                  example: b3e6e5c4062374b565d92454276129b2|jordan
                  type: string
                challenge:
                  example: 6fe815503cd3daaf3faf67c655739906
                  type: string
                go_url:
                  example: ''
                  type: string
              required:
                - username
                - password
                - validate
                - token
                - seccode
                - challenge
            examples: {}
      responses:
        '200':
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                  message:
                    type: string
                  ttl:
                    type: integer
                  data:
                    type: object
                    properties:
                      status:
                        type: integer
                      message:
                        type: string
                      url:
                        type: string
                      refresh_token:
                        type: string
                      timestamp:
                        type: integer
                    required:
                      - status
                      - message
                      - url
                      - refresh_token
                      - timestamp
                    x-apifox-orders:
                      - status
                      - message
                      - url
                      - refresh_token
                      - timestamp
                required:
                  - code
                  - message
                  - ttl
                  - data
                x-apifox-orders:
                  - code
                  - message
                  - ttl
                  - data
              examples:
                '1':
                  summary: 密码时间戳过期
                  value:
                    code: -662
                    message: 密码时间戳过期
                    ttl: 1
                    data: null
                '2':
                  summary: 验证码错误
                  value:
                    code: -105
                    message: 验证码错误
                    ttl: 1
                    data: null
                '3':
                  summary: 用户名或密码错误
                  value:
                    code: -629
                    message: 用户名或密码错误
                    ttl: 1
                    data: null
                '4':
                  summary: 需要手机号验证
                  value:
                    code: 0
                    message: '0'
                    ttl: 1
                    data:
                      is_new: false
                      status: 2
                      message: 本次登录环境存在风险, 需使用手机号进行验证或绑定
                      url: >-
                        https://passport.bilibili.com/h5-app/passport/risk/verify?gourl=https%3A%2F%2Fwww.bilibili.com%2F&request_id=00000000000000000000000000000000&source=risk&tmp_token=00000000000000000000000000000000
                      refresh_token: ''
                      timestamp: 0
                      hint: ''
                      in_reg_audit: 0
                '5':
                  summary: 成功示例
                  value:
                    code: 0
                    message: '0'
                    ttl: 1
                    data:
                      status: 0
                      message: ''
                      url: >-
                        https://passport.biligame.com/crossDomain?DedeUserID=***&DedeUserID__ckMd5=***&Expires=***&SESSDATA=***&bili_jct=***&gourl=https%3A%2F%2Fwww.bilibili.com%2F
                      refresh_token: '***'
                      timestamp: 1662452570273
          headers: {}
          x-apifox-name: 成功
      security: []
      x-apifox-folder: ''
      x-apifox-status: released
      x-run-in-apifox: https://app.apifox.com/web/project/7776376/apis/api-412887534-run
components:
  schemas: {}
  securitySchemes: {}
servers:
  - url: https://api.bilibili.com
    description: 正式环境
security: []

```
