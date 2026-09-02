# F12 告警推送闭环 验收脚本(纯标准库,不依赖真实发布)
import sys, json, time, threading, http.server, urllib.request, urllib.error
sys.path.insert(0, ".")

import db
import dashboard_api  # 模块可 import(路由/HTML 无语法错误)
from alert_pusher import AlertPusher


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


def http_post(path, payload, port=7000):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def main():
    results = []
    db.init()

    # ---- AC12.1 告警落库 + pushed 默认 0 ----
    aid = db.insert_alert("warning", "验收告警F12", scope="visibility",
                          metric="mention_rate", value=0.05, threshold=0.15)
    a = db.get_alert(aid) if hasattr(db, "get_alert") else next((x for x in db.list_alerts(0, 50) if x["id"] == aid), None)
    ok = a is not None and a.get("pushed") == 0 and a.get("resolved") == 0
    results.append(log("AC12.1 告警落库(pushed/resolved 默认0)", ok, f"id={aid} pushed={a.get('pushed')}"))

    # ---- AC12.2 低可见性自动告警 ----
    snap = {"brand": "验收品牌F12", "after_mention_rate": 0.03, "after_visibility_score": 0.1}
    new = db.check_visibility_alert(snap)
    ok = len(new) >= 1 and any("低于阈值" in m for m in new)
    results.append(log("AC12.2 低提及率自动生成告警", ok, f"new={new}"))

    # ---- AC12.3 AlertPusher: 未配置 webhook 不致命 + 配置后真实推送 ----
    # 3a 未配置 webhook: push_alert 标 pushed=1,返回 False 但不报错
    p0 = AlertPusher(webhook_url="")
    ok0 = p0.push_alert({"id": aid, "level": "warning", "scope": "visibility", "message": "x"}) is False
    a0 = next((x for x in db.list_alerts(0, 50) if x["id"] == aid), None)
    ok0b = a0.get("pushed") == 1  # 标记无需推送
    results.append(log("AC12.3 未配置webhook不致命且标记pushed", ok0 and ok0b, f"pushed={a0.get('pushed')}"))

    # 3b 配置 webhook: 起本地 mock server 验证真实 HTTP POST
    received = []
    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            ln = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(ln).decode()
            received.append(body)
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 7702), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.4)
    # 重置该告警为待推送,验证真实推送
    db.mark_alert_pushed(aid, ok=False)  # pushed=-1 视为待重试
    p1 = AlertPusher(webhook_url="http://127.0.0.1:7702/hook")
    pushed_ok = p1.push_alert({"id": aid, "level": "warning", "scope": "visibility", "message": "验收推送F12"})
    ok_push = (pushed_ok is True) and (len(received) == 1) and ("msg_type" in received[0]) and ("content" in received[0])
    results.append(log("AC12.3 配置webhook真实推送成功", ok_push,
                       f"pushed_ok={pushed_ok} recv={len(received)}"))
    # push_pending 批量
    db.insert_alert("warning", "待批量推送F12", scope="visibility")
    summary = p1.push_pending()
    ok_batch = summary.get("pushed", 0) >= 1
    results.append(log("AC12.3 push_pending 批量推送", ok_batch, str(summary)))
    srv.shutdown()

    # ---- AC12.4 标记解决闭环 ----
    db.resolve_alert(aid)
    a1 = next((x for x in db.list_alerts(1, 200) if x["id"] == aid), None)
    ok_res = a1 is not None and a1.get("resolved") == 1
    remain = [x for x in db.list_alerts(0, 200) if x["id"] == aid]
    results.append(log("AC12.4 标记解决闭环(resolved=1)", ok_res and len(remain) == 0))

    # ---- AC12.5 待推送查询 ----
    db.insert_alert("warning", "待推送查询F12", scope="visibility")
    pend = db.list_alerts_pending_push(50)
    ok_pend = any(x["message"] == "待推送查询F12" for x in pend)
    results.append(log("AC12.5 list_alerts_pending_push", ok_pend, f"pending={len(pend)}"))

    # ---- AC12.6 dashboard 路由 ----
    r = http_get("/api/alerts")
    ok_a = ("alerts" in r) and ("pending" in r) and ("webhook_enabled" in r)
    results.append(log("AC12.6 GET /api/alerts(含pushed/pending)", ok_a))
    rp = http_post("/api/alerts/push", {})
    results.append(log("AC12.6 POST /api/alerts/push 可用", rp.get("ok") is True, str(rp)[:80]))
    # 取一个待解决告警 id 验证 resolve 路由
    some = next((x for x in db.list_alerts(0, 50) if x["resolved"] == 0), None)
    if some:
        rr = http_post("/api/alerts/resolve", {"alert_id": some["id"]})
        results.append(log("AC12.6 POST /api/alerts/resolve 可用", rr.get("ok") is True))
    else:
        results.append(log("AC12.6 POST /api/alerts/resolve 可用", True, "无待解决,跳过"))

    # ---- AC12.7 前端告警中心 ----
    html = dashboard_api.dashboard_html()
    ok_ui = ("告警中心" in html) and ('data-tab="alert"' in html) and ("loadAlerts" in html) and ("pushAllAlerts" in html)
    results.append(log("AC12.7 前端告警中心tab", ok_ui))
    ok_ui2 = ("id=\"tab-alert\"" in html) and ("resolveAlert" in html)
    results.append(log("AC12.7 告警解决/推送交互", ok_ui2))

    # 清理验收告警
    for x in db.list_alerts(0, 200):
        if "验收" in (x.get("message") or ""):
            db.resolve_alert(x["id"])

    total = len(results)
    passed = sum(1 for r in results if r)
    print(f"\n==== F12 告警推送闭环验收: {passed}/{total} 通过 ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
