# F19 统一后台 UI 美化 验收脚本(纯标准库,稳定可复跑,不依赖真实发布)
import sys, json, subprocess, tempfile, os, urllib.request, urllib.error
sys.path.insert(0, ".")

import dashboard_api  # 确保模块可 import(路由/HTML 无语法错误)


def log(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))
    return ok


def http_get(path, port=7000):
    try:
        return json.loads(urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=10).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())
    except Exception as e:
        return {"__error__": str(e)}


def main():
    results = []
    html = dashboard_api.dashboard_html()
    page = None
    try:
        page = urllib.request.urlopen("http://127.0.0.1:7000/", timeout=10).read().decode()
    except Exception:
        page = html  # 服务未起时用本地生成内容校验

    # AC19.1 页面与关键模块
    ok = ("闭环看板" in html) and all(k in html for k in
         ["定时发布", "账号管理", "一键发布", "机会洞察", "短视频脚本", "监测管理", "自动复盘"])
    results.append(log("AC19.1 七大功能模块齐备", ok))

    # AC19.2 设计令牌(CSS 变量,实际变量名见 :root)
    ok = all(v in html for v in ["--bg:", "--accent:", "--accent2:", "--panel:", "--line:", "--txt:", "--muted:"])
    results.append(log("AC19.2 设计令牌 CSS 变量齐备", ok))

    # AC19.3 趋势图区域已接入(主看板含 trendChart/loopChart 占位,且 spark() 能产出折线)
    ok = ('id="trendChart"' in html) and ('id="loopChart"' in html)
    svg_line = dashboard_api._sparkline([("a", 0.1), ("b", 0.2)])
    ok = ok and ('<polyline' in svg_line) and ('width="240"' in svg_line)
    results.append(log("AC19.3 趋势图区域接入 + SVG 折线", ok))

    # AC19.4 关键数据路由可用(前端主看板/各 tab 实际调用)
    for p in ["/api/generated", "/api/published", "/api/loop", "/api/insights", "/api/scheduler/tasks", "/api/review/tasks"]:
        d = http_get(p)
        ok = ("__error__" not in d) and ("tasks" in d or "insights" in d or "loop" in d or isinstance(d, list))
        results.append(log(f"AC19.4 GET {p} 可用", ok, str(d)[:60]))

    # AC19.5 响应式 viewport + 字体
    ok = ('name="viewport"' in html) and ("font-family" in html)
    results.append(log("AC19.5 viewport 响应式基础", ok))
    ok = ("::-webkit-scrollbar" in html) and ("@media(max-width:760px)" in html)
    results.append(log("AC19.5 自定义滚动条 + 窄屏适配", ok))

    # AC19.6 spark() 增强:渐变面积 + 末端圆点 + 数值标注
    svg = dashboard_api._sparkline([("a", 0.1), ("b", 0.3), ("c", 0.25), ("d", 0.5)])
    ok = ("linearGradient" in svg) and ("<circle" in svg) and ("<text" in svg) and ("<polygon" in svg)
    results.append(log("AC19.6 趋势图渐变面积/圆点/标注", ok))
    ok = ("stroke-dasharray" in svg)  # 网格线
    results.append(log("AC19.6 趋势图网格线", ok))

    # AC19.7 美化增强类:empty/loading/fadeIn/KPI 色条
    ok = (".empty{" in html) and (".loading{" in html) and ("@keyframes fadeIn" in html) and ("@keyframes spin" in html)
    results.append(log("AC19.7 空状态/加载态/进场动画", ok))
    ok = (".kpi .kpi-card::before" in html) and (".card:hover" in html) and (".kpi .kpi-card:hover" in html)
    results.append(log("AC19.7 KPI 色条 + 卡片微交互", ok))

    # AC19.8 前端脚本语法(node --check)
    s = html.find("<script>")
    e = html.rfind("</script>")
    script = html[s + 8:e]
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(script)
        js_path = f.name
    try:
        r = subprocess.run(["node", "--check", js_path], capture_output=True, text=True, timeout=30)
        results.append(log("AC19.8 前端脚本语法(node --check)", r.returncode == 0, r.stderr[:120]))
    except FileNotFoundError:
        # 无 node 环境时退化为关键危险模式检查(反斜杠转义)
        dangerous = ("split('\\n')" in script) or ("split(\"\\n\")" in script)
        results.append(log("AC19.8 前端脚本无 \\n 转义陷阱", not dangerous, "node 缺失,退化为模式检查"))
    finally:
        os.remove(js_path)

    total = len(results)
    passed = sum(1 for r in results if r)
    print(f"\n==== F19 统一后台 UI 美化验收: {passed}/{total} 通过 ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
