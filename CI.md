# CI / 回归验证说明

## 现状（2026-09-02）
- **GitHub Actions**：账号 `ganfeng321` 因 billing 被锁定，云端 Actions 无法运行（job 直接 5s 失败，提示 "account is locked due to a billing issue"）。代码已推送至 `github.com/ganfeng321/geo-win`。
- **Gitee**：个人免费仓库不提供 CI 服务（Gitee Go 为企业/付费）。代码已推送至 `gitee.com/ganfeng12300/geo-articles`。

## 本机 CI 等价方案（当前使用）
云端 runner 不可用，改用本机脚本提供同等门禁效果：

```powershell
powershell -ExecutionPolicy Bypass -File ci_check.ps1
```

脚本会：
1. 自动定位 Python（优先 `apps/geo-core/venv`，回退系统 `python`）
2. 运行 `apps/geo-core/run_all.py --skip-real`（跳过真实发布的 F7/F10）
3. 退出码 `0` = 绿（全部通过），非 `0` = 红
4. 生成 `ci_report.txt` 报告

最近一次运行：**PASS ✓ 8/8 通过，耗时 294.4s**（F8/F14/F11/F12/F13/F17/F19/F7B）。

## 前置依赖（运行前请确认）
- 发布端 `sau_backend` 在 `127.0.0.1:5409` 运行
- 整合层 `geo-core` 在 `127.0.0.1:7000` 运行
- 监控端 `geo-monitor` 在 `127.0.0.1:3002` 运行
- 环境变量 `AGNES_API_KEY` 已设置（F14/F17 调用 LLM 需要）

## 云端 CI 恢复方式
- **GitHub**：解锁账号 billing 后，`git push` 到 `main` 即自动触发 `.github/workflows/regression.yml`，无需改动。
- **Gitee**：如需云端跑，需开通 Gitee Go（企业/付费），再按其语法另写流水线。
