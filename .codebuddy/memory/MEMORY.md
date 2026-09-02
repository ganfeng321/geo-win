# MEMORY.md — GEO 自用品项目长期记忆

## 项目架构（三层）
- 监控端 Goodie：Node 服务，端口 3002，仅支持 doubao/deepseek 两 AI 引擎，登录 admin/Admin@123456
- 发布端 MPP/sau_backend：Python(系统 C:\Program Files\Python310)，端口 5409，9 平台 uploader
- 整合层 geo-core：Python，端口 7000，dashboard_api.py 统一后台(7 标签:闭环看板/定时发布/账号管理/一键发布/机会洞察/短视频脚本/监测管理/自动复盘) + pipeline/scheduler/visibility_loop/review_loop

## 关键约定（用户决策）
- **不在各发布平台深挖适配**。统一以**小红书(type=1)**为唯一已验证真实发布平台。其他平台 uploader 未适配，发布会返回明确错误(不静默)。
- **视频类一律不做**（用户明确禁令 2026-09-02）：短视频脚本生成(F14)、视频文件端到端发布、任何视频平台(抖音/快手/B站/视频号等)的视频 uploader 适配，全部不碰。已交付的 F14 脚本生成代码保留但不再扩展，不新增视频相关功能。
- **抖音/快手/B站/视频号本质是视频平台**，不应归入"图文候选"——即使发布端 `platform_configs.py` 里 `image_publish=True`(配了图文入口)，按"视频类不做+不在平台深挖"原则也**不纳入近期图文扩展范围**。真正偏图文形态的平台只有：小红书(已通)、视频号图文笔记、Facebook/Instagram 帖子。
- 用户偏好：做完必须检查通过才算完成；不做反爬；用简体中文回答。

## 发布链路关键事实
- 发布端 HTTP 接口 `/postVideosToMultiplePlatforms` 是**同步阻塞**(内部 asyncio.run(run_upload))，单图文约 40-60s。
- **必须单实例运行 sau_backend** + 每次真实发布前用 psutil 杀净残留 Chromium 进程，否则 180s 超时。
- `PublisherClient.publish` 取结果用 `data.get(platform)`(英文名如 xiaohongshu)，**不能**用 `str(code)`(数字)。
- 小红书 config 关键选择器(已修)：发布按钮 `span.btn-text:has-text("发布笔记")`；标题 `input[placeholder="填写标题会有更多赞哦"]`；正文 `div.tiptap.ProseMirror[contenteditable="true"]`；file input 延迟渲染需 `wait_for_selector`。

## F14 视频脚本
- 路由是 `/api/generate/video`(不是 /api/generate)；generate_video_script 已落库 content_type='video'；max_tokens=2500 + _parse_video 截断容错。

## 验收脚本(可复跑, 在 apps/geo-core/)
acceptance_real_publish_test(F7)/acceptance_accounts_test(F8)/acceptance_pipeline_test(F10)/acceptance_loop_test(F17+P4)/acceptance_video_test(F14)/acceptance_scheduler_test(F11)/acceptance_auto_review_test(F20)/acceptance_ui_test(F19)/acceptance_alert_test(F12)/acceptance_export_test(F13)/acceptance_publish_hardening_test(F7B)。2026-09-02 全部通过，报告 docs/MVP_ACCEPTANCE_REPORT.md。

## CI 自动回归
- `.github/workflows/regression.yml`：push/PR/手动触发，ubuntu-latest，建 venv 装依赖，跑 `run_all.py --skip-real`（跳过真实发布 F7/F10/F18）。AGNES_API_KEY 等走 secrets。失败上传 dashboard.log/err。
- `run_all.py` 已跨平台（自动选 venv/Scripts/python.exe 或 venv/bin/python），ALL_SUITES 顺序 F8/F14/F11/F12/F17/F19(非真实发布) / F18/F7/F10(真实发布,--skip-real 跳过)。F19 标 real=False 纳入 CI；F18 真实发布标 real=True 跳过。
- 本地验证：`run_all.py --skip-real` → F8/F14/F11/F12/F17/F19 全过(219s 含 F17 调 LLM)。

## F20 闭环自动复盘(review_loop.py, 2026-09-02 完成)
- 目标：发布→检测可见性→低提及率话题自动换角度重生成→(可选)再次发布，形成"发布-检测-优化"自循环。
- db.py 新增 `auto_review_tasks` 表(brand/topic/platform/angle/min_mention_rate/enabled/auto_loop/last_run_at/last_status/last_rate/run_count) + CRUD：insert/list/get/update_auto_review_task_run/update_auto_review_task_angle/set_auto_review_task_enabled/set_auto_review_task_loop/delete。
- review_loop.py `ReviewLoop.review_once(task, publish=False)`：取最新可见性快照 after_mention_rate → 低于阈值则用 LLM(angle 候选库轮换)生成新角度 → ContentGenerator.generate(platform,brand,topic,tone_hint=角度) 重生成落库 → publish=True 时调 pipeline.run(skip_publish=False) 真实发布(复用 F7)。`_touch_auto_review_task` 用于达阈值不触发时仅记 last_rate 不增 run_count。
- 后台线程 `ReviewLoop().start()` 每 120s 轮询 auto_loop=1 的任务自动执行闭环；dashboard 启动处 `_review_loop.start()`。
- dashboard_api.py 新增路由：GET /api/review/tasks、/api/review/auto-status；POST /api/review/tasks(创建,拒绝视频平台)、/api/review/run-now、/api/review/toggle、/api/review/auto-toggle、/api/review/delete。前端新增"自动复盘"tab(review section + loadReview/createReviewTask/runReviewNow/toggleReviewLoop/deleteReviewTask)。
- 验收 acceptance_auto_review_test.py 15/15 通过(AC1-AC6)。node --check 校验前端 SYNTAX OK。
- 注意：pipeline.run 实际无返回值(None)，发布成功判定改用查 list_publish 最新 success 记录。
- insert_visibility_snapshot 真实签名：(project_id, brand, trigger, before_rate, after_rate, before_score, after_score, publish_before, publish_after, detection_record_id=None)。

## F19 统一后台 UI 美化(2026-09-02 完成,暗色玻璃拟态风格)
- dashboard_api.py `dashboard_html()` 全面美化:毛玻璃 sticky 顶栏、渐变标题、CSS 变量设计令牌(:root{--bg/--panel/--line/--txt/--muted/--accent/--accent2/--pos/--neg/--warn})、KPI 卡片(左侧渐变色条+hover 上浮)、表格 hover、状态 badge、SVG 趋势图。
- 2026-09-02 二次增强:`_sparkline()` 改渐变面积填充+网格线+末端高亮圆点+数值标注;`@keyframes fadeIn` section 进场动画、`.loading` spinner、`.empty` 空状态、`.card:hover` 微交互、KPI 色条、nav 窄屏 flex-wrap、`::-webkit-scrollbar`、窄屏 @media(max-width:760px);各 load*() 加 loading 态、空数据用 .empty 友好态; `<head>` 加 viewport 响应式。
- 验收 acceptance_ui_test.py 改写(纯标准库 urllib,不依赖真实发布/requests):16/16 通过(AC19.1 七模块/AC19.2 设计令牌/AC19.3 趋势图区域+SVG/AC19.4 数据路由/AC19.5 viewport+滚动条/AC19.6 spark 渐变圆点网格/AC19.7 empty+loading+fadeIn+KPI 色条/AC19.8 node --check 脚本语法)。
- 关键教训(UI 验收铁律):Python 三引号/f-string 内嵌 JS 时 `split('\n')` 的 `\n` 会被 Python 转义成真实换行破坏 JS→必须 `String.fromCharCode(10)`;每次 UI 改动后用 node --check 校验 `<script>` 可执行(本次即查出 loop 表三元缺闭合括号的语法错误)。

## F12 告警推送闭环(2026-09-02 完成)
- 目标：可见性低于阈值→自动落库告警→推送到外部渠道(Webhook)→可标记解决，形成"检测-告警-推送-确认"闭环。
- db.py `alerts` 表加 `pushed INTEGER DEFAULT 0` 列(`_ensure_columns` 兼容旧库);新增 `mark_alert_pushed(aid, ok=True)`(成功=1/失败=-1)、`resolve_alert(aid)`(resolved=1)、`list_alerts_pending_push(limit)`(resolved=0 且 pushed<>1)。
- config.py 新增 `ALERT_WEBHOOK_URL`(env)、`ALERT_PUSH_ENABLED`。alert_pusher.py `AlertPusher`：`push_alert(alert)`(发 HTTP POST JSON msg_type=text)、`push_pending()`(批量推送待发,返回 {pushed,failed,skipped,total})。**未配置 webhook 不致命**——push_alert 标 pushed=1(视为无需推送)返回 False 不抛错。
- dashboard_api.py：`/api/overview` 拉取时 `check_visibility_alert(snap)` 后自动 `AlertPusher().push_pending()` 推送待发;新增 GET /api/alerts(含 pending/webhook_enabled)、POST /api/alerts/push(指定 alert_id 或全推)、POST /api/alerts/resolve。**注意：POST 路由必须在 do_POST 分发链内**(曾误放 do_GET 导致 'not found'，已修正)。前端新增"告警中心"tab(loadAlerts/pushAllAlerts/pushOneAlert/resolveAlert)。
- 验收 acceptance_alert_test.py 12/12 通过(AC12.1 落库/AC12.2 低提及率生成/AC12.3 未配置不致命+配置真实推送(mock server)/AC12.4 解决闭环/AC12.5 pending 查询/AC12.6 路由/AC12.7 前端)。node --check SYNTAX OK。
- 边界：推送失败绝不致命(标记 pushed=-1 便于重试,不阻塞主链路与看板)。

## F13 报表快照与导出 收尾完成并验收通过（2026-09-02 续）
- 原 `/api/export?type=csv` 已有(三段多表 CSV+BOM)；本次补全 **JSON 全量结构化导出** + 验收脚本 + 统一导出入口。
- dashboard_api.py 新增 `_export_json()`：聚合 overview/generated/published/accounts/monitor_projects/alerts/insights/visibility_snapshots 为单个 JSON(version+exported_at+各模块数组)；`/api/export` 路由据 `type=csv|json` 分流(JSON 用 application/json + geo_report.json 附件)。
- 前端闭环看板区导出按钮升级为「导出报表 CSV / 导出 JSON」两个(统一导出入口,F16 收敛点)。
- **踩坑**：`datetime.now()` 在本机系统 Python310 下报错(module 'datetime' has no attribute 'now')——正确写法是 `datetime.datetime.now()`(now 是 datetime 类的类方法,非模块属性)。已在 `_export_json` 修正。
- 验收 acceptance_export_test.py(纯标准库 urllib,不依赖真实发布)**23/23 通过**(AC13.1 CSV 三表头+可 csv 解析/AC13.2 JSON 合法/AC13.3 全模块键/AC13.4 字段类型完整/AC13.5 CSV BOM(查原始字节 b'\xef\xbb\xbf')/AC13.6 两格式 HTTP200+attachment)。已接入 run_all.py(SUITES 加 F13, real=False 纳入 CI)。
- 整体回归: 依赖服务就绪时 F8/F11/F12/F13/F14/F17/F19 全过(本次初跑 F8/F11 失败因发布端 5409 未起,启动后复跑 5/5 通过,证实是环境依赖非代码回归)。F7/F10 真实发布由 --skip-real 跳过。
- node --check 前端 SYNTAX OK(改动 UI 后必查)。

## B 真实发布自动化加固（F7B, 2026-09-02 完成并通过验收）
- 目标：加固 F7/F10 真实发布链路健壮性(不扩平台/不碰视频,契合用户硬约束)。
- publisher_client.py 加固：`check_account()` 账号探针(未知平台/无账号/Cookie过期3类,前置短路不进发布端网络);`_cookie_age_days()` Cookie 过期探针(超7天标 cookie_expired);`publish()` 自动调 `pre_publish_cleanup()`(服务存活+杀残留 Chromium)+超时分级(180s→120s,分类 timeout);结构化 `error_type`∈{unknown_platform/no_account/cookie_expired/publish_failed/timeout/exception};无账号返回 `need_login=True`(半自动登录衔接)。
- db.py `publish_records` 表新增 `error_type TEXT`(`_ensure_columns` 兼容旧库);`insert_publish` 增 `error_type` 参数并落库。
- pipeline.py `run()` 真实发布前加 `pre_publish_cleanup(verbose=False)`;dashboard_api.py `_api_publish` 透传 `error_type`/`need_login` 给前端。
- **关键铁律(踩坑)**：dashboard 自检 `pre_publish_cleanup` 含"整合层(7000)"=自身;原 `socketserver.TCPServer` **单线程**,处理 `/api/publish` 时向自身 `/api/overview` 发请求→自调用死锁15s超时。已改 **`ThreadingTCPServer`+allow_reuse_address**(dashboard_api.py 末尾)。真实发布长阻塞也不再卡死看板。
- 验收 `acceptance_publish_hardening_test.py`(F7B)**20/20 通过/1跳过**(跳过真实发布,按 --skip-real 约定;不依赖登录态即可全量跑)。已纳入 run_all.py(SUITES 加 F7B, real=False)。AC_B1~B7 覆盖探针/超时/错误分类/落库/接口信号。
- 整体回归(发布端就绪时)F8/F11/F12/F13/F14/F17/F19/F7B 全过(初跑 F8/F11 失败因重启 dashboard 时误杀发布端进程,重起后复跑5/5通过,环境依赖非回归)。
