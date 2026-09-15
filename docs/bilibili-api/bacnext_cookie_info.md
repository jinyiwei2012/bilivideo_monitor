# 检查是否需要刷新 Cookie

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /x/passport-login/web/cookie/info:
    get:
      summary: 检查是否需要刷新 Cookie
      deprecated: false
      description: ''
      tags: []
      parameters:
        - name: SESSDATA
          in: cookie
          description: ''
          required: true
          example: ''
          schema:
            type: string
        - name: csrf
          in: query
          description: ''
          required: false
          schema:
            type: string
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
                    description: |-
                      `0`: 成功
                      `-101`:`账号未登录
                  message:
                    type: string
                    x-apifox-mock: '0'
                  ttl:
                    type: integer
                    x-apifox-mock: '1'
                  data:
                    type: object
                    properties:
                      refresh:
                        type: boolean
                        description: |-
                          `true`: 需要刷新
                          `false`: 不需要刷新
                      timestamp:
                        type: integer
                        x-apifox-mock: '{{$date.timestamp}}'
                    x-apifox-orders:
                      - refresh
                      - timestamp
                    required:
                      - refresh
                      - timestamp
                    nullable: true
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
                  summary: 成功示例
                  value:
                    code: 0
                    message: '0'
                    ttl: 1
                    data:
                      refresh: false
                      timestamp: 1684466082562
                '2':
                  summary: 账号未登录
                  value:
                    code: -101
                    message: 账号未登录
                    ttl: 1
                    data: null
          headers: {}
          x-apifox-name: 成功
      security: []
      x-apifox-folder: ''
      x-apifox-status: developing
      x-run-in-apifox: https://app.apifox.com/web/project/7776376/apis/api-412267738-run
components:
  schemas: {}
  securitySchemes: {}
servers:
  - url: https://api.bilibili.com
    description: 正式环境
security: []

```
