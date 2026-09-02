# 定时自动发布调度器(常驻)
# 职责: 每分钟轮询 publish_tasks, 命中 cron 时间窗口的任务触发真实发布(小红书),
#       并更新 last_run_at/last_status/run_count。随 dashboard_api 启动拉起后台线程。
# 边界: 仅支持 xiaohongshu(已验证真实发布平台); 视频类平台一律不做。
import threading
import time
import datetime
import traceback

from db import (
    list_publish_tasks, update_publish_task_run, compute_next_run_at,
)
from pipeline import run as pipeline_run
from proc_utils import pre_publish_cleanup  # 发布前清理残留 Chromium, 避免超时

POLL_INTERVAL = 30  # 秒
# 已发布过的时间戳缓存(避免同一分钟重复触发), key=task_id, value="YYYY-MM-DD HH:MM"
_fired_marks = {}
_scheduler_thread = None
_scheduler_running = False


def _should_fire(task) -> bool:
    """判断任务是否应在本轮触发: 当前 HH:MM == cron, 且本分钟未发过。"""
    now = datetime.datetime.now()
    cur = now.strftime("%H:%M")
    target = f"{int(task['cron_hour']):02d}:{int(task['cron_minute']):02d}"
    if cur != target:
        return False
    mark = _fired_marks.get(task["id"])
    if mark == now.strftime("%Y-%m-%d %H:%M"):
        return False  # 本分钟已触发
    return True


def _execute_task(task):
    tid = task["id"]
    print(f"[调度] 触发定时发布 task#{tid} brand={task['brand']} topic={task['topic']}")
    # 发布前清理, 保证单实例浏览器环境干净
    try:
        pre_publish_cleanup(verbose=True)
    except Exception as e:
        print(f"[调度] 发布前清理异常(继续): {e}")
    try:
        results = pipeline_run(task["brand"], task["topic"], [task["platform"]])
        # results: {platform: {ok, message, ...}}
        plat = results.get(task["platform"], {})
        ok = bool(plat.get("ok"))
        status = "success" if ok else f"failed:{plat.get('message','')[:80]}"
    except Exception as e:
        status = f"error:{str(e)[:120]}"
        print(f"[调度] task#{tid} 异常: {traceback.format_exc()}")
    update_publish_task_run(tid, status)
    _fired_marks[tid] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[调度] task#{tid} 完成 status={status}")


def _loop():
    global _scheduler_running
    print("[调度] 后台线程启动")
    while _scheduler_running:
        try:
            tasks = list_publish_tasks()
            for t in tasks:
                if not t.get("enabled"):
                    continue
                # 视频平台任务直接跳过(边界约束)
                if t.get("platform") != "xiaohongshu":
                    continue
                if _should_fire(t):
                    _execute_task(t)
        except Exception as e:
            print(f"[调度] 轮询异常: {e}")
        time.sleep(POLL_INTERVAL)
    print("[调度] 后台线程停止")


def start_scheduler():
    """拉起后台调度线程(幂等)。"""
    global _scheduler_thread, _scheduler_running
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
    _scheduler_thread.start()


def stop_scheduler():
    global _scheduler_running
    _scheduler_running = False


def run_now(tid):
    """立即触发一次任务(供 API /api/scheduler/run-now 调用)。"""
    from db import get_publish_task
    task = get_publish_task(tid)
    if not task:
        return {"ok": False, "message": f"任务 {tid} 不存在"}
    _execute_task(task)
    return {"ok": True, "task_id": tid, "next_run_at": compute_next_run_at(task)}
