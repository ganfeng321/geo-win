# 产品规划设计文档（PRD）
# GEO 自用品 · 自动生成 + 自动发布 + 可见性闭环

> 版本: v1.0 ｜ 日期: 2026-09-01 ｜ 状态: 已评审待实施
> 性质: 仅自用,不商用。全部功能生产级,无假功能、无占位、无 Mock。

---

## 0. 文档约定

- **MVP**: 第一版必须交付且可生产使用的最小闭环（本文第 4 节）。
- **完善功能**: MVP 之后迭代（本文第 5 节），但同样生产级、无假功能。
- **验收标准(AC)**: 每条功能配可量化、可自动/手动验证的通过条件。未达 AC 视为未完成。
- **无假功能**: 文档中出现的功能,实施时必须有真实后端逻辑与真实数据,禁止占位按钮、假数据、Mock 接口。

---

## 1. 产品定位

**一句话**: 一个面向国内市场的 GEO(生成式引擎优化)自用平台 —— 配置品牌与关键词后,自动用自有 AI 生成符合各平台调性的内容,自动发布到多平台矩阵账号,并持续监测品牌在 AI 搜索引擎(豆包/元宝/DeepSeek/Kimi/通义)中的可见性与引用,形成"生成→发布→可见性验证→优化"闭环。

**不做**(明确边界,避免范围蔓延):
- 不对外售卖、不做多租户 SaaS、不做计费。
- 不做海外平台(预留扩展位,不实现)。
- 不逆向平台私有接口做规模化黑产式发布;发布一律基于 Playwright + 用户自有账号 Cookie,频率受控。

---

## 2. 目标用户与场景

**唯一用户角色**: 运营者(即使用者本人)。具备:配置品牌/关键词、录入平台账号 Cookie、查看看板、触发生成与发布、查看可见性报告的权限。

**核心场景(SC)**:
- SC1 配置: 新增一个品牌"量子科技",设定监测关键词"量子计算云服务""量子芯片",选择监测 AI 平台[DeepSeek(agnes 直通)]。
- SC2 生成: 系统按小红书/抖音/百家号调性,用自有 AI 生成 3 篇图文,每篇含标题/正文/标签。
- SC3 发布: 将生成内容定时发布到已录入 Cookie 的对应平台账号。
- SC4 监测: 每日定时在所选 AI 平台提问品牌词,记录品牌是否被提及、位置、引用来源、情感。
- SC5 闭环: 看板展示"发布量 / 各平台表现 / AI 可见性趋势",运营者据此调整生成策略。

---

## 3. 功能清单总览(全量,含 MVP 标记)

| 编号 | 功能 | 分层 | MVP | 验收章节 |
|------|------|------|-----|----------|
| F1 | 品牌/项目管理 | 监控端(复用) | ✅ | 4.1 |
| F2 | 关键词/提示词管理 | 监控端(复用) | ✅ | 4.1 |
| F3 | AI 平台监测(DeepSeek/agnes 直通;豆包等完善期接入) | 监控端(复用) | ✅ | 4.2 |
| F4 | AI 检测任务执行(用自有 API) | 监控端(复用) | ✅ | 4.2 |
| F5 | 可见性指标/引用来源/竞品/情感 | 监控端(复用) | ✅ | 4.3 |
| F6 | 内容生成(按平台调性) | 整合层(自研) | ✅ | 4.4 |
| F7 | 多平台自动发布(定时/批量) | 发布端(复用)+整合层 | ✅ | 4.5 |
| F8 | 平台账号 Cookie 录入与管理 | 发布端(复用) | ✅ | 4.5 |
| F9 | 统一看板(生成量/发布量/可见性) | 整合层(自研) | ✅ | 4.6 |
| F10 | 生成→发布→监测 编排流水线 | 整合层(自研) | ✅ | 4.7 |
| F11 | 定时调度(生成/发布/监测自动化) | 整合层+监控端 | ✅ | 4.8 |
| F12 | 告警规则与通知 | 监控端(复用) | ⬜ 完善 | 5.1 |
| F13 | 报表快照与导出 | 监控端(复用) | ⬜ 完善 | 5.2 |
| F14 | 短视频脚本生成 + 视频发布 | 整合层(自研) | ⬜ 完善 | 5.3 |
| F15 | 机会洞察/内容缺口建议 | 监控端(复用) | ⬜ 完善 | 5.4 |
| F16 | 统一账号/品牌后台 Web UI | 整合层(自研) | ⬜ 完善 | 5.5 |
| F17 | 可见性归因(发布→可见性提升关联) | 整合层(自研) | ✅ 已交付 | 4.6/5.6 |

---

## 4. MVP 详细设计(必须生产级交付)

### 4.1 品牌与项目管理(F1/F2)
- **能力**: 在监控端创建品牌项目,设置品牌名、品牌关键词(用于检测命中)、监测 AI 平台列表、竞争对手列表。
- **复用**: 监控端 `BrandProject` / `BrandCompetitor` / `TrackedPrompt` 模型与 `/api/projects` 接口。
- **AC**:
  - AC1.1 创建项目后,`BrandProject` 表新增一行,`monitoring_platforms` 字段正确存储所选平台数组。
  - AC1.2 至少能选 [豆包, 元宝, DeepSeek, Kimi, 通义] 中≥3 个。
  - AC1.3 关键词保存后在后续检测中用于命中统计(见 4.2)。

### 4.2 AI 检测执行(F3/F4)
- **能力**: 对品牌项目触发检测,系统在所选 AI 平台提问品牌词,调用 AI 获取回答,解析品牌是否提及。
- **接入现状(真实,无假功能)**: 经代码核查 `AIPlatformService.js`:
  - `deepseek` 分支走标准 `/chat/completions`,已验证可直通用户 agnes 网关(agnes-2.5-flash)✅
  - `doubao` 走火山方舟 `/responses` 格式(非 OpenAI 兼容),需豆包自有 Key 或改造为 chat 格式,**MVP 不默认启用**
  - `kimi` / `qianwen` 在原项目中 URL 为占位示例(`api.kimi.com`/`api.qianwen.com` 不存在),属未实现接口;元宝(yuanbao)在原项目代码中**不存在**
  - 因此 **MVP 监测平台 = 仅 DeepSeek(agnes 直通)**,这是当前唯一经实测可用的 AI 监测通道
- **AC**:
  - AC2.1 在 DeepSeek 平台触发检测后,`QuestionRecord` + `ResultDetail` 各新增记录,`ai_response_original` 非空且为真实 agnes API 返回。
  - AC2.2 品牌被提及时,`ResultDetail.brand_mentioned=true` 且 `mentioned_keywords` 含命中关键词。
  - AC2.3 使用 agnes-2.5-flash 模型,响应时延 P95 < 30s(单次单平台)。
  - AC2.4 连续 10 次 DeepSeek 检测成功率为 100%(失败指 API 错误,非"未提及")。
- **扩展(完善期,非 MVP,且须真实接入后才算完成)**: 豆包(配豆包 Key)、Kimi/元宝/通义(需提供真实可用 endpoint 并改造为 chat 兼容格式,禁止占位 URL)。
- **扩展现状闭环标注(2026-09-02)**: 当前监测通道仍**仅 DeepSeek(agnes 直通)**,豆包/Kimi/元宝/通义**未真实接入、未声明支持**(严守"无假功能"原则)。此能力受监控端上游仅实现 doubao/deepseek 两引擎的硬限制,叠加用户"不在各发布/监测平台深挖适配"的决策,故列为完善期待办而非缺陷;纳入范围前必须先有真实 Key + 真实 endpoint 改造,否则不在本期交付内。

### 4.3 可见性指标(F5)
- **能力**: 监测结果汇总为可见性指标:提及率、Share of Voice、引用来源域名、竞品曝光、情感倾向。
- **复用**: 监控端 `VisibilityMetric` / `SourceAnalysisService` / `BrandCompetitorService`。
- **AC**:
  - AC3.1 每次检测后 `VisibilityMetric` 按项目+周期生成一条汇总(提及率=提及次数/总检测数,数值 0~1)。
  - AC3.2 引用来源分析能列出答案中出现的外部 URL 域名及出现次数(去重计数)。
  - AC3.3 情感判定输出 positive/neutral/negative 之一,且对 20 条人工标注样本准确率 ≥ 80%。

### 4.4 内容生成(F6)
- **能力**: 输入品牌+话题+目标平台,用 agnes API 生成标题/正文/标签,遵循平台调性模板。
- **实现**: `apps/geo-core/content_generator.py`(已存在,需补:失败重试、空值校验、超长截断)。
- **AC**:
  - AC4.1 对 [小红书, 抖音, 百家号] 各生成 1 篇,`title` 非空且 ≤ 30 字,`body` 非空且 100~800 字,`tags` 含 1~5 个标签。
  - AC4.2 正文中品牌名出现 ≥ 1 次。
  - AC4.3 单篇生成失败(网络/API 错误)时自动重试 2 次,仍失败返回明确错误,不写入假数据。
  - AC4.4 生成内容存入整合层数据库 `generated_content` 表(见架构文档 ER),可追溯。

### 4.5 自动发布(F7/F8)
- **能力**: 将生成内容(图文)发布到已录入 Cookie 的平台账号,支持批量与定时。
- **复用**: 发布端 `postVideosToMultiplePlatforms` + `cookiesFile/` Cookie 管理。
- **前置硬依赖**: 平台账号 Cookie 需一次性录入 `cookiesFile/`(人手或浏览器自动化获取)。**这是 MVP 唯一需人工介入的点,文档明确标注,不隐藏。**
- **AC**:
  - AC5.1 已录入 ≥ 1 个平台 Cookie 时,调用发布端 API 后该平台返回发布成功状态,且 `publish_records` 表记录成功。
  - AC5.2 Cookie 缺失时,接口返回明确错误"平台 X 未录入账号",不静默失败。
  - AC5.3 定时发布:设置 `enableTimer=true` + `daily_times`,发布端在指定时间实际发布(可用日志/记录验证)。
  - AC5.4 发布失败(如 Cookie 失效)在 `publish_records` 标记 failed 并附错误原因。

### 4.6 统一看板(F9) + 可见性闭环(F17,已交付)
- **能力**: 单一页面展示:MVP 周期内生成篇数、发布成功/失败数、各平台分布、品牌 AI 可见性趋势(提及率曲线);并提供**可见性闭环归因**——把"发布动作"与"AI 可见性检测"关联,量化发布对可见性的贡献(发布前/后 `mention_rate` 与合成可见性指数对比)。
- **实现**: 整合层 `dashboard_api.py`(7000 端口)聚合:
  - 监控端 `/api/geo-projects/:id/dashboard`(真实 trend/summary,源自 `VisibilityMetric`);
  - 整合层 `generated_content` / `publish_records` 计数;
  - 闭环归因表 `visibility_snapshots`(由 `visibility_loop.py` 在每次检测时落库 before/after/delta)。
  - 前端为单文件 HTML(原生 SVG 折线图,无第三方图表库依赖),真实数据驱动。
- **GEO 可见性指数(0~100,合成)**: 监控端 summary 原生无整体 `visibility_score`,整合层用其真实字段合成:
  `mention_rate(%) /100*50 + avg_share_of_voice(%) /100*30 + citation_rate(%) /100*20`。全部来自监控端真实返回,无假数据。
- **AC(原 AC6.1~6.3 升级 + 闭环新增)**:
  - AC6.1 看板"生成篇数"= `generated_content` 表计数,与实际上报一致。
  - AC6.2 看板"可见性趋势"= 按周期聚合 `VisibilityMetric.mention_rate`,至少 2 个数据点可绘制。
  - AC6.3 所有数字可下钻到原始记录(`/api/generated`、`/api/published`、`/api/loop`、`/api/monitor/:id` 真实接口)。
  - AC6.4 闭环归因: 触发一次检测后,`visibility_snapshots` 新增记录,含 `before_mention_rate`/`after_mention_rate`/`mention_rate_delta` 与合成可见性指数 delta,均为真实检测前后值。
  - AC6.5 看板 `latest_snapshot` 字段完整可读;`/api/loop` 返回归因列表。
  - AC6.6 发布失败(无 Cookie)明确报错且落库 failed,闭环不粉饰(Δ≤0 也如实展示,不造假)。
- **验收脚本**: `apps/geo-core/acceptance_loop_test.py`(端到端 8/8 通过,实测真实检测 before→after 提及率 66.67%→68.75%、指数 53.34→55.0)。

### 4.7 编排流水线(F10)
- **能力**: 一条命令/一次触发完成:生成(多平台)→ 发布(对应平台)→ 记录。
- **实现**: `apps/geo-core/pipeline.py`(已部分存在,需补发布调用与状态落库)。
- **AC**:
  - AC7.1 执行 `pipeline.py --brand X --topic Y --platforms 小红书 抖音`,先生成后发布,终端打印每平台生成标题与发布结果。
  - AC7.2 每步结果写入 `generated_content` / `publish_records`,无步骤丢失。
  - AC7.3 任一平台发布失败不影响其他平台(隔离)。

### 4.8 定时调度(F11)
- **能力**: 监测按项目 `monitoring_enabled` + `monitoring_time` 每日定时执行(监控端已有 SchedulerService);生成+发布支持用系统定时任务(cron/计划任务)触发 pipeline。
- **AC**:
  - AC8.1 监控端 SchedulerService 在 `monitoring_time` 实际发起检测(验证 `QuestionRecord` 新增)。
  - AC8.2 提供 `start_all.ps1` 之外的调度说明:生成发布可用 Windows 任务计划程序每日触发 `pipeline.py`(文档给出具体命令,可复现)。
- **AC8.2 具体命令(可复现)**: 在整合层 `apps/geo-core` 目录,以 venv 的 Python3.10 触发(`.env` 中的 `AGNES_API_KEY/AGNES_BASE_URL/AGNES_MODEL` 由 `config.py` 自动读取,任务进程继承环境即可,无需命令行重复传参):
  ```bat
  :: 每日 09:00 自动跑 生成+发布(小红书)
  schtasks /create /tn "GEO_Daily_Publish" ^
    /tr "cmd /c cd /d d:\GEO-XINXIANGMU-00\apps\geo-core && venv\Scripts\python.exe pipeline.py --brand 量子科技 --topic 量子计算云服务优势 --platforms xiaohongshu" ^
    /sc daily /st 09:00
  :: 仅生成不发布(先验证)
  schtasks /create /tn "GEO_Daily_Generate" ^
    /tr "cmd /c cd /d d:\GEO-XINXIANGMU-00\apps\geo-core && venv\Scripts\python.exe pipeline.py --brand 量子科技 --topic 量子计算云服务优势 --platforms xiaohongshu --skip-publish" ^
    /sc daily /st 08:30
  :: 查看/删除
  schtasks /query /tn "GEO_Daily_Publish"
  schtasks /delete /tn "GEO_Daily_Publish" /f
  ```
  说明: `pipeline.py` 已支持 `--brand/--topic/--platforms/--skip-publish` 参数(见 `apps/geo-core/pipeline.py`)。真实发布前需保证发布端(5409)单实例运行且小红书账号已登录;F7-B 的 `pre_publish_cleanup` 会在每次发布前自动清理残留 Chromium 避免超时。

---

## 5. 完善功能(生产级,按优先级迭代)

### 5.1 告警(F12)
- 当品牌可见性(提及率)较上一周期下降 ≥ 20%,或竞品曝光超过本品牌,触发告警。
- AC: 告警规则可在监控端 `AlertRule` 配置;触发后 `AlertRule.evaluation` 写入记录,提供查询接口。

### 5.2 报表快照与导出(F13)
- 周期生成 `ReportSnapshot`,支持 JSON/CSV 导出。
- AC: 导出文件含项目/周期/可见性指标/发布汇总,字段完整可打开。

### 5.3 短视频脚本+视频发布(F14)
- 用 agnes 文本能力生成短视频口播脚本;视频发布复用发布端 `file_type=2`(需提供视频文件,暂由用户供给或后续接入 agnes-video-*)。
- AC: 生成脚本非空且含分镜/口播;视频发布链路与图文一致可验证。
- **用户决策(2026-09-02,闭环标注)**: 视频类一律不做——短视频脚本生成(F14)代码保留并验收通过,但**视频文件端到端发布、任何视频平台视频 uploader 适配均暂缓**,不纳入近期范围。PRD 原"视频发布链路可验证"据此仅在"脚本生成"层面达成,视频发布部分标注为待素材+适配,非未声明功能(已在实际看板/报告中明示)。

### 5.4 机会洞察(F15)
- 监控端 `OpportunityInsightService` 输出内容缺口/未被覆盖的关键词建议。
- AC: 对每个项目返回 ≥ 1 条可操作建议,基于真实检测数据。

### 5.5 统一后台 Web UI(F16)
- 整合层提供统一前端,覆盖 F1~F11 全部操作,替代多系统切换。
- AC: 所有 MVP 功能可在统一 UI 完成,无功能需回退到原系统后台。

### 5.6 可见性归因(F17,已交付)
- 建立"发布内容 → 后续可见性变化"的关联分析,量化单篇/单平台发布对可见性的贡献。
- **实现**(`apps/geo-core/visibility_loop.py` + `db.visibility_snapshots`):
  1. 取项目当前可见性基线(before): 监控端 `dashboard.summary` 的 `brand_mention_rate`(百分比)与合成可见性指数。
  2. 触发一次真实检测(`/detection/create`,platform=`deepseek`/agnes 直通),轮询 `/detection/:id` 直至 `completed`。
  3. 检测完成后取新可见性(after),计算 Δ。
  4. 落库 `visibility_snapshots(before_mention_rate, after_mention_rate, mention_rate_delta, before_visibility_score, after_visibility_score, visibility_score_delta, publish_count_before/after, detection_record_id)`。
- **可见性指数公式**(0~100,合成): `mention_rate(%) /100*50 + avg_share_of_voice(%) /100*30 + citation_rate(%) /100*20`,全部源自监控端真实 summary 字段;监控端原生无单一整体 `visibility_score`,故合成,无假数据。
- **AC(已验证)**:
  - AC: 触发闭环后 `visibility_snapshots` 新增记录,`mention_rate_delta` 为真实检测前后差值(可为负,如实展示)。
  - AC: 看板 `/api/loop` 返回归因列表;`/api/overview.latest_snapshot` 含完整字段。
  - 验收: `acceptance_loop_test.py` 端到端 8/8 通过。

---

## 6. 非功能需求

- **可靠性**: 任一外部 API 失败均重试 + 明确错误,不写假数据。
- **安全**: 所有 Key/Cookie 走 `.env` / `cookiesFile/`,不入库不提交(`.gitignore` 已覆盖)。
- **可观测**: 每个服务有运行日志;整合层流水线每步落库。
- **性能**: 单次检测 P95 < 30s;单次生成 < 30s;看板聚合 < 3s。
- **合规**: 发布频率受控,不突破平台合理阈值;仅自用。

---

## 7. 验收总门槛(MVP 准出)

MVP 视为完成,当且仅当以下全部为真:
1. 启动三端后,监控端能对新品牌跑出真实检测记录(AC2.1~2.4)。
2. 整合层能生成 ≥ 2 平台真实内容并落库(AC4.1~4.4)。
3. 录入 ≥ 1 平台 Cookie 后,发布真实成功且记录(AC5.1)。
4. 看板展示真实生成/发布/可见性数据(AC6.1~6.3)。
5. pipeline 一条命令跑通生成→发布(AC7.1~7.3)。
6. 调度能每日自动监测(AC8.1)。

任何一条不达标,MVP 不算完成。

---

## 8. 无假功能声明(合规约束)

本设计在"无假功能、无占位、无 Mock"前提下产出。已识别并显式排除的伪能力:
- ❌ 原项目 `kimi`/`qianwen` 的 URL 为占位示例(`api.kimi.com`/`api.qianwen.com` 不存在)→ 不在 MVP 声明,完善期须接入真实 endpoint。
- ❌ 原项目无"元宝(yuanbao)"实现 → 不在 MVP 声明。
- ❌ 豆包走 `/responses` 非 OpenAI 兼容格式,不能直接复用 agnes → MVP 不默认启用,完善期明确改造方案后再启用。
- ✅ MVP 真实可用监测通道:**仅 DeepSeek(agnes-2.5-flash 直通)**,已实测。

任何被标注为"完善期"的功能,在真实接入并满足对应 AC 前,不得出现在 MVP 交付清单与看板中。
