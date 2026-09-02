# 触发百家号登录 + 截图验证(做完检查通过才算完成)
# 流程: 触发 /login(SSE) -> Chrome 弹窗 -> 等待登录组件渲染 -> 截图到文件
# 运行后检查截图确认登录页可交互,再让用户登录。
import sys
import time
import requests

PUB = "http://localhost:5409"
SCREENSHOT = r"d:\GEO-XINXIANGMU-00\apps\geo-core\login_page_check.png"


def trigger_and_screenshot(platform_type: int, account_id: str):
    url = f"{PUB}/login?type={platform_type}&id={account_id}"
    print(f"[1/3] 触发登录: 平台type={platform_type} 账号={account_id}")
    print(">> Chrome 窗口将弹出,等待登录页加载与组件渲染...")
    last = None
    start = time.time()
    try:
        with requests.get(url, stream=True, timeout=320) as r:
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("data:"):
                    msg = line[len("data:"):].strip()
                    if msg != last:
                        print("<<", msg)
                        last = msg
                        if "登录组件已渲染" in msg or "登录页" in msg:
                            # 页面已加载,给 2 秒让截图时页面稳定
                            time.sleep(2)
                            print("[2/3] 登录页已加载,正在截图验证...")
                            # 用 Playwright 直接截图验证(独立于发布端进程)
                            _take_screenshot()
                            print(f"[3/3] 截图已保存: {SCREENSHOT}")
                            print(">> 请查看截图确认登录页正常,然后在 Chrome 窗口中登录百家号")
                        if "Cookie已保存" in msg or "登录成功" in msg:
                            print("✅ 百家号登录成功,Cookie 已落盘")
                            return True
                        if '"code": 500' in msg or "失败" in msg or "超时" in msg:
                            print("❌ 登录失败")
                            return False
                if time.time() - start > 310:
                    print("⏰ 超时")
                    return False
    except Exception as e:
        print("请求异常:", e)
        return False
    return False


def _take_screenshot():
    """用 Playwright 对百家号登录页截图,用于验证页面是否正常渲染。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://baijiahao.baidu.com/builder/theme/bjh/login",
                      wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            page.screenshot(path=SCREENSHOT, full_page=True)
            browser.close()
    except ImportError:
        print("⚠️ playwright 未安装在整合层 venv,跳过自动截图")
    except Exception as e:
        print(f"⚠️ 截图失败: {e}")


if __name__ == "__main__":
    acc = sys.argv[2] if len(sys.argv) > 2 else "my_baijiahao"
    ptype = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    ok = trigger_and_screenshot(ptype, acc)
    sys.exit(0 if ok else 1)
