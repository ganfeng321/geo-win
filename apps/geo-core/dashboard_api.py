# 整合层闭环看板 API(轻量 HTTP 服务)
# 聚合: 监控端可见性(dashboard.trend/summary) + 整合层生成/发布 + 闭环归因快照
# 端点:
#   GET /api/overview            -> {generated, published, failed, monitor_projects, latest_snapshot}
#   GET /api/generated           -> 生成列表
#   GET /api/published           -> 发布列表
#   GET /api/monitor/:project_id -> 监控端看板(summary+trend),真实数据
#   GET /api/loop                -> 闭环归因快照列表(visibility_snapshots)
#   GET /api/loop/run?pid=&brand=&q= -> 触发一次闭环(基线->检测->对比->落库)
#   GET /                       -> 闭环看板 HTML(真实图表)
import http.server
import json
import socketserver
import urllib.parse
import threading
import datetime
import requests
from db import (
    count_generated, count_publish, list_generated, list_publish, init,
    list_visibility_snapshots, latest_visibility_snapshot,
    list_alerts, check_visibility_alert, list_insights, insert_insight,
    mark_alert_pushed, resolve_alert, list_alerts_pending_push,
    upsert_monitor_project, list_monitor_projects, update_monitor_project_run,
    insert_publish_task, list_publish_tasks, compute_next_run_at, delete_publish_task,
    insert_auto_review_task, list_auto_review_tasks, get_auto_review_task,
    update_auto_review_task_run, update_auto_review_task_angle,
    set_auto_review_task_enabled, set_auto_review_task_loop, delete_auto_review_task,
)
from monitor_client import MonitorClient
from config import PUBLISHER_BASE
from publisher_client import PublisherClient
from insight_generator import InsightGenerator
from content_generator import ContentGenerator
from scheduler import start_scheduler, run_now as scheduler_run_now
from review_loop import ReviewLoop
from alert_pusher import AlertPusher

# F20 后台自动复盘循环线程句柄(模块级, 启动时实例化并 start)
_review_loop = None

init()
PORT = 7000

# 平台 type -> 英文名/中文名 对照(用于后台展示与登录跳转)
PLATFORM_INFO = {
    1: ("xiaohongshu", "小红书"),
    2: ("shipinhao", "视频号"),
    3: ("douyin", "抖音"),
    4: ("kuaishou", "快手"),
    5: ("tiktok", "TikTok"),
    6: ("instagram", "Instagram"),
    7: ("facebook", "Facebook"),
    8: ("bilibili", "B站"),
    9: ("baijiahao", "百家号"),
}


def _json(obj, code=200):
    return code, json.dumps(obj, ensure_ascii=False).encode("utf-8")


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/api/accounts":
                self._send(*_json(_get_accounts()))
            elif path == "/api/overview":
                pub = count_publish()
                fail = count_publish("failed")
                snap = latest_visibility_snapshot()
                # F12: 每次拉取 overview 时按最新快照判定告警(低于阈值则落库),并推送待发告警
                new_alerts = check_visibility_alert(snap)
                push_summary = AlertPusher().push_pending()
                self._send(*_json({
                    "generated": count_generated(),
                    "published": pub,
                    "failed": fail,
                    "monitor_projects": len(MonitorClient().get_projects()),
                    "latest_snapshot": snap,
                    "alerts": list_alerts(0, 20),
                    "new_alerts": new_alerts,
                }))
            elif path == "/api/generated":
                self._send(*_json(list_generated(50)))
            elif path == "/api/published":
                self._send(*_json(list_publish(50)))
            elif path == "/api/projects":
                m = MonitorClient()
                self._send(*_json(m.get_projects()))
            elif path == "/api/monitor/projects":
                self._send(*_json({"projects": list_monitor_projects(100)}))
            elif path.startswith("/api/monitor/") and path.rsplit("/", 1)[-1].isdigit():
                pid = int(path.rsplit("/", 1)[-1])
                m = MonitorClient()
                self._send(*_json(m.dashboard(pid, 30)))
            elif path == "/api/alerts":
                # F12: 告警列表(含推送状态)
                self._send(*_json({"alerts": list_alerts(0, 50),
                                   "pending": len(list_alerts_pending_push(50)),
                                   "webhook_enabled": AlertPusher().enabled()}))
            elif path == "/api/export":
                fmt = qs.get("type", ["csv"])[0].lower()
                if fmt == "json":
                    # F13: JSON 全量结构化导出
                    payload = _export_json()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Disposition",
                                     "attachment; filename=geo_report.json")
                    self.end_headers()
                    self.wfile.write(payload.encode("utf-8"))
                else:
                    # F13: CSV 多表导出(默认)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition",
                                     "attachment; filename=geo_report.csv")
                    self.end_headers()
                    self.wfile.write(_export_csv().encode("utf-8"))
            elif path == "/api/loop":
                self._send(*_json(list_visibility_snapshots(50)))
            elif path == "/api/loop/run":
                from visibility_loop import run_visibility_loop
                pid = int(qs.get("pid", ["0"])[0])
                brand = qs.get("brand", ["测试品牌"])[0]
                q = qs.get("q", ["请介绍该领域的代表品牌"])[0]
                if pid <= 0:
                    self._send(*_json({"error": "pid 必须 > 0"}, 400))
                    return
                res = run_visibility_loop(pid, brand, q, [brand], trigger="manual")
                self._send(*_json(res))
            elif path == "/api/insights":
                self._send(*_json({"insights": list_insights(20)}))
            elif path == "/api/scheduler/tasks":
                # F18: 定时发布任务列表(附下一次运行时间)
                tasks = list_publish_tasks(100)
                for t in tasks:
                    t["next_run_at"] = compute_next_run_at(t) if t.get("enabled") else None
                self._send(*_json({"tasks": tasks, "msg": f"共 {len(tasks)} 个任务"}))
            elif path == "/api/review/tasks":
                # F20: 闭环自动复盘任务列表
                tasks = list_auto_review_tasks(100)
                self._send(*_json({"tasks": tasks, "msg": f"共 {len(tasks)} 个复盘任务"}))
            elif path == "/api/review/auto-status":
                # F20: 后台自动循环线程状态
                self._send(*_json({"running": bool(_review_loop and _review_loop._thread
                                                    and _review_loop._thread.is_alive())}))
            elif path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(dashboard_html().encode("utf-8"))
            else:
                self._send(*_json({"error": "not found"}, 404))
        except Exception as e:
            self._send(*_json({"error": str(e)}, 500))

    def log_message(self, *a):
        pass

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except Exception:
                body = {}
            if path == "/api/publish":
                self._send(*_json(_api_publish(body)))
            elif path == "/api/accounts/login":
                self._send(*_json(_api_trigger_login(body)))
            elif path == "/api/insights/generate":
                brand = (body or {}).get("brand")
                try:
                    g = InsightGenerator()
                    rep = g.generate(brand)
                    self._send(*_json({"ok": True, "report": rep, "msg": "洞察已生成并落库"}))
                except Exception as e:
                    self._send(*_json({"ok": False, "msg": f"洞察生成失败: {e}"}, 500))
            elif path == "/api/generate/video":
                platform = (body or {}).get("platform") or "douyin"
                brand = (body or {}).get("brand") or "示例品牌"
                topic = (body or {}).get("topic") or "GEO优化入门"
                duration = int((body or {}).get("duration", 60))
                try:
                    g = ContentGenerator()
                    rep = g.generate_video_script(platform, brand, topic, duration)
                    ok = rep.get("ok")
                    self._send(*_json({"ok": ok, "msg": rep.get("error") or "短视频脚本已生成",
                                       "result": rep}))
                except Exception as e:
                    self._send(*_json({"ok": False, "msg": f"生成失败: {e}"}, 500))
            elif path == "/api/monitor/projects":
                # F3: 批量创建监测项目(受监控端仅 doubao/deepseek 限制,多平台=多项目覆盖)
                items = (body or {}).get("projects") or []
                if not items:
                    self._send(*_json({"ok": False, "msg": "projects 为空"}))
                    return
                created = []
                errors = []
                m = MonitorClient()
                for it in items:
                    name = it.get("name") or it.get("brand")
                    brand = it.get("brand")
                    kws = it.get("keywords") or []
                    try:
                        rp = m.create_project(name, kws)
                        pid = upsert_monitor_project(name, brand, ",".join(kws),
                                                    "doubao,deepseek", rp.get("id"))
                        update_monitor_project_run(pid, "created", rp.get("id"))
                        created.append({"name": name, "remote_id": rp.get("id"), "db_id": pid})
                    except Exception as e:
                        errors.append({"name": name, "error": str(e)})
                self._send(*_json({"ok": len(created) > 0, "created": created,
                                   "errors": errors,
                                   "msg": f"创建 {len(created)} 个,失败 {len(errors)} 个"}))
            elif path == "/api/monitor/run-all":
                # F3: 批量触发所有监测项目的检测
                projects = list_monitor_projects(100)
                if not projects:
                    self._send(*_json({"ok": False, "msg": "暂无监测项目"}))
                    return
                results = []
                m = MonitorClient()
                q = (body or {}).get("question") or "请介绍该领域的代表品牌及其特点"
                for p in projects:
                    brand = p.get("brand")
                    kws = [k.strip() for k in (p.get("keywords") or "").split(",") if k.strip()]
                    try:
                        det = m.detect(q, brand, kws, project_id=p.get("remote_project_id"))
                        update_monitor_project_run(p["id"], det.get("status") or "done",
                                                   p.get("remote_project_id"))
                        results.append({"name": p.get("name"), "status": det.get("status"),
                                        "record_id": det.get("record_id")})
                    except Exception as e:
                        update_monitor_project_run(p["id"], "error")
                        results.append({"name": p.get("name"), "error": str(e)})
                self._send(*_json({"ok": True, "results": results,
                                   "msg": f"批量检测 {len(results)} 个项目"}))
            elif path == "/api/scheduler/tasks":
                # F18: 创建定时发布任务(仅支持 xiaohongshu)
                brand = (body or {}).get("brand")
                topic = (body or {}).get("topic")
                platform = (body or {}).get("platform") or "xiaohongshu"
                if not brand or not topic:
                    self._send(*_json({"ok": False, "msg": "brand 与 topic 必填"}))
                    return
                if platform != "xiaohongshu":
                    self._send(*_json({"ok": False, "msg": "当前仅支持 xiaohongshu 定时发布(视频平台不做)"}, 400))
                    return
                try:
                    cron_hour = int((body or {}).get("cron_hour", 9))
                    cron_minute = int((body or {}).get("cron_minute", 0))
                except Exception:
                    self._send(*_json({"ok": False, "msg": "cron_hour/cron_minute 必须为整数"}))
                    return
                tid = insert_publish_task(brand, topic, platform, cron_hour, cron_minute, 1)
                self._send(*_json({"ok": True, "task_id": tid,
                                   "next_run_at": compute_next_run_at(
                                       {"cron_hour": cron_hour, "cron_minute": cron_minute, "enabled": 1}),
                                   "msg": "定时发布任务已创建"}))
            elif path == "/api/scheduler/run-now":
                # F18: 立即触发一次任务(验证定时链路真实发布)
                tid = int((body or {}).get("task_id") or 0)
                if tid <= 0:
                    self._send(*_json({"ok": False, "msg": "task_id 必填且 > 0"}))
                    return
                res = scheduler_run_now(tid)
                self._send(*_json(res))
            elif path == "/api/scheduler/delete":
                tid = int((body or {}).get("task_id") or 0)
                if tid <= 0:
                    self._send(*_json({"ok": False, "msg": "task_id 必填且 > 0"}))
                    return
                delete_publish_task(tid)
                self._send(*_json({"ok": True, "msg": f"任务 {tid} 已删除"}))
            elif path == "/api/review/tasks":
                # F20: 创建闭环自动复盘任务
                brand = (body or {}).get("brand")
                topic = (body or {}).get("topic")
                if not brand or not topic:
                    self._send(*_json({"ok": False, "msg": "brand 与 topic 必填"}))
                    return
                platform = (body or {}).get("platform") or "xiaohongshu"
                if platform != "xiaohongshu":
                    self._send(*_json({"ok": False, "msg": "当前仅支持 xiaohongshu(视频平台不做)"}, 400))
                    return
                try:
                    min_rate = float((body or {}).get("min_mention_rate", 0.15))
                except Exception:
                    self._send(*_json({"ok": False, "msg": "min_mention_rate 必须为数字"}))
                    return
                angle = (body or {}).get("angle") or "通用科普"
                auto_loop = int((body or {}).get("auto_loop", 0))
                tid = insert_auto_review_task(brand, topic, platform, angle, min_rate, 1, auto_loop)
                self._send(*_json({"ok": True, "task_id": tid,
                                   "msg": "闭环自动复盘任务已创建"
                                          + ("并开启自动循环" if auto_loop else "")}))
            elif path == "/api/review/run-now":
                # F20: 立即对单个任务执行一次复盘闭环(默认不真实发布,带 publish=1 则真实发布)
                tid = int((body or {}).get("task_id") or 0)
                if tid <= 0:
                    self._send(*_json({"ok": False, "msg": "task_id 必填且 > 0"}))
                    return
                publish = int((body or {}).get("publish", 0)) == 1
                res = ReviewLoop().review_once(get_auto_review_task(tid), publish=publish)
                self._send(*_json({"ok": True, "result": res}))
            elif path == "/api/review/toggle":
                # F20: 启停单个复盘任务
                tid = int((body or {}).get("task_id") or 0)
                enabled = int((body or {}).get("enabled", 1))
                if tid <= 0:
                    self._send(*_json({"ok": False, "msg": "task_id 必填且 > 0"}))
                    return
                set_auto_review_task_enabled(tid, enabled)
                self._send(*_json({"ok": True, "msg": f"任务 {tid} 已{'启用' if enabled else '停用'}"}))
            elif path == "/api/review/auto-toggle":
                # F20: 开关单个任务的自动循环(后台线程每 120s 轮询 auto_loop=1 的任务)
                tid = int((body or {}).get("task_id") or 0)
                auto_loop = int((body or {}).get("auto_loop", 0))
                if tid <= 0:
                    self._send(*_json({"ok": False, "msg": "task_id 必填且 > 0"}))
                    return
                set_auto_review_task_loop(tid, auto_loop)
                loop_word = "开启" if auto_loop else "关闭"
                self._send(*_json({"ok": True,
                                   "msg": f"任务 {tid} 自动循环已{loop_word}"}))
            elif path == "/api/review/delete":
                tid = int((body or {}).get("task_id") or 0)
                if tid <= 0:
                    self._send(*_json({"ok": False, "msg": "task_id 必填且 > 0"}))
                    return
                delete_auto_review_task(tid)
                self._send(*_json({"ok": True, "msg": f"复盘任务 {tid} 已删除"}))
            elif path == "/api/alerts/push":
                # F12: 手动推送(指定 alert_id 或默认推送全部待发)
                aid = (body or {}).get("alert_id")
                if aid:
                    a = next((x for x in list_alerts(0, 200) if x["id"] == int(aid)), None)
                    ok = AlertPusher().push_alert(a) if a else False
                    self._send(*_json({"ok": True, "pushed": 1 if ok else 0,
                                       "msg": f"告警 {aid} {'推送成功' if ok else '推送失败/未配置webhook'}"}))
                else:
                    summary = AlertPusher().push_pending()
                    self._send(*_json({"ok": True, **summary,
                                       "msg": f"已推送 {summary['pushed']} 条,跳过 {summary['skipped']} 条"}))
            elif path == "/api/alerts/resolve":
                # F12: 标记告警已解决(关闭闭环)
                aid = int((body or {}).get("alert_id") or 0)
                if aid <= 0:
                    self._send(*_json({"ok": False, "msg": "alert_id 必填且 > 0"}))
                else:
                    resolve_alert(aid)
                    self._send(*_json({"ok": True, "msg": f"告警 {aid} 已标记为解决"}))
            else:
                self._send(*_json({"error": "not found"}, 404))
        except Exception as e:
            self._send(*_json({"error": str(e)}, 500))


def _export_csv():
    """F13: 导出闭环/生成/发布数据 CSV(UTF-8 BOM,Excel 友好)。"""
    import csv, io
    buf = io.StringIO()
    w = csv.writer(buf)
    # 1) 闭环快照
    w.writerow(["== 可见性闭环快照 =="])
    cols = ["id", "project_id", "brand", "trigger", "before_mention_rate",
            "after_mention_rate", "mention_rate_delta", "before_visibility_score",
            "after_visibility_score", "visibility_score_delta",
            "publish_count_before", "publish_count_after", "captured_at"]
    w.writerow(cols)
    for r in list_visibility_snapshots(200):
        w.writerow([r.get(c, "") for c in cols])
    w.writerow([])
    # 2) 生成内容
    w.writerow(["== 生成内容 =="])
    gcols = ["id", "brand", "topic", "platform", "title", "tags", "model", "status", "created_at"]
    w.writerow(gcols)
    for r in list_generated(200):
        w.writerow([r.get(c, "") for c in gcols])
    w.writerow([])
    # 3) 发布记录
    w.writerow(["== 发布记录 =="])
    pcols = ["id", "generated_content_id", "platform", "account", "status", "error", "published_at"]
    w.writerow(pcols)
    for r in list_publish(200):
        w.writerow([r.get(c, "") for c in pcols])
    # 加 BOM 让 Excel 正确识别 UTF-8
    return "\ufeff" + buf.getvalue()


def _export_json():
    """F13: 导出全量结构化 JSON(闭环/生成/发布/账号/监测项目/告警/洞察),便于二次分析。"""
    data = {
        "version": "1.0",
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "overview": {
            "generated": count_generated(),
            "published": count_publish(),
            "failed": count_publish("failed"),
            "monitor_projects": len(MonitorClient().get_projects()),
        },
        "visibility_snapshots": list_visibility_snapshots(200),
        "generated": list_generated(200),
        "published_records": list_publish(200),
        "accounts": _get_accounts().get("accounts", []),
        "monitor_projects": list_monitor_projects(100),
        "alerts": list_alerts(0, 200),
        "insights": list_insights(20),
    }
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _get_accounts():
    """拉取发布端所有账号(type/status/cookiesFile),供后台展示登录状态。"""
    try:
        r = requests.get(f"{PUBLISHER_BASE}/getAccounts", timeout=10)
        r.raise_for_status()
        rows = r.json().get("data", []) or []
    except Exception as e:
        return {"error": f"无法连接发布端: {e}", "accounts": []}
    accounts = []
    for row in rows:
        # getAccounts 返回 list[list], 列顺序与 user_info 表一致:
        # id, type, filePath, userName, status
        try:
            uid, ptype, cookies_file, user_name, status = row[0], row[1], row[2], row[3], row[4]
        except Exception:
            continue
        info = PLATFORM_INFO.get(int(ptype), ("unknown", f"type{ptype}"))
        accounts.append({
            "id": uid,
            "type": int(ptype),
            "platform_key": info[0],
            "platform_name": info[1],
            "account": user_name,
            "cookiesFile": cookies_file,
            "status": int(status) if status is not None else 0,
            "logged_in": bool(status and int(status) == 1),
        })
    return {"accounts": accounts}


def _api_trigger_login(body):
    """触发发布端 SSE 登录(后台启动,用户在弹窗里登录)。
    返回提示;真正登录成功以 /api/accounts 的 status=1 为准。"""
    ptype = body.get("type")
    account = body.get("account") or body.get("id")
    if not ptype or not account:
        return {"ok": False, "msg": "缺少 type 或 account"}
    # 后台异步触发(登录是 SSE 长连接,这里只 fire-and-forget 启动浏览器)
    def _run():
        try:
            requests.get(
                f"{PUBLISHER_BASE}/login",
                params={"type": ptype, "id": account},
                timeout=5, stream=True,
            )
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()
    info = PLATFORM_INFO.get(int(ptype), ("unknown", f"type{ptype}"))
    return {"ok": True, "msg": f"已触发 {info[1]}({account}) 登录,请在弹出的浏览器窗口中完成登录"}


def _api_publish(body):
    """一键真实发布(图文)。body: {{platform, title, text, tags}}。"""
    platform = body.get("platform")
    title = (body.get("title") or "").strip()
    text = (body.get("text") or "").strip()
    tags = (body.get("tags") or "").strip()
    if not platform:
        return {"ok": False, "msg": "缺少 platform"}
    if not title or not text:
        return {"ok": False, "msg": "标题与正文均不能为空"}
    client = PublisherClient()
    res = client.publish(platform, title, text, tags=tags, file_type=1)
    ok = res.get("status") == "success"
    if res.get("need_login"):
        # 半自动衔接: 提示前端触发登录(已有 /api/accounts/login)
        return {"ok": False, "need_login": True,
                "msg": "账号未登录或 Cookie 缺失,请先触发登录后再发布",
                "error_type": res.get("error_type"), "detail": res}
    return {"ok": ok, "msg": res.get("error") or "发布成功",
            "error_type": res.get("error_type"), "detail": res}


def _sparkline(values, w=240, h=70, color="#7cc4ff"):
    """生成原生 SVG 面积折线图(无第三方依赖)。values: [(label, num)]。
    含网格线、渐变面积填充、末端高亮圆点与最后数值标注。"""
    if not values:
        return '<svg width="%d" height="%d"></svg>' % (w, h)
    pts = [v for _, v in values if v is not None]
    if not pts:
        return '<svg width="%d" height="%d"></svg>' % (w, h)
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1
    n = len(values)
    step = w / max(n - 1, 1)
    pad = 8
    coords = []
    for i, (_, v) in enumerate(values):
        x = i * step
        y = h - pad - ((v - lo) / span) * (h - 2 * pad) if v is not None else h - pad
        coords.append((x, y))
    poly = " ".join("%.1f,%.1f" % (x, y) for x, y in coords)
    area = "0,%d %s %d,%d" % (h, poly, w, h)
    grid = ""
    for g in range(1, 4):
        gy = (h / 4) * g
        grid += '<line x1="0" y1="%.1f" x2="%d" y2="%.1f" stroke="#2a3340" stroke-width="1" stroke-dasharray="3 4"/>' % (gy, w, gy)
    last_x, last_y = coords[-1]
    last_v = values[-1][1]
    dot = '<circle cx="%.1f" cy="%.1f" r="3.5" fill="%s" stroke="#0b0e14" stroke-width="1.5"/>' % (last_x, last_y, color)
    label = '<text x="%.1f" y="%.1f" fill="%s" font-size="11" font-weight="700" text-anchor="end">%.3f</text>' % (
        w - 4, max(12, last_y - 6), color, last_v if last_v is not None else 0)
    return ('<svg width="%d" height="%d" viewBox="0 0 %d %d">'
            '<defs><linearGradient id="g_%s" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0%%" stop-color="%s" stop-opacity="0.35"/>'
            '<stop offset="1%%" stop-color="%s" stop-opacity="0"/></linearGradient></defs>'
            '%s'
            '<polygon fill="url(#g_%s)" points="%s"/>'
            '<polyline fill="none" stroke="%s" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" points="%s"/>'
            '%s%s</svg>'
            ) % (w, h, w, h, color, color, color, grid, color, area, color, poly, dot, label)


def dashboard_html():
    return """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GEO 闭环看板</title><style>
:root{--bg:#0b0e14;--panel:#151a23;--panel2:#1c2330;--line:#2a3340;--txt:#e6edf3;--muted:#9fb0c3;--accent:#4f9dff;--accent2:#27a567;--pos:#3fb950;--neg:#f85149;--warn:#d29922}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:linear-gradient(180deg,#0b0e14 0%,#0d1119 100%);color:var(--txt);min-height:100vh}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:14px 28px;background:rgba(21,26,35,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.topbar .logo{font-size:18px;font-weight:700;background:linear-gradient(90deg,#4f9dff,#27a567);-webkit-background-clip:text;background-clip:text;color:transparent}
.topbar nav{display:flex;gap:4px}
.topbar nav a{color:var(--muted);text-decoration:none;padding:8px 14px;cursor:pointer;border-radius:8px;font-size:14px;transition:.15s}
.topbar nav a:hover{color:var(--txt);background:var(--panel2)}
.topbar nav a.active{color:#fff;background:linear-gradient(90deg,rgba(79,157,255,.25),rgba(39,165,103,.25));border:1px solid rgba(79,157,255,.4)}
.body{padding:0 28px 40px;max-width:1280px;margin:0 auto}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:22px 0 6px}
.kpi .kpi-card{background:linear-gradient(145deg,var(--panel2),var(--panel));padding:16px 18px;border-radius:12px;border:1px solid var(--line);box-shadow:0 2px 10px rgba(0,0,0,.25)}
.kpi .kpi-card .label{font-size:12px;color:var(--muted);margin-bottom:6px}
.kpi .kpi-card b{font-size:26px;font-weight:700;color:var(--accent)}
.card{background:var(--panel);padding:20px;border-radius:14px;margin:18px 0;border:1px solid var(--line);box-shadow:0 2px 14px rgba(0,0,0,.2)}
.section-title{font-size:16px;font-weight:600;color:var(--txt);margin:0 0 14px;display:flex;align-items:center;gap:8px}
.section-title::before{content:"";width:4px;height:16px;background:linear-gradient(180deg,var(--accent),var(--accent2));border-radius:2px;display:inline-block}
.row{display:flex;gap:20px;flex-wrap:wrap}
.row>.card{flex:1;min-width:340px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{border-bottom:1px solid var(--line);padding:9px 10px;text-align:left}
th{color:var(--muted);font-weight:600;background:var(--panel2);position:sticky;top:0}
tbody tr:hover{background:rgba(79,157,255,.06)}
a{color:var(--accent)}.pos{color:var(--pos)}.neg{color:var(--neg)}.muted{color:var(--muted)}
button{background:linear-gradient(90deg,var(--accent),#3b82f6);color:#fff;border:0;padding:9px 16px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;transition:.15s}
button:hover{filter:brightness(1.1);transform:translateY(-1px)}
button.ghost{background:var(--panel2);border:1px solid var(--line);color:var(--txt)}
button.green{background:linear-gradient(90deg,var(--accent2),#1f9d57)}
input,select,textarea{padding:9px 12px;border-radius:8px;border:1px solid var(--line);background:#0e1219;color:var(--txt);font-family:inherit;font-size:13px;outline:none;transition:.15s}
input:focus,select:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(79,157,255,.15)}
.pub-form{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
.pub-form label{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted)}
.pub-form textarea{width:100%;resize:vertical}
.alert{margin:14px 0;padding:12px 16px;border-radius:10px;font-size:13px}
.alert.danger{background:rgba(248,81,73,.12);color:#ffb3ae;border:1px solid rgba(248,81,73,.35)}
.alert.warn{background:rgba(210,153,34,.12);color:#ffd98a;border:1px solid rgba(210,153,34,.35)}
.insight-item{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:16px;margin:14px 0}
.insight-sum{font-size:15px;color:var(--txt);margin-bottom:10px;font-weight:600}
.ops{margin:8px 0 0;padding-left:20px}
.ops li{margin:10px 0;line-height:1.6}
.insight-time{color:#6b7785;font-size:12px;margin-top:10px}
.badge{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600}
.badge.ok{background:rgba(63,185,80,.18);color:var(--pos)}
.badge.fail{background:rgba(248,81,73,.18);color:var(--neg)}
.badge.off{background:rgba(159,176,195,.15);color:var(--muted)}
.tabbar{display:flex;gap:8px;margin:18px 0 4px}
.chart-wrap{background:#0e1219;border:1px solid var(--line);border-radius:10px;padding:14px;margin-top:8px}
#alertBar:empty{display:none}
.msg{margin-top:10px;color:var(--muted);font-size:13px}
/* ---- F19 美化增强 ---- */
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
section{animation:fadeIn .28s ease both}
@keyframes spin{to{transform:rotate(360deg)}}
.loading{display:inline-block;width:15px;height:15px;border:2px solid var(--line);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;vertical-align:-2px;margin-right:6px}
.empty{text-align:center;color:var(--muted);padding:26px 10px;font-size:13px;background:repeating-linear-gradient(45deg,transparent,transparent 10px,rgba(159,176,195,.04) 10px,rgba(159,176,195,.04) 20px);border-radius:10px;margin-top:8px}
.empty b{color:var(--txt);font-weight:600}
.card{transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.card:hover{border-color:rgba(79,157,255,.35);box-shadow:0 6px 22px rgba(0,0,0,.32)}
.kpi .kpi-card{position:relative;overflow:hidden}
.kpi .kpi-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:linear-gradient(180deg,var(--accent),var(--accent2))}
.kpi .kpi-card:hover{transform:translateY(-3px);box-shadow:0 8px 26px rgba(79,157,255,.18)}
.topbar nav{flex-wrap:wrap}
.tabbar a{padding:7px 14px}
.processing{opacity:.6;pointer-events:none}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:var(--line);border-radius:6px}
::-webkit-scrollbar-thumb:hover{background:#3a4656}
::-webkit-scrollbar-track{background:transparent}
@media(max-width:760px){.topbar{padding:12px 14px}.body{padding:0 14px 30px}.kpi .kpi-card b{font-size:22px}table{font-size:12px}}
</style></head><body>
<header class="topbar">
  <div class="logo">GEO 自用品 · 统一后台</div>
  <nav>
    <a href="javascript:void(0)" data-tab="dash" class="active" onclick="switchTab('dash')">闭环看板</a>
    <a href="javascript:void(0)" data-tab="scheduler" onclick="switchTab('scheduler')">定时发布</a>
    <a href="javascript:void(0)" data-tab="accounts" onclick="switchTab('accounts')">账号管理</a>
    <a href="javascript:void(0)" data-tab="publish" onclick="switchTab('publish')">一键发布</a>
    <a href="javascript:void(0)" data-tab="insight" onclick="switchTab('insight')">机会洞察</a>
    <a href="javascript:void(0)" data-tab="video" onclick="switchTab('video')">短视频脚本</a>
    <a href="javascript:void(0)" data-tab="monitor" onclick="switchTab('monitor')">监测管理</a>
    <a href="javascript:void(0)" data-tab="review" onclick="switchTab('review')">自动复盘</a>
    <a href="javascript:void(0)" data-tab="alert" onclick="switchTab('alert')">告警中心</a>
  </nav>
</header>

<div class="body">
<div class="kpi" id="kpi"></div>
<div id="alertBar"></div>

<!-- 闭环看板 -->
<section id="tab-dash">
<div class="card">
  <div class="section-title">闭环归因(F17):发布→可见性变化
    <span style="float:right">
      <button style="background:#27a567" onclick="exportReport('csv')">导出报表 CSV</button>
      <button style="background:#2f6fed;margin-left:6px" onclick="exportReport('json')">导出 JSON</button>
    </span>
  </div>
  <div id="loopControls">
    <input id="pid" placeholder="监控端项目ID" size="10">
    <input id="brand" placeholder="品牌名" size="14">
    <input id="q" placeholder="检测问题" size="30" value="请介绍该领域的代表品牌">
    <button onclick="runLoop()">触发一次闭环</button>
  </div>
  <div id="loopMsg" style="margin-top:8px;color:#9fb3c8"></div>
  <div id="loopChart"></div>
  <table id="loop"><tr><th>时间</th><th>品牌</th><th>发布前</th><th>发布后</th><th>提及率Δ</th><th>可见性Δ</th><th>触发</th></tr></table>
</div>

<div class="card">
  <div class="section-title">AI 可见性趋势(监控端)</div>
  <div id="trendChart"></div>
  <pre id="trendSummary" style="font-size:12px;color:#9fb3c8"></pre>
</div>

<div class="row">
  <div class="card" style="flex:1"><div class="section-title">生成内容</div>
    <table id="gen"><tr><th>平台</th><th>标题</th><th>状态</th></tr></table></div>
  <div class="card" style="flex:1"><div class="section-title">发布记录</div>
    <table id="pub"><tr><th>平台</th><th>账号</th><th>状态</th><th>错误</th></tr></table></div>
</div>
</section>

<!-- 账号管理 -->
<section id="tab-accounts" style="display:none">
<div class="card">
  <div class="section-title">平台账号与登录状态</div>
  <div id="accMsg" style="margin-bottom:8px;color:#9fb3c8"></div>
  <table id="acc"><tr><th>平台</th><th>账号</th><th>状态</th><th>Cookie 文件</th><th>操作</th></tr></table>
</div>
<div class="card">
  <div class="section-title">添加平台账号(触发浏览器登录,自动录入 Cookie)</div>
  <div class="pub-form">
    <label>平台
      <select id="naPlatform">
        <option value="1">小红书</option>
        <option value="2">视频号</option>
        <option value="3">抖音</option>
        <option value="4">快手</option>
        <option value="8">B站</option>
        <option value="9">百家号</option>
      </select>
    </label>
    <label>账号名(自定义,用于标识)
      <input id="naAccount" placeholder="如 my_bilibili" size="16" value="my_bilibili">
    </label>
    <button onclick="addAccount()">触发登录弹窗</button>
  </div>
  <div id="naMsg" style="margin-top:8px;color:#9fb3c8"></div>
</div>
</section>

<!-- 一键发布 -->
<section id="tab-publish" style="display:none">
<div class="card">
  <div class="section-title">一键真实发布(图文)</div>
  <div class="pub-form">
    <label>平台
      <select id="pPlatform"></select>
    </label>
    <label>标题
      <input id="pTitle" placeholder="文章标题" size="40">
    </label>
    <label>标签(逗号分隔)
      <input id="pTags" placeholder="GEO,AI,大模型" size="20">
    </label>
    <label style="flex:1 1 100%">正文
      <textarea id="pText" rows="6" placeholder="正文内容..."></textarea>
    </label>
    <button onclick="doPublish()">立即发布</button>
  </div>
  <div id="pubMsg" style="margin-top:8px;color:#9fb3c8"></div>
</div>
</section>

<!-- 机会洞察 -->
<section id="tab-insight" style="display:none">
<div class="card">
  <div class="section-title">GEO 机会洞察(F15)
    <button style="float:right;background:#27a567" onclick="genInsight()">生成洞察报告</button>
  </div>
  <div id="insightMsg" style="margin-bottom:8px;color:#9fb3c8"></div>
  <div id="insightList"></div>
</div>
</section>

<!-- 短视频脚本 -->
<section id="tab-video" style="display:none">
<div class="card">
  <div class="section-title">短视频脚本生成(F14)</div>
  <div class="pub-form">
    <label>平台
      <select id="vPlatform">
        <option value="douyin">抖音</option>
        <option value="shipinhao">视频号</option>
        <option value="kuaishou">快手</option>
        <option value="bilibili">B站</option>
      </select>
    </label>
    <label>品牌
      <input id="vBrand" placeholder="品牌名" size="16" value="GeoPilot">
    </label>
    <label>话题
      <input id="vTopic" placeholder="脚本话题" size="24" value="3分钟看懂生成式引擎优化">
    </label>
    <label>时长(秒)
      <input id="vDur" type="number" value="60" min="15" max="180" style="width:80px">
    </label>
    <button onclick="genVideo()">生成脚本</button>
  </div>
  <div id="videoMsg" style="margin-top:8px;color:#9fb3c8"></div>
  <pre id="videoOut" style="white-space:pre-wrap;background:#111;padding:12px;border-radius:6px;margin-top:8px;display:none"></pre>
</div>
</section>

<!-- 定时发布 F18 -->
<section id="tab-scheduler" style="display:none">
<div class="card">
  <div class="section-title">定时自动发布(F18)
    <button style="float:right" class="green" onclick="loadScheduler()">刷新列表</button>
  </div>
  <div class="muted" style="font-size:12px;margin-bottom:10px">后台调度线程按 cron 时间自动真实发布到小红书(视频平台不支持)。</div>
  <div class="pub-form">
    <label>品牌
      <input id="sBrand" placeholder="品牌名" size="16" value="量子科技">
    </label>
    <label>话题
      <input id="sTopic" placeholder="发布话题" size="26" value="AI 芯片最新进展">
    </label>
    <label>触发小时(0-23)
      <input id="sHour" type="number" value="9" min="0" max="23" style="width:80px">
    </label>
    <label>触发分钟(0-59)
      <input id="sMin" type="number" value="0" min="0" max="59" style="width:80px">
    </label>
    <button onclick="createTask()">创建定时任务</button>
  </div>
  <div id="sMsg" class="msg"></div>
  <table id="sList" style="margin-top:14px"><tr><th>ID</th><th>品牌</th><th>话题</th><th>平台</th><th>cron</th><th>状态</th><th>下次运行</th><th>操作</th></tr></table>
</div>
</section>

<!-- 监测管理 F3 -->
<section id="tab-monitor" style="display:none">
<div class="card">
  <div class="section-title">多项目监测管理(F3)
    <button style="float:right;background:#27a567" onclick="runAllMonitor()">批量触发检测</button>
    <button style="float:right;margin-right:8px" onclick="createMonitor()">批量创建项目</button>
  </div>
  <div id="monitorMsg" style="margin-bottom:8px;color:#9fb3c8"></div>
  <label style="font-size:12px;color:#9fb3c8">批量创建(每行一个项目,格式: 品牌名|关键词1,关键词2):</label>
  <textarea id="mProjects" rows="4" style="width:100%;margin-top:6px" placeholder="GeoPilot|GEO,生成式引擎优化,AI搜索
竞品A|量子计算,云服务"></textarea>
  <table id="mList"><tr><th>项目名</th><th>品牌</th><th>关键词</th><th>引擎</th><th>状态</th><th>最近运行</th></tr></table>
</div>
</section>

<section id="tab-review" style="display:none">
  <h2>闭环自动复盘 (F20)</h2>
  <p style="color:#5b6b7b">发布→检测可见性→低提及率话题自动换角度重生成→(可选)再次发布，形成"发布-检测-优化"自循环。</p>
  <div class="kpi-grid" style="margin:12px 0">
    <div class="kpi"><div class="kpi-val" id="rCount">0</div><div class="kpi-lbl">复盘任务</div></div>
    <div class="kpi"><div class="kpi-val" id="rLoop">关</div><div class="kpi-lbl">自动循环</div></div>
    <div class="kpi"><div class="kpi-val" id="rTrig">0</div><div class="kpi-lbl">已触发复盘</div></div>
  </div>
  <div class="card" style="padding:14px;margin-bottom:14px">
    <h3>新建复盘任务</h3>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
      <input id="rBrand" placeholder="品牌(如 GeoPilot)" style="padding:8px;border-radius:8px;border:1px solid #d3dce6">
      <input id="rTopic" placeholder="话题(如 GEO 是什么)" style="padding:8px;border-radius:8px;border:1px solid #d3dce6;flex:1">
      <input id="rMin" placeholder="触发阈值(默认0.15)" style="padding:8px;border-radius:8px;border:1px solid #d3dce6;width:150px">
      <input id="rAngle" placeholder="初始角度(默认通用科普)" style="padding:8px;border-radius:8px;border:1px solid #d3dce6;width:170px">
      <label style="align-self:center"><input type="checkbox" id="rLoop"> 开启自动循环</label>
      <button class="btn" onclick="createReviewTask()">创建</button>
    </div>
  </div>
  <table id="rList">
    <tr><th>ID</th><th>品牌</th><th>话题</th><th>当前角度</th><th>阈值</th><th>状态</th><th>最近提及率</th><th>运行次数</th><th>自动循环</th><th>操作</th></tr>
  </table>
</section>

<section id="tab-alert" style="display:none">
  <h2>告警中心 (F12)</h2>
  <p style="color:#5b6b7b">可见性低于阈值自动落库告警，可推送到外部渠道(企业微信/飞书/Slack Webhook)，并标记已解决形成闭环。</p>
  <div class="kpi-grid" style="margin:12px 0">
    <div class="kpi"><div class="kpi-val" id="aTotal">0</div><div class="kpi-lbl">未解决告警</div></div>
    <div class="kpi"><div class="kpi-val" id="aPending">0</div><div class="kpi-lbl">待推送</div></div>
    <div class="kpi"><div class="kpi-val" id="aWeb">关</div><div class="kpi-lbl">Webhook</div></div>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:10px">
    <button class="btn" onclick="pushAllAlerts()">推送全部待发</button>
    <span id="aMsg" class="msg"></span>
  </div>
  <table id="aList">
    <tr><th>ID</th><th>级别</th><th>范围</th><th>消息</th><th>指标</th><th>推送</th><th>状态</th><th>时间</th><th>操作</th></tr>
  </table>
</section>

<script>
function loadingHTML(txt){return `<div class="loading"></div>${txt||'加载中...'}`;}
function emptyHTML(title,hint){return `<div class="empty"><b>${title||'暂无数据'}</b>${hint?'<br>'+hint:''}</div>`;}
function switchTab(name){
  document.querySelectorAll('.topbar nav a').forEach(a=>a.classList.remove('active'));
  document.querySelector(`.topbar nav a[data-tab="${name}"]`).classList.add('active');
  ['dash','scheduler','accounts','publish','insight','video','monitor','review','alert'].forEach(t=>{
    const el=document.getElementById('tab-'+t); if(el) el.style.display = (t===name)?'block':'none';
  });
  if(name==='accounts') loadAccounts();
  if(name==='publish') loadPlatforms();
  if(name==='insight') loadInsights();
  if(name==='monitor') loadMonitor();
  if(name==='scheduler') loadScheduler();
  if(name==='review') loadReview();
  if(name==='alert') loadAlerts();
}
async function load(){
  const ov=await (await fetch('/api/overview')).json();
  const snap=ov.latest_snapshot||{};
  renderAlerts(ov.alerts||[], ov.new_alerts||[]);
  document.getElementById('kpi').innerHTML=
    `<div class="kpi-card"><div class="label">生成内容</div><b>${ov.generated}</b></div>`+
    `<div class="kpi-card"><div class="label">发布成功</div><b>${ov.published}</b></div>`+
    `<div class="kpi-card"><div class="label">发布失败</div><b style="color:${ov.failed>0?'var(--neg)':'var(--accent)'}">${ov.failed}</b></div>`+
    `<div class="kpi-card"><div class="label">监测项目</div><b>${ov.monitor_projects}</b></div>`+
    `<div class="kpi-card"><div class="label">最近提及率</div><b>${snap.after_mention_rate!=null?snap.after_mention_rate.toFixed(3):'--'}</b></div>`;
  const g=await (await fetch('/api/generated')).json();
  document.getElementById('gen').innerHTML='<tr><th>平台</th><th>标题</th><th>状态</th></tr>'+
    (g.length?g.map(r=>`<tr><td>${r.platform}</td><td>${r.title||''}</td><td>${r.status}</td></tr>`).join(''):'<tr><td colspan="3">'+emptyHTML('暂无生成内容','在"一键发布"或定时发布中生成')+'</td></tr>');
  const p=await (await fetch('/api/published')).json();
  document.getElementById('pub').innerHTML='<tr><th>平台</th><th>账号</th><th>状态</th><th>错误</th></tr>'+
    (p.length?p.map(r=>`<tr><td>${r.platform}</td><td>${r.account||''}</td><td>${r.status}</td><td>${r.error||''}</td></tr>`).join(''):'<tr><td colspan="4">'+emptyHTML('暂无发布记录','真实发布后在此显示')+'</td></tr>');
  const lp=await (await fetch('/api/loop')).json();
  document.getElementById('loop').innerHTML='<tr><th>时间</th><th>品牌</th><th>发布前</th><th>发布后</th><th>提及率Δ</th><th>可见性Δ</th><th>触发</th></tr>'+
    (lp.length?lp.map(r=>{const d=r.mention_rate_delta;const cls=d>0?'pos':(d<0?'neg':'');
      return `<tr><td>${r.captured_at}</td><td>${r.brand}</td><td>${r.before_mention_rate!=null?r.before_mention_rate.toFixed(3):'--'}</td>`+
      `<td>${r.after_mention_rate!=null?r.after_mention_rate.toFixed(3):'--'}</td>`+
      `<td class="${cls}">${d!=null?(d>=0?'+':'')+d.toFixed(3):'--'}</td>`+
      `<td class="${cls}">${r.visibility_score_delta!=null?(r.visibility_score_delta>=0?'+':'')+r.visibility_score_delta.toFixed(2):'--'}</td>`+
      `<td>${r.trigger}</td></tr>`}).join(''):'<tr><td colspan="7">'+emptyHTML('暂无闭环记录','发布并检测可见性后生成闭环数据')+'</td></tr>');
}
function renderAlerts(alerts, newAlerts){
  const bar=document.getElementById('alertBar');
  const items=[...(newAlerts||[]).map(m=>({msg:m,cls:'danger'}))];
  (alerts||[]).forEach(a=>items.push({msg:a.message,cls:'warn'}));
  if(!items.length){bar.innerHTML='';return;}
  bar.innerHTML=items.map(it=>`<div class="alert ${it.cls}">⚠ ${it.msg}</div>`).join('');
}
function exportReport(fmt){
  window.location.href='/api/export?type='+(fmt||'csv');
}
async function loadInsights(){
  try{
    const d=await (await fetch('/api/insights')).json();
    const list=(d.insights||[]).map(it=>{
      let ops=[];
      try{ops=JSON.parse(it.opportunities||'[]');}catch(e){}
      const opHtml=ops.map(o=>`<li><b>${o.topic||''}</b> · <span class="pos">${o.platform||''}</span><br><span style="color:#cbd5e1">动作:</span>${o.action||''}<br><span style="color:#9fb3c8">依据:${o.reason||''}</span></li>`).join('');
      return `<div class="insight-item"><div class="insight-sum">${it.summary||''}</div><ul class="ops">${opHtml||'<li>暂无机会项</li>'}</ul><div class="insight-time">${it.created_at||''}</div></div>`;
    }).join('');
    document.getElementById('insightList').innerHTML=list||'<div class="empty">尚无洞察报告<br>点击右上角"生成洞察报告"基于真实数据生成</div>';
  }catch(e){document.getElementById('insightList').textContent='加载失败:'+e;}
}
async function genInsight(){
  document.getElementById('insightMsg').textContent='正在基于真实数据生成洞察(调用 LLM),请稍候...';
  try{
    const r=await (await fetch('/api/insights/generate',{method:'POST'})).json();
    document.getElementById('insightMsg').textContent=(r.ok?'✅ ':'❌ ')+(r.msg||'');
    if(r.ok) loadInsights();
  }catch(e){document.getElementById('insightMsg').textContent='生成异常:'+e;}
}
async function genVideo(){
  const platform=document.getElementById('vPlatform').value;
  const brand=document.getElementById('vBrand').value.trim();
  const topic=document.getElementById('vTopic').value.trim();
  const duration=parseInt(document.getElementById('vDur').value)||60;
  if(!brand||!topic){document.getElementById('videoMsg').textContent='品牌与话题不能为空';return;}
  document.getElementById('videoMsg').textContent='正在生成短视频脚本(调用 LLM)...';
  document.getElementById('videoOut').style.display='none';
  try{
    const r=await (await fetch('/api/generate/video',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform,brand,topic,duration})})).json();
    document.getElementById('videoMsg').textContent=(r.ok?'✅ ':'❌ ')+(r.msg||'');
    if(r.ok){document.getElementById('videoOut').style.display='block';document.getElementById('videoOut').textContent=r.result.body;}
  }catch(e){document.getElementById('videoMsg').textContent='生成异常:'+e;}
}
async function loadMonitor(){
  try{
    document.getElementById('mList').innerHTML='<tr><th>项目名</th><th>品牌</th><th>关键词</th><th>引擎</th><th>状态</th><th>最近运行</th></tr><tr><td colspan=6>'+loadingHTML('加载监测项目...')+'</td></tr>';
    const d=await (await fetch('/api/monitor/projects')).json();
    const rows=(d.projects||[]).map(p=>`<tr><td>${p.name}</td><td>${p.brand}</td><td>${p.keywords||''}</td><td>${p.platforms||''}</td><td>${p.last_status||'-'}</td><td>${p.last_run_at||'-'}</td></tr>`).join('');
    document.getElementById('mList').innerHTML='<tr><th>项目名</th><th>品牌</th><th>关键词</th><th>引擎</th><th>状态</th><th>最近运行</th></tr>'+(rows||'<tr><td colspan=6>'+emptyHTML('暂无监测项目','在上方批量创建,格式:品牌|关键词')+'</td></tr>');
  }catch(e){document.getElementById('monitorMsg').textContent='加载失败:'+e;}
}
async function createMonitor(){
  const txt=document.getElementById('mProjects').value.trim();
  if(!txt){document.getElementById('monitorMsg').textContent='请输入项目(品牌|关键词)';return;}
  const projects=txt.split(String.fromCharCode(10)).map(l=>l.trim()).filter(Boolean).map(l=>{
    const [brand,kws]=l.split('|');
    return {name:brand.trim(),brand:brand.trim(),keywords:(kws||'').split(',').map(s=>s.trim()).filter(Boolean)};
  });
  document.getElementById('monitorMsg').textContent='正在批量创建监测项目...';
  try{
    const r=await (await fetch('/api/monitor/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({projects})})).json();
    document.getElementById('monitorMsg').textContent=(r.ok?'✅ ':'❌ ')+(r.msg||'')+(r.errors&&r.errors.length?(' 失败:'+JSON.stringify(r.errors)):'');
    loadMonitor();
  }catch(e){document.getElementById('monitorMsg').textContent='创建异常:'+e;}
}
async function loadScheduler(){
  try{
    document.getElementById('sList').innerHTML='<tr><th>ID</th><th>品牌</th><th>话题</th><th>平台</th><th>cron</th><th>状态</th><th>下次运行</th><th>操作</th></tr><tr><td colspan=8>'+loadingHTML('加载定时任务...')+'</td></tr>';
    const d=await (await fetch('/api/scheduler/tasks')).json();
    const rows=(d.tasks||[]).map(t=>{
      const st=t.last_status||'-';
      const badge=st.startsWith('success')?'<span class="badge ok">成功</span>':(st.startsWith('fail')||st.startsWith('error')?`<span class="badge fail">${st.slice(0,12)}</span>`:'<span class="badge off">待运行</span>');
      return `<tr><td>${t.id}</td><td>${t.brand}</td><td>${t.topic}</td><td>${t.platform}</td>`+
        `<td>${String(t.cron_hour).padStart(2,'0')}:${String(t.cron_minute).padStart(2,'0')}</td>`+
        `<td>${badge}</td><td>${t.next_run_at||'-'}</td>`+
        `<td><button class="ghost" onclick="runNowTask(${t.id})">立即触发</button> <button class="ghost" onclick="deleteTask(${t.id})">删除</button></td></tr>`;
    }).join('');
    document.getElementById('sList').innerHTML='<tr><th>ID</th><th>品牌</th><th>话题</th><th>平台</th><th>cron</th><th>状态</th><th>下次运行</th><th>操作</th></tr>'+(rows||'<tr><td colspan=8>'+emptyHTML('暂无定时任务','在上方设置品牌/话题/时间,开启定时自动发布')+'</td></tr>');
  }catch(e){document.getElementById('sMsg').textContent='加载失败:'+e;}
}
async function createTask(){
  const brand=document.getElementById('sBrand').value.trim();
  const topic=document.getElementById('sTopic').value.trim();
  const cron_hour=parseInt(document.getElementById('sHour').value)||0;
  const cron_minute=parseInt(document.getElementById('sMin').value)||0;
  if(!brand||!topic){document.getElementById('sMsg').textContent='品牌与话题必填';return;}
  document.getElementById('sMsg').textContent='正在创建定时任务...';
  try{
    const r=await (await fetch('/api/scheduler/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({brand,topic,platform:'xiaohongshu',cron_hour,cron_minute})})).json();
    document.getElementById('sMsg').textContent=(r.ok?'✅ ':'❌ ')+(r.msg||'');
    if(r.ok) loadScheduler();
  }catch(e){document.getElementById('sMsg').textContent='创建异常:'+e;}
}
async function runNowTask(id){
  document.getElementById('sMsg').textContent='正在立即触发真实发布...';
  try{
    const r=await (await fetch('/api/scheduler/run-now',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:id})})).json();
    document.getElementById('sMsg').textContent=(r.ok?'✅ ':'❌ ')+(r.task_id?('task#'+r.task_id):(r.msg||''));
    loadScheduler();
  }catch(e){document.getElementById('sMsg').textContent='触发异常:'+e;}
}
async function deleteTask(id){
  try{
    const r=await (await fetch('/api/scheduler/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:id})})).json();
    document.getElementById('sMsg').textContent=(r.ok?'✅ ':'❌ ')+(r.msg||'');
    loadScheduler();
  }catch(e){document.getElementById('sMsg').textContent='删除异常:'+e;}
}
async function runAllMonitor(){
  document.getElementById('monitorMsg').textContent='正在批量触发检测(可能耗时较长)...';
  try{
    const r=await (await fetch('/api/monitor/run-all',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).json();
    document.getElementById('monitorMsg').textContent=(r.ok?'✅ ':'❌ ')+(r.msg||'');
    loadMonitor();
  }catch(e){document.getElementById('monitorMsg').textContent='批量检测异常:'+e;}
}
// ---------- F20 闭环自动复盘 ----------
async function loadReview(){
  try{
    const d=await (await fetch('/api/review/tasks')).json();
    const tasks=d.tasks||[];
    document.getElementById('rCount').textContent=tasks.length;
    const loopOn=tasks.some(t=>t.auto_loop&&t.enabled);
    document.getElementById('rLoop').textContent=loopOn?'开':'关';
    document.getElementById('rTrig').textContent=tasks.filter(t=>t.last_status&&t.last_status!=='pending').length;
    const rows=tasks.map(t=>{
      const st=t.last_status||'pending';
      const badge=st==='ok'||st==='published'?'<span class="badge ok">'+st+'</span>':
        (st.startsWith('fail')||st==='gen_failed'||st==='publish_failed'?'<span class="badge fail">'+st.slice(0,14)+'</span>':'<span class="badge off">待运行</span>');
      const rate=t.last_rate!=null?Number(t.last_rate).toFixed(3):'-';
      const loop=t.enabled&&t.auto_loop?'<span class="pos">开</span>':'<span class="neg">关</span>';
      return `<tr><td>${t.id}</td><td>${t.brand}</td><td>${t.topic}</td><td>${t.angle||'通用科普'}</td>`+
        `<td>${t.min_mention_rate}</td><td>${badge}</td><td>${rate}</td><td>${t.run_count||0}</td>`+
        `<td>${loop}</td>`+
        `<td><button class="ghost" onclick="runReviewNow(${t.id},0)">复盘(不发布)</button> `+
        `<button class="ghost" onclick="runReviewNow(${t.id},1)">复盘+发布</button> `+
        `<button class="ghost" onclick="toggleReviewLoop(${t.id})">${t.auto_loop?'停循环':'开循环'}</button> `+
        `<button class="ghost" onclick="deleteReviewTask(${t.id})">删除</button></td></tr>`;
    }).join('');
    document.getElementById('rList').innerHTML='<tr><th>ID</th><th>品牌</th><th>话题</th><th>当前角度</th><th>阈值</th><th>状态</th><th>最近提及率</th><th>运行次数</th><th>自动循环</th><th>操作</th></tr>'+
      (rows||'<tr><td colspan=10>'+emptyHTML('暂无复盘任务','在上方创建,低提及率话题将自动换角度重生成')+'</td></tr>');
  }catch(e){document.getElementById('rList').innerHTML='<tr><td colspan=10 class="muted">加载失败:'+e+'</td></tr>';}
}
async function createReviewTask(){
  const brand=document.getElementById('rBrand').value.trim();
  const topic=document.getElementById('rTopic').value.trim();
  const min=parseFloat(document.getElementById('rMin').value)||0.15;
  const angle=document.getElementById('rAngle').value.trim()||'通用科普';
  const auto_loop=document.getElementById('rLoop').checked?1:0;
  if(!brand||!topic){alert('品牌与话题必填');return;}
  try{
    const r=await (await fetch('/api/review/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({brand,topic,platform:'xiaohongshu',min_mention_rate:min,angle,auto_loop})})).json();
    if(r.ok){document.getElementById('rBrand').value='';document.getElementById('rTopic').value='';loadReview();}else{alert('创建失败:'+(r.msg||''));}
  }catch(e){alert('创建异常:'+e);}
}
async function runReviewNow(id,publish){
  try{
    const r=await (await fetch('/api/review/run-now',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:id,publish:publish})})).json();
    const res=r.result||{};
    let msg='任务'+id+': '+(res.triggered?(res.new_angle?'已换角度【'+res.new_angle+'】重生成,':'未触发复盘,'):'')+(res.status||'');
    if(publish) msg+=' 发布:'+(res.published?'成功':'未成功');
    alert((r.ok?'✅ ':'❌ ')+msg);
    loadReview();
  }catch(e){alert('复盘异常:'+e);}
}
async function toggleReviewLoop(id){
  try{
    const cur=await (await fetch('/api/review/tasks')).json();
    const t=(cur.tasks||[]).find(x=>x.id===id);
    const auto_loop=t&&t.auto_loop?0:1;
    const r=await (await fetch('/api/review/auto-toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:id,auto_loop})})).json();
    loadReview();
  }catch(e){alert('切换异常:'+e);}
}
async function deleteReviewTask(id){
  try{
    const r=await (await fetch('/api/review/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:id})})).json();
    if(r.ok) loadReview();
  }catch(e){alert('删除异常:'+e);}
}
// ---------- F12 告警中心 ----------
async function loadAlerts(){
  try{
    document.getElementById('aList').innerHTML='<tr><th>ID</th><th>级别</th><th>范围</th><th>消息</th><th>指标</th><th>推送</th><th>状态</th><th>时间</th><th>操作</th></tr><tr><td colspan=9>'+loadingHTML('加载告警...')+'</td></tr>';
    const d=await (await fetch('/api/alerts')).json();
    const alerts=d.alerts||[];
    document.getElementById('aTotal').textContent=alerts.length;
    document.getElementById('aPending').textContent=d.pending||0;
    document.getElementById('aWeb').textContent=d.webhook_enabled?'开':'关';
    const rows=alerts.map(a=>{
      const pushed=a.pushed==1?'<span class="badge ok">已推送</span>':(a.pushed==-1?'<span class="badge fail">推送失败</span>':'<span class="badge off">待推送</span>');
      const st=a.resolved?'<span class="badge ok">已解决</span>':'<span class="badge off">未解决</span>';
      const metric=a.metric?(a.metric+':'+(a.value!=null?a.value:'-')+'/'+(a.threshold!=null?a.threshold:'-')):'-';
      return `<tr><td>${a.id}</td><td>${a.level}</td><td>${a.scope||'-'}</td><td>${a.message}</td><td>${metric}</td>`+
        `<td>${pushed}</td><td>${st}</td><td>${a.created_at||'-'}</td>`+
        `<td><button class="ghost" onclick="pushOneAlert(${a.id})">推送</button> `+
        `<button class="ghost" onclick="resolveAlert(${a.id})">标记解决</button></td></tr>`;
    }).join('');
    document.getElementById('aList').innerHTML='<tr><th>ID</th><th>级别</th><th>范围</th><th>消息</th><th>指标</th><th>推送</th><th>状态</th><th>时间</th><th>操作</th></tr>'+
      (rows||'<tr><td colspan=9>'+emptyHTML('暂无告警','可见性低于阈值时自动生成')+'</td></tr>');
  }catch(e){document.getElementById('aList').innerHTML='<tr><td colspan=9>'+emptyHTML('加载失败:'+e)+'</td></tr>';}
}
async function pushAllAlerts(){
  try{
    const r=await (await fetch('/api/alerts/push',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(x=>x.json()));
    document.getElementById('aMsg').textContent='已推送 '+r.pushed+' 条,跳过 '+r.skipped+' 条'+(r.failed?',失败 '+r.failed+' 条':'');
    loadAlerts();
  }catch(e){document.getElementById('aMsg').textContent='推送异常:'+e;}
}
async function pushOneAlert(id){
  try{
    const r=await (await fetch('/api/alerts/push',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({alert_id:id})})).json();
    alert((r.ok?'✅ ':'❌ ')+r.msg);
    loadAlerts();
  }catch(e){alert('推送异常:'+e);}
}
async function resolveAlert(id){
  try{
    const r=await (await fetch('/api/alerts/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({alert_id:id})})).json();
    if(r.ok) loadAlerts();
  }catch(e){alert('解决异常:'+e);}
}
async function loadAccounts(){
  try{
    const d=await (await fetch('/api/accounts')).json();
    if(d.error){document.getElementById('accMsg').textContent=d.error;return;}
    const rows=(d.accounts||[]).map(a=>{
      const st=a.logged_in?'<span class="pos">已登录</span>':'<span class="neg">未登录</span>';
      const btn=`<button onclick="triggerLogin(${a.type},'${a.account}')">重新登录</button>`;
      return `<tr><td>${a.platform_name}(${a.platform_key})</td><td>${a.account}</td><td>${st}</td><td>${a.cookiesFile||'-'}</td><td>${btn}</td></tr>`;
    }).join('');
    document.getElementById('acc').innerHTML='<tr><th>平台</th><th>账号</th><th>状态</th><th>Cookie 文件</th><th>操作</th></tr>'+(rows||'<tr><td colspan=5>'+emptyHTML('暂无账号','在发布端(5409)登录后此处自动显示')+'</td></tr>');
  }catch(e){document.getElementById('accMsg').textContent='加载失败:'+e;}
}
async function triggerLogin(type,account){
  document.getElementById('accMsg').textContent='正在触发登录...';
  try{
    const r=await (await fetch('/api/accounts/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:type,account:account})})).json();
    document.getElementById('accMsg').textContent=r.msg||(r.ok?'已触发':'失败');
  }catch(e){document.getElementById('accMsg').textContent='触发失败:'+e;}
}
async function addAccount(){
  const type=document.getElementById('naPlatform').value;
  const account=document.getElementById('naAccount').value.trim();
  if(!account){document.getElementById('naMsg').textContent='请填写账号名';return;}
  document.getElementById('naMsg').textContent='正在触发登录弹窗,请在浏览器中完成登录...';
  try{
    const r=await (await fetch('/api/accounts/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:parseInt(type),account:account})})).json();
    document.getElementById('naMsg').textContent=(r.ok?'✅ ':'❌ ')+(r.msg||'');
    if(r.ok) setTimeout(loadAccounts,8000); // 登录后延迟刷新列表
  }catch(e){document.getElementById('naMsg').textContent='触发失败:'+e;}
}
async function loadPlatforms(){
  try{
    const d=await (await fetch('/api/accounts')).json();
    const sel=document.getElementById('pPlatform');
    const accs=(d.accounts||[]).filter(a=>a.logged_in);
    if(!accs.length){
      sel.innerHTML='<option value="">（无已登录账号，请先到"账号管理"登录）</option>';
      return;
    }
    sel.innerHTML=accs.map(a=>`<option value="${a.platform_key}">${a.platform_name}(${a.account})</option>`).join('');
  }catch(e){}
}
async function doPublish(){
  const platform=document.getElementById('pPlatform').value;
  const title=document.getElementById('pTitle').value.trim();
  const text=document.getElementById('pText').value.trim();
  const tags=document.getElementById('pTags').value.trim();
  if(!platform){document.getElementById('pubMsg').textContent='没有可用平台(请先登录账号)';return;}
  if(!title||!text){document.getElementById('pubMsg').textContent='标题与正文不能为空';return;}
  document.getElementById('pubMsg').textContent='正在发布...';
  try{
    const r=await (await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform,title,text,tags})})).json();
    document.getElementById('pubMsg').textContent=(r.ok?'✅ ':'❌ ')+(r.msg||'');
    if(r.ok) load();
  }catch(e){document.getElementById('pubMsg').textContent='发布异常:'+e;}
}
async function loadTrend(pid){
  if(!pid) return;
  try{
    const d=await (await fetch('/api/monitor/'+pid)).json();
    const trend=(d.trend||[]).map(t=>({date:t.date,rate:t.brand_mention_rate}));
    const vals=trend.map(t=>[t.date,t.rate]);
    document.getElementById('trendChart').innerHTML='<div class="muted" style="font-size:12px;margin-bottom:6px">提及率趋势(按日)</div>'+spark(vals);
    document.getElementById('trendSummary').textContent=JSON.stringify(d.summary||{},null,2);
  }catch(e){document.getElementById('trendSummary').textContent='趋势加载失败:'+e;}
}
function spark(vals){
  if(!vals.length) return '<svg width=320 height=70></svg>';
  const w=320,h=70,step=w/Math.max(vals.length-1,1),pts=vals.map((v,i)=>[i*step,h-((v[1]||0)*(h-12))-6]);
  const poly=pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ');
  const area=`0,${h} `+poly+` ${w},${h}`;
  return `<svg width=${w} height=${h} viewBox="0 0 ${w} ${h}" style="width:100%;max-width:480px">
    <defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#4f9dff" stop-opacity=".35"/><stop offset="100%" stop-color="#4f9dff" stop-opacity="0"/>
    </linearGradient></defs>
    <polygon fill="url(#sg)" points="${area}"/>
    <polyline fill="none" stroke="#4f9dff" stroke-width="2" points="${poly}"/>
    ${pts.map(p=>`<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2.5" fill="#7cc4ff"/>`).join('')}
  </svg>`;
}
async function runLoop(){
  const pid=document.getElementById('pid').value;
  const brand=document.getElementById('brand').value;
  const q=document.getElementById('q').value;
  if(!pid||!brand){document.getElementById('loopMsg').textContent='请填写项目ID与品牌名';return;}
  document.getElementById('loopMsg').textContent='正在执行闭环(基线→检测→对比),请稍候...';
  try{
    const r=await (await fetch(`/api/loop/run?pid=${pid}&brand=${encodeURIComponent(brand)}&q=${encodeURIComponent(q)}`)).json();
    document.getElementById('loopMsg').textContent='闭环完成: 检测'+(r.detection_done?'已完成':'未完成')+' 提及率Δ='+(r.mention_rate_delta!=null?r.mention_rate_delta.toFixed(3):'--');
    loadTrend(pid);load();
  }catch(e){document.getElementById('loopMsg').textContent='闭环失败:'+e;}
}
(async()=>{
  try{
    const projs=await (await fetch('/api/projects')).json();
    if(Array.isArray(projs) && projs.length){
      const pid=projs[0].id;
      document.getElementById('pid').value=pid;
      document.getElementById('brand').value=projs[0].name||'';
      loadTrend(pid);
    }
  }catch(e){}
  load();
})();
</script>
</div>
</body></html>"""


if __name__ == "__main__":
    start_scheduler()  # 拉起定时自动发布后台线程
    _review_loop = ReviewLoop()
    _review_loop.start()  # 拉起闭环自动复盘后台线程(F20)
    # 多线程服务: 避免发布端同步阻塞/自检自调用(整合层健康检查指向自身)时单线程死锁卡死看板
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler) as httpd:
        print(f"闭环看板 on http://localhost:{PORT}")
        httpd.serve_forever()
