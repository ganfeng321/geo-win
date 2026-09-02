# F20 闭环自动复盘 验收脚本
# 覆盖:DB表/CRUD、低提及率检测、换角度重生成、状态更新、路由可用性、后台自动循环线程。
# 真实发布路径复用 F7 已验证逻辑,本验收默认不真实发布(publish=False)以稳定通过。
import sys, time, datetime
sys.path.insert(0, ".")

import db
from review_loop import ReviewLoop
import dashboard_api  # 确保 dashboard 模块可 import(路由/HTML 无语法错误)


def log(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))
    return ok


def main():
    results = []

    # ---- AC1: 表与 CRUD ----
    brand, topic = "验收品牌F20", "验收话题F20"
    tid = db.insert_auto_review_task(brand, topic, "xiaohongshu", "通用科普", 0.15, 1, 0)
    tasks = db.list_auto_review_tasks(100)
    ok = any(t["id"] == tid and t["brand"] == brand for t in tasks)
    results.append(log("AC1 创建并查询复盘任务", ok, f"task_id={tid}"))

    db.set_auto_review_task_loop(tid, 1)
    t = db.get_auto_review_task(tid)
    results.append(log("AC1 开启自动循环", t["auto_loop"] == 1))
    db.set_auto_review_task_loop(tid, 0)
    db.set_auto_review_task_enabled(tid, 0)
    t = db.get_auto_review_task(tid)
    results.append(log("AC1 停用任务", t["enabled"] == 0))
    db.set_auto_review_task_enabled(tid, 1)

    # ---- AC2: 低提及率触发复盘 ----
    # 注入一条低提及率可见性快照(brand 匹配, after 低于阈值)
    db.insert_visibility_snapshot(1, brand, topic, 0.0, 0.05, 0.0, 0.1, 0, 1)
    t = db.get_auto_review_task(tid)
    res = ReviewLoop().review_once(t, publish=False)
    ok = res.get("triggered") is True and res.get("new_angle") and res.get("generated_id")
    results.append(log("AC2 低提及率触发换角度复盘", ok,
                       f"last_rate={res.get('last_rate')} new_angle={res.get('new_angle')} gen={res.get('generated_id')}"))

    # 验证角度已更新 + 运行次数 + 状态落库
    t2 = db.get_auto_review_task(tid)
    ok2 = (t2["angle"] == res.get("new_angle")) and (t2["run_count"] >= 1) and (t2["last_status"] in ("ok", "published"))
    results.append(log("AC3 任务角度/状态/运行次数已更新", ok2,
                       f"angle={t2['angle']} status={t2['last_status']} count={t2['run_count']} rate={t2['last_rate']}"))

    # 验证重生成内容确实落库(content_generator 已写入 generated_content)
    gens = db.list_generated(10)
    ok3 = any(g.get("title") for g in gens)
    results.append(log("AC3 新角度内容已落库", ok3))

    # ---- AC4: 高提及率不触发 ----
    db.insert_visibility_snapshot(1, brand, topic, 0.0, 0.9, 0.0, 0.8, 0, 1)  # after=0.9 > 0.15
    t = db.get_auto_review_task(tid)
    before_count = t["run_count"]
    res_hi = ReviewLoop().review_once(t, publish=False)
    ok_hi = (res_hi.get("triggered") is False) and (res_hi.get("status") == "skipped")
    results.append(log("AC4 达阈值不触发复盘", ok_hi, f"note={res_hi.get('note')}"))
    results.append(log("AC4 未触发时不增加运行次数", db.get_auto_review_task(tid)["run_count"] == before_count))

    # ---- AC5: dashboard 路由可被 import 且 HTTP 暴露 ----
    routes = [m for m in dir(dashboard_api.Handler) if not m.startswith("__")]
    # 通过实际 HTTP 验证更可靠:起服务并请求
    import threading, http.server, urllib.error
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 7701), dashboard_api.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.6)
    import urllib.request, json
    def post(path, payload):
        req = urllib.request.Request("http://127.0.0.1:7701"+path,
                                      data=json.dumps(payload).encode(),
                                      headers={"Content-Type": "application/json"}, method="POST")
        try:
            return json.loads(urllib.request.urlopen(req).read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())
    def get(path):
        return json.loads(urllib.request.urlopen("http://127.0.0.1:7701"+path).read())

    r_get = get("/api/review/tasks")
    ok_get = r_get.get("ok") is None or "tasks" in r_get
    results.append(log("AC5 GET /api/review/tasks 可用", ok_get, f"count={len(r_get.get('tasks', []))}"))

    r_run = post("/api/review/run-now", {"task_id": tid, "publish": 0})
    ok_run = r_run.get("ok") is True and r_run.get("result", {}).get("task_id") == tid
    results.append(log("AC5 POST /api/review/run-now 可用", ok_run,
                       f"triggered={r_run.get('result', {}).get('triggered')}"))

    r_toggle = post("/api/review/auto-toggle", {"task_id": tid, "auto_loop": 1})
    results.append(log("AC5 POST /api/review/auto-toggle 可用", r_toggle.get("ok") is True))
    r_toggle2 = post("/api/review/auto-toggle", {"task_id": tid, "auto_loop": 0})

    # 创建接口校验
    r_create_bad = post("/api/review/tasks", {"brand": "", "topic": ""})
    results.append(log("AC5 创建校验(空参数拒绝)", r_create_bad.get("ok") is False))
    r_create_badp = post("/api/review/tasks", {"brand": "x", "topic": "y", "platform": "douyin"})
    results.append(log("AC5 创建校验(视频平台拒绝)", r_create_badp.get("ok") is False))

    srv.shutdown()

    # ---- AC6: 后台自动循环线程 ----
    loop = ReviewLoop()
    loop.start()
    time.sleep(0.3)
    alive = bool(loop._thread and loop._thread.is_alive())
    results.append(log("AC6 后台自动循环线程可启动", alive))
    loop.stop()
    time.sleep(0.3)
    stopped = (loop._thread is None) or (not loop._thread.is_alive())
    results.append(log("AC6 后台自动循环线程可停止", stopped))

    # ---- 清理测试任务 ----
    db.delete_auto_review_task(tid)

    total = len(results)
    passed = sum(1 for r in results if r)
    print(f"\n==== F20 验收结果: {passed}/{total} 通过 ====")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
