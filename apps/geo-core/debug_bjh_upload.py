# 调试百家号图文页上传按钮选择器
# 用已录入的 Cookie 加载百家号图文页,截图并 dump 上传区域 HTML
import asyncio
from playwright.async_api import async_playwright

COOKIE_FILE = r"d:\GEO-XINXIANGMU-00\packages\geo-publisher\sau_backend\cookiesFile\baijiahao_cookie_my_baijiahao.json"
PAGE_URL = "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1"
SCREENSHOT = r"d:\GEO-XINXIANGMU-00\apps\geo-core\bjh_edit_page.png"
CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # 弹窗看真实渲染结果
            executable_path=CHROME,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(storage_state=COOKIE_FILE)
        page = await context.new_page()
        await page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(10000)  # 等 SPA 渲染完(10秒)
        # 截图
        await page.screenshot(path=SCREENSHOT, full_page=True)
        print(f"截图保存: {SCREENSHOT}")
        # 尝试找旧选择器
        old_sel = "div._5eb0d99a7a8a2180-uploadEventContainer"
        old_el = await page.query_selector(old_sel)
        print(f"旧选择器 '{old_sel}': {'FOUND' if old_el else 'NOT FOUND'}")
        # 尝试找常见上传相关元素
        for sel in [
            "input[type='file']",
            "[class*='upload']",
            "[class*='Upload']",
            "[id*='upload']",
            "[id*='Upload']",
            "[class*='cover']",
            "[class*='image']",
            "[class*='file']",
            "div[role='button']",
        ]:
            els = await page.query_selector_all(sel)
            if els:
                print(f"  '{sel}': {len(els)} 个匹配")
                for el in els[:3]:
                    tag = await el.evaluate("el => el.tagName")
                    cls = await el.evaluate("el => el.className")
                    id_ = await el.evaluate("el => el.id")
                    print(f"    <{tag}> class={cls!r} id={id_!r}")
        # dump body 前 2000 字符看结构
        html = await page.evaluate("document.body.innerHTML.substring(0, 3000)")
        print(f"\nBODY HTML (前3000字符):\n{html}")
        await browser.close()


asyncio.run(main())
