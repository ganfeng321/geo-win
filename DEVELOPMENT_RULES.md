# GEO 自用品 · 开发规则 (DEVELOPMENT RULES)

> 目标:基于开源项目二开,构建一个**国内市场的 GEO(生成式引擎优化)自用平台**。
> 核心能力:① GEO 可见性监控 ② AI 自动生成内容 ③ 多平台自动发布。
> 性质:**仅自用,不商用**。AI 生成调用用户自有 API。

---

## 0. 项目定位与范围

- **市场**:国内(豆包 / 元宝 / DeepSeek / Kimi / 通义千问等 AI 平台;小红书 / 抖音 / 知乎 / 百家号等发布平台)。
- **不做**:海外平台深度适配(预留扩展位即可)、商业化计费、多租户 SaaS。
- **合规红线**:
  - 仅用开源项目、自用,不破解/不逆向平台私有接口牟利。
  - MPP 发布基于 Playwright 模拟登录,**控制频率、避免批量封号**,量小自用可控。
  - 用户凭证(平台账号、AI API Key)一律走环境变量 / 本地配置文件,**禁止硬编码、禁止提交仓库**。

---

## 1. 仓库与目录结构

采用 monorepo,两个开源项目作为独立子模块保留(便于后续拉取上游更新):

```
GEO-XINXIANGMU-00/
├── DEVELOPMENT_RULES.md        # 本文件
├── README.md                   # 启动与架构说明
├── packages/
│   ├── geo-monitor/            # Goodie AI-GEO(Next.js+Express+SQLite) — 监控端
│   └── geo-publisher/          # MediaPublishPlatform(Python+Flask+Playwright) — 发布端
├── apps/
│   └── geo-core/               # 自研整合层:统一品牌/账号后台 + AI 生成模块 + 调度
├── config/                     # 本地配置样例(.env.example,不含真实密钥)
└── memory/                     # 工作记忆(已在 .codebuddy/memory)
```

**规则**:
- 开源项目**不改动其核心目录结构**,二开改动集中在 `apps/geo-core` 或通过接口/配置接入。
- 必须改开源项目代码时,用分支 `fork-dev` 并加 `// [GEO-EDIT]` 注释标注改动位置与原因。

---

## 2. 技术栈约定

| 层 | 技术 | 说明 |
|----|------|------|
| 监控端(二开) | Next.js + React + Ant Design / Express + Sequelize / SQLite | 沿用 Goodie 原栈 |
| 发布端(二开) | Python 3.10 + Flask + Playwright + SQLite / Vue3 + Element Plus | 沿用 MPP 原栈 |
| 整合层(自研) | 待定(倾向 Node/Python 轻量服务,或复用监控端 Next.js) | 统一入口、调度、AI 生成 |
| AI 生成 | 用户自有 API(接口适配层隔离,支持多家) | 协议签名未定,先抽象 `LLMClient` 接口 |
| 配置 | `.env` + `.env.example` | 真实密钥不入库 |

---

## 3. 开发流程规范

1. **先跑通,再二开**:每个开源项目 clone 后先本地启动验证,记录启动命令到 README。
2. **小步提交**:每完成一个可运行功能点提交一次,commit message 中文、说明"做了什么+为什么"。
3. **接口优先**:整合层与两端通过 REST API / 配置文件解耦,不直接改对方内部逻辑。
4. **改动可追溯**:改开源代码必加 `// [GEO-EDIT]` 标注。
5. **不破坏原功能**:二开新增能力,不删原项目可用功能。

---

## 4. 质量与效率约定

- **可运行优先**:每个改动必须能本地启动验证,不交付"跑不起来"的代码。
- **配置外置**:所有账号、Key、平台参数走配置,环境差异不写死。
- **最小可用(MVP)先行**:先打通"监控→生成→发布"单链路,再补竞品分析/趋势图等。
- **中文注释**:代码注释、文档用中文(自用项目,便于维护)。
- **依赖锁定**:记录 `package.json` / `requirements.txt` 版本,避免环境漂移。

---

## 5. AI 生成模块接口约定(预留)

```python
# 抽象接口,具体实现等用户给出 API 后填充
class LLMClient:
    def generate(self, platform: str, brand: str, prompt: str) -> str:
        """按平台调性生成内容。platform 决定语气/长度/格式。"""
        raise NotImplementedError
```
- 用户自有 API 接入后,新增一个实现类即可,不改动调用方。

---

## 6. 当前待确认(用户后续提供)

> 更新(2026-09-02):以下 4 项已在实际开发中确认落地,本节保留为历史决策记录,不再阻塞交付。

- [x] 用户自有 AI API 的接入方式(地址/协议/Key) —— 已确认:统一走 agnes 网关(agnes-2.5-flash),OpenAI 兼容 `AGNES_BASE_URL`+`AGNES_API_KEY`+`AGNES_MODEL`,监控端与整合层共用,已验证可用。
- [x] 发布端:Playwright 模拟登录(MPP 现状) or 蚁小二开放平台 API —— 已确认:用 MPP(Flask+Playwright)+ 用户自有账号 Cookie,不接蚁小二;F7/F7B 已落地小红书图文发布。
- [x] 内容形态:纯图文 / 含短视频脚本 —— 已确认:图文为主 + 短视频口播脚本生成(F14,按用户"视频类不做"决策仅生成不端到端发布视频)。
- [x] 一期是否需要 GEO 监控闭环 —— 已确认:需要,且已完成(F17 可见性闭环 + F20 自动复盘换角度重生成 + 看板归因)。

---

## 7. 禁忌

- ❌ 不把密钥/账号明文写进代码或提交。
- ❌ 不逆向平台私有接口做规模化黑产式发布。
- ❌ 不引入不必要的重依赖(保持自用品轻量)。
- ❌ 不删改开源项目 LICENSE。
