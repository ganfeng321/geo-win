# 进程自检与清理工具(稳固化用)
# 职责:
#   1. ensure_services(): 检查三端服务是否存活, 缺失即给出明确提示(不静默)
#   2. cleanup_chromium(): 真实发布前杀净残留 Chromium 进程, 避免 180s 超时
#   3. pre_publish_cleanup(): 组合上述两步, 供真实发布类验收/生产调用前复用
import os
import sys
import time
import signal

import requests

from config import MONITOR_BASE, PUBLISHER_BASE, CORE_BASE

# 需要存活的核心服务
SERVICES = {
    "监控端(3002)": "http://localhost:3002/api/health",
    "发布端(5409)": f"{PUBLISHER_BASE}/getPlatformStats",
    "整合层(7000)": f"{CORE_BASE}/api/overview",
}

# 发布端 Playwright 启动的残留进程关键名(Windows 下为 headless_shell / chrome)
CHROMIUM_KEYWORDS = ("headless_shell", "chrome", "chromium", "ms-playwright")


def _kill_proc(proc) -> bool:
    try:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
        return True
    except Exception:
        try:
            proc.kill()
            return True
        except Exception:
            return False


def cleanup_chromium(verbose: bool = True) -> int:
    """杀净残留 Chromium 进程, 返回被杀数量。"""
    try:
        import psutil
    except ImportError:
        if verbose:
            print("  [警告] psutil 未安装, 跳过 Chromium 清理(请 pip install psutil)")
        return 0

    killed = 0
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmd = " ".join(proc.info.get("cmdline") or []).lower()
        except Exception:
            continue
        if any(k in name or k in cmd for k in CHROMIUM_KEYWORDS):
            # 保护自身: 不杀当前进程树
            if proc.pid == os.getpid():
                continue
            if _kill_proc(proc):
                killed += 1
    if verbose and killed:
        print(f"  [清理] 已杀净 {killed} 个残留浏览器进程")
    return killed


def check_service(url: str, timeout: int = 5) -> bool:
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False


def ensure_services(verbose: bool = True) -> bool:
    """检查三端是否存活; 返回是否全部存活。"""
    all_ok = True
    for name, url in SERVICES.items():
        ok = check_service(url)
        if verbose:
            print(f"  [{'✓' if ok else '✗'}] {name} {url}")
        all_ok = all_ok and ok
    return all_ok


def pre_publish_cleanup(verbose: bool = True):
    """真实发布前统一调用: 服务存活检查 + 浏览器进程清理。"""
    if verbose:
        print("== 发布前自检 ==")
    svc_ok = ensure_services(verbose=verbose)
    cleanup_chromium(verbose=verbose)
    if verbose:
        print("== 自检完成 ==\n")
    return svc_ok


if __name__ == "__main__":
    pre_publish_cleanup()
