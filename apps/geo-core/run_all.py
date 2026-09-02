# 一键回归: 顺序跑全部验收脚本, 汇总报告, 退出码聚合
# 用法:
#   cd apps/geo-core
#   $env:AGNES_API_KEY="你的Key"
#   .\venv\Scripts\python.exe run_all.py            # 全部(含真实发布)
#   .\venv\Scripts\python.exe run_all.py --skip-real  # 跳过会真实发布的用例(F7/F10)
#   .\venv\Scripts\python.exe run_all.py --only F8 F14  # 只跑指定
import sys
import argparse
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 跨平台 venv 解释器: Windows 用 Scripts/python.exe, Linux/macOS 用 bin/python
if (HERE / "venv" / "Scripts" / "python.exe").exists():
    PY = HERE / "venv" / "Scripts" / "python.exe"
else:
    PY = HERE / "venv" / "bin" / "python"

# 全部验收用例(顺序即依赖顺序: 先无副作用的接口/生成, 再真实发布/闭环)
ALL_SUITES = [
    ("F8",  "acceptance_accounts_test.py",   "账号管理",          False),
    ("F14", "acceptance_video_test.py",      "短视频脚本生成",     False),
    ("F11", "acceptance_scheduler_test.py",  "调度契约",          False),
    ("F12", "acceptance_alert_test.py",      "告警推送闭环",       False),
    ("F13", "acceptance_export_test.py",     "报表快照与导出",     False),
    ("F17", "acceptance_loop_test.py",       "可见性闭环看板",     False),
    ("F18", "acceptance_auto_publish_test.py","定时自动发布落地",   True),
    ("F19", "acceptance_ui_test.py",         "统一后台 UI 美化",    False),
    ("F7",  "acceptance_real_publish_test.py","真实发布(小红书)",  True),
    ("F7B", "acceptance_publish_hardening_test.py","真实发布加固(探针/超时/错误分类)", False),
    ("F10", "acceptance_pipeline_test.py",   "端到端 Pipeline",    True),
]

# 真实发布前需要先做进程清理
REAL_SUITES = {name for name, _, _, real in ALL_SUITES if real}


def run_suite(name, script, title, is_real, do_cleanup):
    print("\n" + "=" * 64)
    print(f"▶ [{name}] {title}  ({script})")
    print("=" * 64)
    if is_real and do_cleanup:
        # 复用到 proc_utils 的发布前清理(杀残留 Chromium), 避免 180s 超时
        sys.path.insert(0, str(HERE))
        try:
            from proc_utils import pre_publish_cleanup
            pre_publish_cleanup(verbose=True)
        except Exception as e:
            print(f"  [警告] 发布前清理失败: {e}")
    t0 = time.time()
    try:
        proc = subprocess.run(
            [str(PY), str(HERE / script)],
            cwd=str(HERE),
            env={**__import__("os").environ},
            timeout=900,
        )
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        print(f"  [超时] {name} 超过 900s 未完成")
        rc = 2
    except FileNotFoundError:
        print(f"  [错误] 找不到解释器 {PY}, 请先创建 venv")
        rc = 3
    print(f"◀ [{name}] 退出码={rc}  耗时 {time.time()-t0:.1f}s")
    return rc == 0


def main():
    ap = argparse.ArgumentParser(description="GEO 整合层一键验收回归")
    ap.add_argument("--skip-real", action="store_true", help="跳过会真实发布的用例(F7/F10)")
    ap.add_argument("--only", nargs="+", help="只跑指定编号, 如 --only F8 F14")
    ap.add_argument("--no-cleanup", action="store_true", help="真实发布前不做 Chromium 进程清理")
    args = ap.parse_args()

    suites = ALL_SUITES
    if args.only:
        want = set(args.only)
        suites = [s for s in ALL_SUITES if s[0] in want]
        if not suites:
            print(f"无匹配用例: {args.only} (可选: {[s[0] for s in ALL_SUITES]})")
            sys.exit(1)
    if args.skip_real:
        suites = [s for s in suites if not s[3]]

    do_cleanup = not args.no_cleanup

    print("=" * 64)
    print("GEO 整合层 · 一键验收回归")
    print(f"解释器: {PY}")
    print(f"用例数: {len(suites)}  | 真实发布清理: {'开' if do_cleanup else '关'}")
    if not __import__("os").environ.get("AGNES_API_KEY"):
        print("[提示] 未设置 AGNES_API_KEY, 涉及 LLM 生成的用例可能失败")
    print("=" * 64)

    results = []
    t_all = time.time()
    for name, script, title, is_real in suites:
        ok = run_suite(name, script, title, is_real, do_cleanup)
        results.append((name, title, ok))

    # 汇总
    print("\n" + "#" * 64)
    print("验收汇总")
    print("#" * 64)
    passed = sum(1 for _, _, ok in results if ok)
    for name, title, ok in results:
        print(f"  [{'✓ PASS' if ok else '✗ FAIL'}] {name} {title}")
    print(f"\n总计: {passed}/{len(results)} 通过, 耗时 {time.time()-t_all:.1f}s")

    # 退出码: 任一失败=1
    failed = [n for n, _, ok in results if not ok]
    if failed:
        print(f"失败用例: {failed}")
        sys.exit(1)
    print("全部通过 ✓")
    sys.exit(0)


if __name__ == "__main__":
    main()
