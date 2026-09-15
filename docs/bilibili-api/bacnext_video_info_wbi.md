# 视频信息

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /x/web-interface/wbi/view:
    get:
      summary: 视频信息
      deprecated: false
      description: ''
      tags:
        - 主站/Web 界面/Wbi
        - Wbi
      parameters:
        - name: aid
          in: query
          description: aid和bvid任选其一
          required: false
          example: '1700001'
          schema:
            type: string
        - name: bvid
          in: query
          description: aid和bvid任选其一
          required: false
          example: ''
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
                  message:
                    type: string
                  ttl:
                    type: integer
                  data:
                    type: object
                    properties:
                      bvid:
                        type: string
                      aid:
                        type: integer
                      videos:
                        type: integer
                      tid:
                        type: integer
                      tid_v2:
                        type: integer
                      tname:
                        type: string
                      tname_v2:
                        type: string
                      copyright:
                        type: integer
                      pic:
                        type: string
                      title:
                        type: string
                      pubdate:
                        type: integer
                      ctime:
                        type: integer
                      desc:
                        type: string
                      desc_v2:
                        type: array
                        items:
                          type: object
                          properties:
                            raw_text:
                              type: string
                            type:
                              type: integer
                            biz_id:
                              type: integer
                          x-apifox-orders:
                            - raw_text
                            - type
                            - biz_id
                      state:
                        type: integer
                      duration:
                        type: integer
                      mission_id:
                        type: integer
                      rights:
                        type: object
                        properties:
                          bp:
                            type: integer
                          elec:
                            type: integer
                          download:
                            type: integer
                          movie:
                            type: integer
                          pay:
                            type: integer
                          hd5:
                            type: integer
                          no_reprint:
                            type: integer
                          autoplay:
                            type: integer
                          ugc_pay:
                            type: integer
                          is_cooperation:
                            type: integer
                          ugc_pay_preview:
                            type: integer
                          no_background:
                            type: integer
                          clean_mode:
                            type: integer
                          is_stein_gate:
                            type: integer
                          is_360:
                            type: integer
                          no_share:
                            type: integer
                          arc_pay:
                            type: integer
                          free_watch:
                            type: integer
                        required:
                          - bp
                          - elec
                          - download
                          - movie
                          - pay
                          - hd5
                          - no_reprint
                          - autoplay
                          - ugc_pay
                          - is_cooperation
                          - ugc_pay_preview
                          - no_background
                          - clean_mode
                          - is_stein_gate
                          - is_360
                          - no_share
                          - arc_pay
                          - free_watch
                        x-apifox-orders:
                          - bp
                          - elec
                          - download
                          - movie
                          - pay
                          - hd5
                          - no_reprint
                          - autoplay
                          - ugc_pay
                          - is_cooperation
                          - ugc_pay_preview
                          - no_background
                          - clean_mode
                          - is_stein_gate
                          - is_360
                          - no_share
                          - arc_pay
                          - free_watch
                      owner:
                        type: object
                        properties:
                          mid:
                            type: integer
                          name:
                            type: string
                          face:
                            type: string
                        required:
                          - mid
                          - name
                          - face
                        x-apifox-orders:
                          - mid
                          - name
                          - face
                      stat:
                        type: object
                        properties:
                          aid:
                            type: integer
                          view:
                            type: integer
                          danmaku:
                            type: integer
                          reply:
                            type: integer
                          favorite:
                            type: integer
                          coin:
                            type: integer
                          share:
                            type: integer
                          now_rank:
                            type: integer
                          his_rank:
                            type: integer
                          like:
                            type: integer
                          dislike:
                            type: integer
                          evaluation:
                            type: string
                          vt:
                            type: integer
                        required:
                          - aid
                          - view
                          - danmaku
                          - reply
                          - favorite
                          - coin
                          - share
                          - now_rank
                          - his_rank
                          - like
                          - dislike
                          - evaluation
                          - vt
                        x-apifox-orders:
                          - aid
                          - view
                          - danmaku
                          - reply
                          - favorite
                          - coin
                          - share
                          - now_rank
                          - his_rank
                          - like
                          - dislike
                          - evaluation
                          - vt
                      argue_info:
                        type: object
                        properties:
                          argue_msg:
                            type: string
                          argue_type:
                            type: integer
                          argue_link:
                            type: string
                        required:
                          - argue_msg
                          - argue_type
                          - argue_link
                        x-apifox-orders:
                          - argue_msg
                          - argue_type
                          - argue_link
                      dynamic:
                        type: string
                      cid:
                        type: integer
                      dimension:
                        type: object
                        properties:
                          width:
                            type: integer
                          height:
                            type: integer
                          rotate:
                            type: integer
                        required:
                          - width
                          - height
                          - rotate
                        x-apifox-orders:
                          - width
                          - height
                          - rotate
                      premiere:
                        type: 'null'
                      teenage_mode:
                        type: integer
                      is_chargeable_season:
                        type: boolean
                      is_story:
                        type: boolean
                      is_upower_exclusive:
                        type: boolean
                      is_upower_play:
                        type: boolean
                      is_upower_preview:
                        type: boolean
                      enable_vt:
                        type: integer
                      vt_display:
                        type: string
                      is_upower_exclusive_with_qa:
                        type: boolean
                      no_cache:
                        type: boolean
                      pages:
                        type: array
                        items:
                          type: object
                          properties:
                            cid:
                              type: integer
                            page:
                              type: integer
                            from:
                              type: string
                            part:
                              type: string
                            duration:
                              type: integer
                            vid:
                              type: string
                            weblink:
                              type: string
                            dimension:
                              type: object
                              properties:
                                width:
                                  type: integer
                                height:
                                  type: integer
                                rotate:
                                  type: integer
                              required:
                                - width
                                - height
                                - rotate
                              x-apifox-orders:
                                - width
                                - height
                                - rotate
                            ctime:
                              type: integer
                          x-apifox-orders:
                            - cid
                            - page
                            - from
                            - part
                            - duration
                            - vid
                            - weblink
                            - dimension
                            - ctime
                      subtitle:
                        type: object
                        properties:
                          allow_submit:
                            type: boolean
                          list:
                            type: array
                            items:
                              type: string
                        required:
                          - allow_submit
                          - list
                        x-apifox-orders:
                          - allow_submit
                          - list
                      staff:
                        type: array
                        items:
                          type: object
                          properties:
                            mid:
                              type: integer
                            title:
                              type: string
                            name:
                              type: string
                            face:
                              type: string
                            vip:
                              type: object
                              properties:
                                type:
                                  type: integer
                                status:
                                  type: integer
                                due_date:
                                  type: integer
                                vip_pay_type:
                                  type: integer
                                theme_type:
                                  type: integer
                                label:
                                  type: object
                                  properties:
                                    path:
                                      type: string
                                    text:
                                      type: string
                                    label_theme:
                                      type: string
                                    text_color:
                                      type: string
                                    bg_style:
                                      type: integer
                                    bg_color:
                                      type: string
                                    border_color:
                                      type: string
                                    use_img_label:
                                      type: boolean
                                    img_label_uri_hans:
                                      type: string
                                    img_label_uri_hant:
                                      type: string
                                    img_label_uri_hans_static:
                                      type: string
                                    img_label_uri_hant_static:
                                      type: string
                                    label_id:
                                      type: integer
                                    label_goto:
                                      type: object
                                      properties:
                                        mobile:
                                          type: string
                                        pc_web:
                                          type: string
                                      required:
                                        - mobile
                                        - pc_web
                                      x-apifox-orders:
                                        - mobile
                                        - pc_web
                                  required:
                                    - path
                                    - text
                                    - label_theme
                                    - text_color
                                    - bg_style
                                    - bg_color
                                    - border_color
                                    - use_img_label
                                    - img_label_uri_hans
                                    - img_label_uri_hant
                                    - img_label_uri_hans_static
                                    - img_label_uri_hant_static
                                    - label_id
                                    - label_goto
                                  x-apifox-orders:
                                    - path
                                    - text
                                    - label_theme
                                    - text_color
                                    - bg_style
                                    - bg_color
                                    - border_color
                                    - use_img_label
                                    - img_label_uri_hans
                                    - img_label_uri_hant
                                    - img_label_uri_hans_static
                                    - img_label_uri_hant_static
                                    - label_id
                                    - label_goto
                                avatar_subscript:
                                  type: integer
                                nickname_color:
                                  type: string
                                role:
                                  type: integer
                                avatar_subscript_url:
                                  type: string
                                tv_vip_status:
                                  type: integer
                                tv_vip_pay_type:
                                  type: integer
                                tv_due_date:
                                  type: integer
                                avatar_icon:
                                  type: object
                                  properties:
                                    icon_type:
                                      type: integer
                                    icon_resource:
                                      type: object
                                      properties: {}
                                      x-apifox-orders: []
                                  required:
                                    - icon_type
                                    - icon_resource
                                  x-apifox-orders:
                                    - icon_type
                                    - icon_resource
                                ott_info:
                                  type: object
                                  properties:
                                    vip_type:
                                      type: integer
                                    pay_type:
                                      type: integer
                                    pay_channel_id:
                                      type: string
                                    status:
                                      type: integer
                                    overdue_time:
                                      type: integer
                                  required:
                                    - vip_type
                                    - pay_type
                                    - pay_channel_id
                                    - status
                                    - overdue_time
                                  x-apifox-orders:
                                    - vip_type
                                    - pay_type
                                    - pay_channel_id
                                    - status
                                    - overdue_time
                                super_vip:
                                  type: object
                                  properties:
                                    is_super_vip:
                                      type: boolean
                                  required:
                                    - is_super_vip
                                  x-apifox-orders:
                                    - is_super_vip
                              required:
                                - type
                                - status
                                - due_date
                                - vip_pay_type
                                - theme_type
                                - label
                                - avatar_subscript
                                - nickname_color
                                - role
                                - avatar_subscript_url
                                - tv_vip_status
                                - tv_vip_pay_type
                                - tv_due_date
                                - avatar_icon
                                - ott_info
                                - super_vip
                              x-apifox-orders:
                                - type
                                - status
                                - due_date
                                - vip_pay_type
                                - theme_type
                                - label
                                - avatar_subscript
                                - nickname_color
                                - role
                                - avatar_subscript_url
                                - tv_vip_status
                                - tv_vip_pay_type
                                - tv_due_date
                                - avatar_icon
                                - ott_info
                                - super_vip
                            official:
                              type: object
                              properties:
                                role:
                                  type: integer
                                title:
                                  type: string
                                desc:
                                  type: string
                                type:
                                  type: integer
                              required:
                                - role
                                - title
                                - desc
                                - type
                              x-apifox-orders:
                                - role
                                - title
                                - desc
                                - type
                            follower:
                              type: integer
                            label_style:
                              type: integer
                          required:
                            - mid
                            - title
                            - name
                            - face
                            - vip
                            - official
                            - follower
                            - label_style
                          x-apifox-orders:
                            - mid
                            - title
                            - name
                            - face
                            - vip
                            - official
                            - follower
                            - label_style
                      is_season_display:
                        type: boolean
                      user_garb:
                        type: object
                        properties:
                          url_image_ani_cut:
                            type: string
                        required:
                          - url_image_ani_cut
                        x-apifox-orders:
                          - url_image_ani_cut
                      honor_reply:
                        type: object
                        properties:
                          honor:
                            type: array
                            items:
                              type: object
                              properties:
                                aid:
                                  type: integer
                                type:
                                  type: integer
                                desc:
                                  type: string
                                weekly_recommend_num:
                                  type: integer
                              required:
                                - aid
                                - type
                                - desc
                                - weekly_recommend_num
                              x-apifox-orders:
                                - aid
                                - type
                                - desc
                                - weekly_recommend_num
                        x-apifox-orders:
                          - honor
                      like_icon:
                        type: string
                      need_jump_bv:
                        type: boolean
                      disable_show_up_info:
                        type: boolean
                      is_story_play:
                        type: integer
                      is_view_self:
                        type: boolean
                    required:
                      - bvid
                      - aid
                      - videos
                      - tid
                      - tid_v2
                      - tname
                      - tname_v2
                      - copyright
                      - pic
                      - title
                      - pubdate
                      - ctime
                      - desc
                      - desc_v2
                      - state
                      - duration
                      - rights
                      - owner
                      - stat
                      - argue_info
                      - dynamic
                      - cid
                      - dimension
                      - premiere
                      - teenage_mode
                      - is_chargeable_season
                      - is_story
                      - is_upower_exclusive
                      - is_upower_play
                      - is_upower_preview
                      - enable_vt
                      - vt_display
                      - is_upower_exclusive_with_qa
                      - no_cache
                      - pages
                      - subtitle
                      - is_season_display
                      - user_garb
                      - honor_reply
                      - like_icon
                      - need_jump_bv
                      - disable_show_up_info
                      - is_story_play
                      - is_view_self
                    x-apifox-orders:
                      - bvid
                      - aid
                      - videos
                      - tid
                      - tid_v2
                      - tname
                      - tname_v2
                      - copyright
                      - pic
                      - title
                      - pubdate
                      - ctime
                      - desc
                      - desc_v2
                      - state
                      - duration
                      - mission_id
                      - rights
                      - owner
                      - stat
                      - argue_info
                      - dynamic
                      - cid
                      - dimension
                      - premiere
                      - teenage_mode
                      - is_chargeable_season
                      - is_story
                      - is_upower_exclusive
                      - is_upower_play
                      - is_upower_preview
                      - enable_vt
                      - vt_display
                      - is_upower_exclusive_with_qa
                      - no_cache
                      - pages
                      - subtitle
                      - staff
                      - is_season_display
                      - user_garb
                      - honor_reply
                      - like_icon
                      - need_jump_bv
                      - disable_show_up_info
                      - is_story_play
                      - is_view_self
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
              example:
                code: 0
                message: OK
                ttl: 1
                data:
                  bvid: BV117411r7R1
                  aid: 85440373
                  videos: 1
                  tid: 28
                  tid_v2: 2061
                  tname: ''
                  tname_v2: ''
                  copyright: 1
                  pic: >-
                    http://i1.hdslb.com/bfs/archive/ea0dd34bf41e23a68175680a00e3358cd249105f.jpg
                  title: 当我给拜年祭的快板加了电音配乐…
                  pubdate: 1580377255
                  ctime: 1580212263
                  desc: >-
                    【CB想说的】看完拜年祭之后最爱的一个节目！给有快板的部分简单加了一些不同风格的配乐hhh，感谢沃玛画的我！太可爱了哈哈哈哈哈哈哈！！！

                    【Warma想说的】我画了打碟的CB，画风为了还原原版视频所以参考了四迹老师的画风，四迹老师的画真的太可爱啦！不过其实在画的过程中我遇到了一个问题，CB的耳机……到底是戴在哪个耳朵上呢？


                    原版：av78977080

                    编曲（配乐）：Crazy Bucket

                    人声（配音）：Warma/谢拉

                    曲绘：四迹/Warma

                    动画：四迹/Crazy Bucket

                    剧本：Mokurei-木灵君

                    音频后期：DMYoung/纳兰寻风/Crazy Bucket

                    包装：破晓天
                  desc_v2:
                    - raw_text: >-
                        【CB想说的】看完拜年祭之后最爱的一个节目！给有快板的部分简单加了一些不同风格的配乐hhh，感谢沃玛画的我！太可爱了哈哈哈哈哈哈哈！！！

                        【Warma想说的】我画了打碟的CB，画风为了还原原版视频所以参考了四迹老师的画风，四迹老师的画真的太可爱啦！不过其实在画的过程中我遇到了一个问题，CB的耳机……到底是戴在哪个耳朵上呢？


                        原版：av78977080

                        编曲（配乐）：Crazy Bucket

                        人声（配音）：Warma/谢拉

                        曲绘：四迹/Warma

                        动画：四迹/Crazy Bucket

                        剧本：Mokurei-木灵君

                        音频后期：DMYoung/纳兰寻风/Crazy Bucket

                        包装：破晓天
                      type: 1
                      biz_id: 0
                  state: 0
                  duration: 486
                  mission_id: 11838
                  rights:
                    bp: 0
                    elec: 0
                    download: 1
                    movie: 0
                    pay: 0
                    hd5: 1
                    no_reprint: 1
                    autoplay: 1
                    ugc_pay: 0
                    is_cooperation: 1
                    ugc_pay_preview: 0
                    no_background: 0
                    clean_mode: 0
                    is_stein_gate: 0
                    is_360: 0
                    no_share: 0
                    arc_pay: 0
                    free_watch: 0
                  owner:
                    mid: 66606350
                    name: buckit_陈楒潼
                    face: >-
                      https://i2.hdslb.com/bfs/face/c9af3b32cf74baec5a4b65af8ca18ae5ff571f77.jpg
                  stat:
                    aid: 85440373
                    view: 2417169
                    danmaku: 12554
                    reply: 2681
                    favorite: 57987
                    coin: 72977
                    share: 9639
                    now_rank: 0
                    his_rank: 55
                    like: 161650
                    dislike: 0
                    evaluation: ''
                    vt: 0
                  argue_info:
                    argue_msg: ''
                    argue_type: 0
                    argue_link: ''
                  dynamic: |-
                    进来就出不去了！！！
                    #全民音乐UP主##CB##warma##电音##快板##拜年祭##诸神的奥运##编曲##Remix#
                  cid: 146044693
                  dimension:
                    width: 1920
                    height: 1080
                    rotate: 0
                  premiere: null
                  teenage_mode: 0
                  is_chargeable_season: false
                  is_story: false
                  is_upower_exclusive: false
                  is_upower_play: false
                  is_upower_preview: false
                  enable_vt: 0
                  vt_display: ''
                  is_upower_exclusive_with_qa: false
                  no_cache: false
                  pages:
                    - cid: 146044693
                      page: 1
                      from: vupload
                      part: 建议改成：建议改成：诸 神 的 电 音 节（不是）
                      duration: 486
                      vid: ''
                      weblink: ''
                      dimension:
                        width: 1920
                        height: 1080
                        rotate: 0
                      ctime: 1580212263
                  subtitle:
                    allow_submit: false
                    list: []
                  staff:
                    - mid: 66606350
                      title: UP主
                      name: buckit_陈楒潼
                      face: >-
                        https://i2.hdslb.com/bfs/face/c9af3b32cf74baec5a4b65af8ca18ae5ff571f77.jpg
                      vip:
                        type: 2
                        status: 1
                        due_date: 1803657600000
                        vip_pay_type: 1
                        theme_type: 0
                        label:
                          path: http://i0.hdslb.com/bfs/vip/label_annual.png
                          text: 年度大会员
                          label_theme: annual_vip
                          text_color: '#FFFFFF'
                          bg_style: 1
                          bg_color: '#FB7299'
                          border_color: ''
                          use_img_label: true
                          img_label_uri_hans: ''
                          img_label_uri_hant: ''
                          img_label_uri_hans_static: >-
                            https://i0.hdslb.com/bfs/vip/8d4f8bfc713826a5412a0a27eaaac4d6b9ede1d9.png
                          img_label_uri_hant_static: >-
                            https://i0.hdslb.com/bfs/activity-plat/static/20220614/e369244d0b14644f5e1a06431e22a4d5/VEW8fCC0hg.png
                          label_id: -22
                          label_goto:
                            mobile: >-
                              https://big.bilibili.com/mobile/index?navhide=1&from_spmid=vipicon
                            pc_web: >-
                              https://account.bilibili.com/big?from_spmid=vipicon
                        avatar_subscript: 1
                        nickname_color: '#FB7299'
                        role: 3
                        avatar_subscript_url: ''
                        tv_vip_status: 0
                        tv_vip_pay_type: 0
                        tv_due_date: 0
                        avatar_icon:
                          icon_type: 1
                          icon_resource: {}
                        ott_info:
                          vip_type: 0
                          pay_type: 0
                          pay_channel_id: ''
                          status: 0
                          overdue_time: 0
                        super_vip:
                          is_super_vip: false
                      official:
                        role: 1
                        title: bilibili 知名音乐UP主
                        desc: ''
                        type: 0
                      follower: 602282
                      label_style: 0
                    - mid: 53456
                      title: 曲绘
                      name: Warma
                      face: >-
                        https://i2.hdslb.com/bfs/face/87c0b7e4d3eedf04c458a82b9271013beaa4bc59.jpg
                      vip:
                        type: 2
                        status: 1
                        due_date: 1802620800000
                        vip_pay_type: 0
                        theme_type: 0
                        label:
                          path: http://i0.hdslb.com/bfs/vip/label_annual.png
                          text: 年度大会员
                          label_theme: annual_vip
                          text_color: '#FFFFFF'
                          bg_style: 1
                          bg_color: '#FB7299'
                          border_color: ''
                          use_img_label: true
                          img_label_uri_hans: >-
                            https://i0.hdslb.com/bfs/activity-plat/static/20220608/e369244d0b14644f5e1a06431e22a4d5/0DFy9BHgwE.gif
                          img_label_uri_hant: ''
                          img_label_uri_hans_static: >-
                            https://i0.hdslb.com/bfs/vip/8d7e624d13d3e134251e4174a7318c19a8edbd71.png
                          img_label_uri_hant_static: >-
                            https://i0.hdslb.com/bfs/activity-plat/static/20220614/e369244d0b14644f5e1a06431e22a4d5/uckjAv3Npy.png
                          label_id: -22
                          label_goto:
                            mobile: >-
                              https://big.bilibili.com/mobile/index?navhide=1&from_spmid=vipicon
                            pc_web: >-
                              https://account.bilibili.com/big?from_spmid=vipicon
                        avatar_subscript: 1
                        nickname_color: '#FB7299'
                        role: 3
                        avatar_subscript_url: ''
                        tv_vip_status: 1
                        tv_vip_pay_type: 1
                        tv_due_date: 1785427200
                        avatar_icon:
                          icon_type: 1
                          icon_resource: {}
                        ott_info:
                          vip_type: 1
                          pay_type: 1
                          pay_channel_id: alipay
                          status: 1
                          overdue_time: 1785427200
                        super_vip:
                          is_super_vip: true
                      official:
                        role: 1
                        title: bilibili 知名UP主
                        desc: ''
                        type: 0
                      follower: 4963350
                      label_style: 0
                  is_season_display: false
                  user_garb:
                    url_image_ani_cut: ''
                  honor_reply:
                    honor:
                      - aid: 85440373
                        type: 2
                        desc: 第45期每周必看
                        weekly_recommend_num: 45
                      - aid: 85440373
                        type: 3
                        desc: 全站排行榜最高第55名
                        weekly_recommend_num: 0
                      - aid: 85440373
                        type: 4
                        desc: 热门
                        weekly_recommend_num: 0
                      - aid: 85440373
                        type: 7
                        desc: 热门收录
                        weekly_recommend_num: 0
                  like_icon: ''
                  need_jump_bv: false
                  disable_show_up_info: false
                  is_story_play: 1
                  is_view_self: false
          headers: {}
          x-apifox-name: 成功
      security: []
      x-apifox-folder: 主站/Web 界面/Wbi
      x-apifox-status: developing
      x-run-in-apifox: https://app.apifox.com/web/project/7776376/apis/api-416367303-run
components:
  schemas: {}
  securitySchemes: {}
servers:
  - url: https://api.bilibili.com
    description: 正式环境
security: []

```
