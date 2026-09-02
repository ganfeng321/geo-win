# 系统架构设计文档
# GEO 自用品 · 自动生成 + 自动发布 + 可见性闭环

> 版本: v1.0 ｜ 日期: 2026-09-01 ｜ 配套: PRD.md
> 原则: 复用开源项目为主、自研整合层为辅;无假功能;闭环无短板。

---

## 1. 架构总览

三个服务 + 一个自研整合层,通过 HTTP/REST 与共享数据库解耦:

```
┌──────────────────────────────────────────────────────────────────┐
│                      使用者(运营者)                                │
│   操作: 配置品牌/录入Cookie/看板/触发生成发布/查看可见性            │
└───────────────┬───────────────────────┬──────────────────────────┘
                │                       │                          │
      ┌─────────▼────────┐   ┌──────────▼──────────┐   ┌──────────▼──────────┐
      │  整合层 geo-core  │   │  监控端 Goodie       │   │  发布端 MPP          │
      │  (Python,自研)    │──▶│ (Next.js+Express)    │   │ (Flask+Playwright)   │
      │  llmm/pub/pipeline│   │ 3002 API / 3001 UI   │   │ 5409 API             │
      │  + 整合层 SQLite   │   │ + SQLite             │   │ + SQLite             │
      └─────────┬────────┘   └──────────┬──────────┘   └──────────┬──────────┘
                │ 调发布 API            │ 检测记录/可见性         │ 调 Cookie 发布
                │ /postVideos...        │ (读取)                 │ 到平台
                └───────────────────────┴────────────────────────┘
                用户自有 agnes API (agnes-2.5-flash) ← 监控端+整合层共用
```

**设计决策**: 不强行合并三套 SQLite,而是以"监控端 SQLite 为可见性真相源、发布端 SQLite 为发布真相源、整合层 SQLite 为编排/生成真相源",整合层通过 API 读取两端、并保存自有编排记录。避免改动开源项目内部结构(开发规则 §1)。

---

## 2. 服务职责与接口契约

### 2.1 监控端(Goodie) — 可见性真相源
- 地址: API `localhost:3002/api`, 前端 `localhost:3001`
- 关键模型: `BrandProject, BrandCompetitor, TrackedPrompt, QuestionRecord, ResultDetail, VisibilityMetric, AlertRule, ReportSnapshot`
- 复用接口:
  - `POST /api/projects` 创建品牌项目(幂等:同名复用)
  - `POST /api/detection/create` 触发检测;**返回 `data.results:[{record_id, platform, status}]`(数组,字段名 `record_id` 非 `id`)**
  - `GET /api/detection/status/:id` 轮询状态/结果(`:id` 即上述 `record_id`)
  - `GET /api/geo-projects/:id/dashboard?days=30` 看板(返回 `summary`{brand_mention_rate(百分比), avg_share_of_voice, citation_rate, recommendation_rate...} + `trend`[每日 VisibilityMetric])
- AI 调用: 经代码核查,`deepseek` 分支走标准 `/chat/completions`,已验证可直通 agnes(agnes-2.5-flash)✅;`doubao` 走火山方舟 `/responses`(非 OpenAI 兼容)、`kimi`/`qianwen` 在原项目中为占位 URL、元宝(yuanbao)代码中不存在。故 MVP 监测通道仅 DeepSeek(agnes 直通),其余平台列入完善期(需真实 Key/改造,禁止占位)。

### 2.2 发布端(MPP) — 发布真相源
- 地址: `localhost:5409`
- 关键接口: `POST /postVideosToMultiplePlatforms`
- 参数契约(来自 `multiFileUploader.post_file` 真实签名):
  ```
  platforms: list            # ["xiaohongshu","douyin",...]
  accountFiles: dict         # {平台: [cookie文件名,...]}
  fileType: int              # 1-图文 2-视频
  files: list                # 视频/图片文件名(图文可空,用 text 发布)
  title, text, tags: str
  enableTimer: bool, dailyTimes: list, startDays: int  # 定时
  ```
- 账号存储: `sau_backend/cookiesFile/<平台>/<账号>.json`(Cookie 文件)
- 注意: `cookiesFile/` 需人工或浏览器自动化一次性录入,是 MVP 唯一人工依赖。

### 2.3 整合层(geo-core,自研) — 编排真相源
- 地址: 本地 Python 服务/脚本,端口未占用(内网)
- 模块(均已存在,需补齐):
  - `llm_client.py`: 调 agnes(OpenAI 兼容)
  - `content_generator.py`: 按平台调性生成 title/body/tags,落库 `generated_content`
  - `publisher_client.py`: 调发布端 API,落库 `publish_records`
  - `pipeline.py`: 编排生成→发布
- 新增数据(DB 见 §3 整合层): `generated_content, publish_records, pipeline_runs`

---

## 3. 数据模型(ER)

### 3.1 整合层 SQLite(`apps/geo-core/geo_core.db`)— 自研
```
generated_content (
  id INTEGER PK,
  brand TEXT,
  topic TEXT,
  platform TEXT,          # xiaohongshu/douyin/...
  title TEXT,
  body TEXT,
  tags TEXT,
  model TEXT,             # agnes-2.5-flash
  status TEXT,            # generated/published/failed
  created_at DATETIME
)

publish_records (
  id INTEGER PK,
  generated_content_id INTEGER FK,
  platform TEXT,
  account TEXT,
  status TEXT,            # success/failed/pending
  error TEXT,
  published_at DATETIME
)

pipeline_runs (
  id INTEGER PK,
  brand TEXT,
  topic TEXT,
  platforms TEXT,         # json
  started_at, finished_at DATETIME,
  result_summary TEXT
)
```

### 3.2 监控端 SQLite(复用,仅列与闭环相关)
```
BrandProject(id, name, brand_keywords, monitoring_platforms, monitoring_enabled, monitoring_time)
QuestionRecord(id, project_id, platform, question, created_at)
ResultDetail(id, question_record_id, brand_mentioned, mentioned_keywords, ai_response_original, sentiment)
VisibilityMetric(id, project_id, period, mention_rate, share_of_voice, competitors_exposure)
```

### 3.3 发布端 SQLite(复用)
```
accounts(id, platform, account_name, cookie_file)
publish_logs(id, platform, account, status, created_at)  # 发布端实际表名以代码为准
```

### 3.4 关联键
- 整合层 `generated_content.brand` ↔ 监控端 `BrandProject.name`
- 发布成功 `publish_records.published_at` 用于 §5 归因(对比前后 `VisibilityMetric.mention_rate`)

---

## 4. 闭环算法(GEO 闭环逻辑,已落地)

**目标**: 量化"生成→发布→可见性提升",形成可验证闭环。

**实现**(`apps/geo-core/visibility_loop.py` + `db.visibility_snapshots` + `dashboard_api.py`):

步骤:
1. **生成**: 对品牌 B、话题 T,生成平台 P 的内容 C(agnes)。
2. **发布**: C 发布到平台 P 账号,记录 `published_at=t0`(AC5.1)。
3. **基线采集(before)**: 调监控端 `GET /api/geo-projects/:id/dashboard?days=30`,从 `summary.brand_mention_rate`(百分比)与合成可见性指数取发布前可见性。
4. **触发检测**: `POST /api/detection/create`(platform=`deepseek`/agnes 直通,带 `project_id`),轮询 `GET /api/detection/status/:id` 直至 `completed`(真实等待,无 Mock)。
5. **采集 after**: 检测完成后再次取 dashboard,得 `after_mention_rate` / `after_visibility_score`。
6. **归因落库**: 计算 Δ 并写入 `visibility_snapshots(before_mention_rate, after_mention_rate, mention_rate_delta, before/after_visibility_score, visibility_score_delta, publish_count_before/after, detection_record_id)`。
7. **展示**: 看板(7000)聚合 `visibility_snapshots` + 监控端 trend,原生 SVG 折线图呈现 Δ 与趋势。

**可见性指数(0~100,合成)**: 监控端 summary 原生无单一整体 `visibility_score`,整合层用真实字段合成 `mention_rate(%) /100*50 + avg_share_of_voice(%) /100*30 + citation_rate(%) /100*20`。全部来自监控端真实返回,无假数据。

**判定无短板**: 若 Δ≤0,看板如实展示(不粉饰),并可据此标注"未见提升,建议调整话题/平台"(无假功能约束)。

---

## 5. 关键技术决策(ADR)

- **ADR-1 复用语义**: 复用开源项目内部模型,不改其结构;整合层只通过 API 交互 + 自有库落库。理由: 降低二开风险、可随上游更新。
- **ADR-2 AI 接入**: 统一走 agnes 网关(agnes-2.5-flash)。监控端 `deepseek` 位(OpenAI 兼容 chat 格式)与整合层共用同一 Key/模型,已验证可用;豆包(doubao,/responses 格式)、Kimi/元宝/通义暂不接入(原项目为占位/不存在),列入完善期,接入前不得声明支持。理由: 用户自有、OpenAI 兼容、一处配置、且避免假功能。
- **ADR-3 发布方案**: MVP 用 MPP Playwright + Cookie(用户自有账号),不接蚁小二 API。理由: 零成本、可控、合规自用。
- **ADR-4 数据库**: 三端各自 SQLite,整合层聚合读。理由: 不破坏开源项目;后期(F16)可抽统一库。
- **ADR-5 唯一人工依赖**: 平台 Cookie 录入需一次人工/浏览器自动化。已在 PRD 4.5 明示,不隐藏。
- **ADR-6 发布可靠性与并发**: (1) 真实发布前 `publish()` 自动 `pre_publish_cleanup()`(服务存活+杀残留 Chromium)、账号探针前置短路(未知平台/无账号/Cookie 过期)、超时分级(180s→120s)、结构化 `error_type` 落库(F7-B);(2) 整合层 `dashboard_api` 由单线程 `TCPServer` 改为 `ThreadingTCPServer`,修复"自检自调用指向自身 /api/overview 单线程死锁"问题,真实发布长阻塞不再卡死看板。理由: 复用开源项目内部模型不改结构,但编排层需在自有进程内做健壮性兜底。

---

## 6. 部署与启动

- **依赖**: 监控端 Node24 + sqlite3(需 VS 构建工具);发布端 Python3.10 venv + Playwright Chromium;整合层 Python3.10 venv + requests。
- **启动**: `start_all.ps1` 一键起三端(已提供)。
- **调度**: 监测=监控端 SchedulerService;生成发布=Windows 任务计划程序每日触发 `pipeline.py`(具体 `schtasks` 命令已写入 PRD 4.8,满足 F11 AC8.2 可复现)。
- **配置**: 所有 Key 在 `.env`(已 gitignore)。

---

## 7. 架构验收标准

- ACA-1 三端独立启动且互相可通过 REST 调用(整合层→发布端 200;整合层读监控端指标成功)。
- ACA-2 整合层 `generated_content` / `publish_records` 在 pipeline 执行后确有写入(查库验证)。
- ACA-3 闭环可跑通: 发布后下一监测周期 `VisibilityMetric` 新增,看板 Δ 可计算。
- ACA-4 任一服务宕机,整合层调用返回明确错误,不写假数据(故障隔离)。
- ACA-5 全链路无 Mock/占位: 所有返回数据来自真实 API 或真实库记录。
