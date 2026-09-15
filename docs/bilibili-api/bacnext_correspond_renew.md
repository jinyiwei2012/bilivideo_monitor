# 主站 Correspond 续期

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /correspond/1/{correspondPath}:
    get:
      summary: 主站 Correspond 续期
      deprecated: false
      description: ''
      tags: []
      parameters:
        - name: correspondPath
          in: path
          description: ''
          required: true
          schema:
            type: string
      responses:
        '200':
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties: {}
          headers: {}
          x-apifox-name: 成功
      security: []
      x-apifox-folder: ''
      x-apifox-status: developing
      x-run-in-apifox: https://app.apifox.com/web/project/7776376/apis/api-413629293-run
components:
  schemas: {}
  securitySchemes: {}
servers:
  - url: https://api.bilibili.com
    description: 正式环境
security: []

```
