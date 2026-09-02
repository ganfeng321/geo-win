# GEO 自用品 · 项目总览

基于开源项目二开的**国内 GEO(生成式引擎优化)自用平台**:自动生成内容 → 自动发布到多平台 → 监控 AI 搜索可见性闭环。
仅自用,不商用。AI 生成调用用户自有 API。

---

## 一、仓库结构

```
GEO-XINXIANGMU-00/
├── DEVELOPMENT_RULES.md      # 开发规则(规范/架构约定/二开约束)
├── README.md                # 本文件
├── CI.md                    # CI / 回归验证说明(GitHub 锁定期用本机脚本替代)
├── ci_check.ps1             # 本机 CI 等价脚本(跑 run_all.py --skip-real)
├── start_all.ps1            # 一键启动三端(监控/发布)
├── start_and_ci.ps1         # 一键启动三端 + 整合层 + 跑本机 CI
├── ci_report.txt            # 最近一次本机 CI 报告
├── packages/
│   ├── geo-monitor/         # Goodie AI-GEO 监测系统(监控端,Next.js+Express+SQLite)
│   └── geo-publisher/       # MediaPublishPlatform(发布端,Python+Flask+Playwright+Vue3)
└── apps/                    # 自研整合层(规划中)
```

---

## 二、两个开源项目概览

### ① 监控端 geo-monitor(Goodie AI-GEO)
- 技术:前端 Next.js(3001) / 后端 Express(3002) / SQLite
- 已支持 AI 平台:**豆包、DeepSeek**(重点),并预留 Kimi、千问 Key 位
- 能力:品牌项目、GEO 检测任务、多平台 AI 回答监测、提及率/Share of Voice/引用率、竞品曝光、情绪判断、Prompt 库、信源引用分析、定时任务、用户/会员/后台
- 二开接入点:`backend/services/`(检测逻辑)、`backend/routes/`(API)、`backend/.env`(AI Key)
- 启动:`npm install`(根+backend+前端) → 配 `.env` → `npm run dev`

### ② 发布端 geo-publisher(MediaPublishPlatform, MIT)
- 技术:后端 Flask(5409)+Playwright / 前端 Vue3(5173) / SQLite
- 已支持 9 平台:小红书、腾讯视频号、抖音、快手、TikTok、Instagram、Facebook、B站、百家号
- 能力:一键批量发布、定时发布、多账号 Cookie 管理、发布记录、RESTful API(`/postVideosToMultiplePlatforms` 等)
- 二开接入点:`sau_backend/newFileUpload/platform_configs.py`(加平台只改配置)、`sau_backend/sau_backend.py`(API)
- 启动:`pip install -r requirements.txt` → `playwright install chromium` → `python db/createTable.py` → `python sau_backend/sau_backend.py`

---

## 三、整合架构(目标态)

```
┌─────────────────────────────────────────────────────────────┐
│  统一控制台(规划 apps/geo-core 或复用监控端前端)            │
│  品牌/关键词配置 · AI生成策略 · 发布计划 · 可见性看板       │
└───────────┬───────────────────────────┬─────────────────────┘
            │                           │
   ┌────────▼─────────┐       ┌─────────▼──────────┐
   │  AI 生成模块      │       │  发布端 MPP API     │
   │ (LLMClient抽象)   │──────▶│  localhost:5409     │
   │ 用户自有API       │       │  自动发到各平台     │
   └──────────────────┘       └─────────┬──────────┘
            │                           │
   ┌────────▼─────────┐                 │
   │  监控端 Goodie    │◀── 检测品牌在    │
   │  localhost:3002   │    AI的可见性    │
   └──────────────────┘                  │
                                         │
                          发布后回流:再监测可见性是否提升(闭环)
```

**闭环**:配置品牌词 → AI 按平台调性生成图文 → MPP 定时发布到矩阵号 → Goodie 监测发布后品牌在豆包/元宝/DeepSeek 的提及与引用 → 看板展示效果。

---

## 四、分期计划(MVP 优先)

- [x] **P0 跑通**:两端本地独立启动验证 ✅ 已实测
- [x] **P1 接入自有 API**:用户 agnes AI 已接监控端 deepseek 位 ✅ 实测检测返回正常
- [x] **P2 AI 生成模块**:`apps/geo-core/llm_client.py` + `content_generator.py` ✅ 实测生成结构化内容
- [x] **P3 整合调度**:`apps/geo-core/pipeline.py` + `publisher_client.py`(调 MPP API)✅ 已联调
- [x] **P4 可见性闭环**:`apps/geo-core/visibility_loop.py` + `dashboard_api.py` ✅ 实测闭环归因 Δ 可见

---

## 五、实际验证结果(2026-09-01)

| 模块 | 地址 | 状态 | 验证方式 |
|------|------|------|----------|
| 监控端后端 | localhost:3002 | ✅ | `/api/health` OK;登录admin跑 deepseek(agnes)检测返回品牌介绍 |
| 监控端前端 | localhost:3001 | ✅ | HTTP 200 |
| 发布端 | localhost:5409 | ✅ | `/getPlatformStats` 返回 200 统计 |
| AI 生成模块 | apps/geo-core | ✅ | dry-run 用 agnes 生成小红书/抖音双调性内容,JSON 解析正确 |
| 用户 AI API | agnes-2.5-flash | ✅ | chat/completions 实测返回正常 |

**踩坑记录**:
- 本机需开 VPN 才能 clone/install GitHub。
- 监控端 `sqlite3` 需 VS2022 构建工具: `winget install Microsoft.VisualStudio.2022.BuildTools --override "--wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"`,再 `npm approve-scripts sqlite3` + `npm rebuild sqlite3`。
- 发布端 pip 用清华镜像缺 `aiofiles==24.1.0` 等,改官方源: `pip install -r requirements.txt -i https://pypi.org/simple`。
- 发布端 db 路径: `createTable.py` 建在根 `database.db`,但代码读 `sau_backend/db/database.db`,需复制过去(已处理)。
- 用户 API 模型名必须用 `agnes-2.5-flash`(通用名如 gpt-4o-mini 返回 model_not_found)。

---

## 六、启动方式

- **一键启动**: `powershell -ExecutionPolicy Bypass -File start_all.ps1`
- **手动**:
  - 监控端后端: `cd packages/geo-monitor/backend && node app.js`
  - 监控端前端: `cd packages/geo-monitor/nextjs-frontend && npx next dev -p 3001`
  - 发布端: `cd packages/geo-publisher/sau_backend && $env:PYTHONPATH="." && ..\venv\Scripts\python.exe sau_backend.py`
  - 整合层看板: `cd apps/geo-core && .\venv\Scripts\python.exe dashboard_api.py`(http://localhost:7000)
  - AI 生成测试: `cd apps/geo-core && .\venv\Scripts\python.exe pipeline.py --brand X --topic Y --platforms xiaohongshu douyin --dry-run`
  - MVP 验收: `cd apps/geo-core && $env:AGNES_API_KEY="你的Key" ; .\venv\Scripts\python.exe acceptance_test.py`
  - **一键回归(推荐)**: `cd apps/geo-core && $env:AGNES_API_KEY="你的Key" ; .\venv\Scripts\python.exe run_all.py`
    - 跳过真实发布: `.\venv\Scripts\python.exe run_all.py --skip-real`
    - 只跑部分: `.\venv\Scripts\python.exe run_all.py --only F8 F14`
  - **每日定时调度**: Windows 任务计划程序触发 `pipeline.py` 的具体 `schtasks` 命令见 `docs/PRD.md` 4.8(F11 AC8.2,可复现)
  - **本机 CI 等价(推荐日常用)**: `powershell -ExecutionPolicy Bypass -File start_and_ci.ps1`
    - 一键启动三端 + 整合层(7000) + 跑 `ci_check.ps1`(= `run_all.py --skip-real`),生成 `ci_report.txt`
    - 仅跑门禁(服务已在跑时): `powershell -ExecutionPolicy Bypass -File ci_check.ps1`
    - 前置: 三端(3002/5409/7000)在跑 + `AGNES_API_KEY` 已设(F14/F17 调 LLM 需要)
  - **零操作自运维(推荐)**: 注册 Windows 定时任务,每日 09:00 自动启动服务+跑门禁:
    `powershell -ExecutionPolicy Bypass -File install_ci_task.ps1`(任务名 `GEO-DailyCI`,状态见 `Get-ScheduledTask -TaskName GEO-DailyCI`);手动触发 `Start-ScheduledTask -TaskName GEO-DailyCI`

---

## 七、MVP 验收结果(2026-09-02,37/37 通过)

以小红书为唯一已验证真实发布平台,端到端跑通全链路并逐项验收。一键回归:

```powershell
cd apps/geo-core
$env:AGNES_API_KEY="你的Key"
.\venv\Scripts\python.exe run_all.py        # 全部(含真实发布 F7/F10)
```

各验收脚本(均落 `apps/geo-core/`):
| 编号 | 文件 | 验收范围 | 结果 |
|------|------|----------|------|
| F8  | acceptance_accounts_test.py | 账号管理/登录状态展示 | ✅ 5/5 |
| F14 | acceptance_video_test.py | 短视频脚本生成+落库+接口 | ✅ 7/7 |
| F11 | acceptance_scheduler_test.py | 调度/定时发布契约 | ✅ 5/5 |
| F17 | acceptance_loop_test.py | 可见性闭环看板/归因 | ✅ 8/8(Δ+1.63) |
| F7  | acceptance_real_publish_test.py | 小红书真实发布+入口 | ✅ 5/5 |
| F10 | acceptance_pipeline_test.py | 端到端 Pipeline | ✅ 7/7 |

合计 **37/37 PASS**(详见 `docs/MVP_ACCEPTANCE_REPORT.md`)。

整合层生产级文件(无假功能):
`db.py / llm_client.py / content_generator.py / publisher_client.py / monitor_client.py / pipeline.py / dashboard_api.py / visibility_loop.py / proc_utils.py(进程清理) / run_all.py(一键回归) / acceptance_*.py`

**稳固化要点**:
- 真实发布前统一 `proc_utils.pre_publish_cleanup()` 杀净残留 Chromium,避免 180s 超时。
- 发布端必须**单实例**运行,否则多进程争用导致发布超时。
- 真实发布依赖人工录入的小红书 Cookie(`sau_backend/cookiesFile/`);其他平台 uploader 未适配,发布会明确报错(非静默)。

---

## 八、待办(下一期/完善期)

- [ ] 多平台图文发布(B站/抖音/快手/视频号等 uploader 适配;当前仅小红书验证)【按"不在平台深挖/视频类不做"原则,近期不做】
- [ ] 短视频文件端到端发布(脚本生成已通,缺视频素材+平台视频 uploader 适配)【用户禁令:视频类不做】
- [x] 统一品牌/账号后台 Web UI(F16) —— 已由 geo-core 统一后台实现(账号管理/监测-品牌管理/一键发布/定时/洞察/闭环/复盘/告警/统一报表导出入口,替代多系统切换)
- [x] 报表快照与导出(F13) —— CSV + JSON 全量结构化导出,验收通过(见 acceptance_export_test.py)
- [ ] 监测平台扩展:豆包(配 Key)/Kimi/元宝/通义(真实 endpoint,禁止占位)

---

## 九、CI 与代码托管(2026-09-02)

### 代码托管
- **Gitee(主,中文/免 VPN)**: `https://gitee.com/ganfeng12300/geo-articles` —— 代码已推送,日常看代码/备份用这个。
- **GitHub(备)**: `https://github.com/ganfeng321/geo-win` —— 账号 `ganfeng321` 因 billing 被锁定,GitHub Actions 暂不可用;代码已同步,**解锁后 `git push origin main` 即可自动跑 `.github/workflows/regression.yml`,无需改配置**。

### CI 现状
- GitHub Actions 当前 5s 失败根因:账号 billing 锁定(`account is locked due to a billing issue`),非代码问题。
- Gitee 个人免费仓库不提供 CI 服务(Gitee Go 为企业/付费)。
- **因此改用本机 CI 等价方案**(见 `CI.md`): `ci_check.ps1` 在本地提供与云端 Actions 等价的门禁(自动定位 Python → 跑 `run_all.py --skip-real` → 退出码 0=绿 → 生成 `ci_report.txt`)。
- 最近一次本机验证: **PASS ✓ 8/8 通过(294.4s)**(F8/F14/F11/F12/F13/F17/F19/F7B, `--skip-real` 跳过真实发布 F7/F10/F18)。
- 完整真实发布回归(不含 `--skip-real`)此前实测 **11/11 通过**,真实发布会真在小红书发帖(属验收必要副作用)。
