# F18 定时自动发布落地验收
# 验证: 创建定时发布任务 -> 列表可见 -> 立即触发真实发布小红书 success -> 任务执行记录更新
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import requests
from db import init
from config import CORE_BASE

init()
PASS, FAIL = [], []
BASE = f"{CORE_BASE}/api/scheduler"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'✓' if cond else '✗'}] {name}" + (f" -> {detail}" if detail and not cond else ""))


def main():
    print("== F18 定时自动发布落地 ==")
    # AC18.1 创建定时任务(仅 xiaohongshu)
    r = requests.post(f"{BASE}/tasks",
                      json={"brand": "量子科技", "topic": "量子纠错芯片最新进展",
                            "platform": "xiaohongshu", "cron_hour": 9, "cron_minute": 30},
                      timeout=10)
    ok = r.status_code == 200 and r.json().get("ok")
    tid = r.json().get("task_id")
    check("AC18.1 创建定时任务", ok and tid, r.text[:120])
    if not tid:
        return _done()

    # AC18.2 视频平台任务被拒(边界约束)
    r2 = requests.post(f"{BASE}/tasks", json={"brand": "x", "topic": "y", "platform": "douyin"}, timeout=10)
    check("AC18.2 非小红书平台任务被拒", r2.status_code == 400, r2.text[:120])

    # AC18.3 任务列表可见
    time.sleep(0.3)
    r3 = requests.get(f"{BASE}/tasks", timeout=10)
    tasks = r3.json().get("tasks", [])
    visible = any(t["id"] == tid for t in tasks)
    check("AC18.3 任务出现在列表", visible, f"list len={len(tasks)}")

    # AC18.4 立即触发 -> 真实发布小红书 success
    r4 = requests.post(f"{BASE}/run-now", json={"task_id": tid}, timeout=300)
    j4 = r4.json()
    check("AC18.4 立即触发接口返回ok", j4.get("ok"), r4.text[:160])

    # AC18.5 任务执行状态已更新(success 表示真实发布成功)
    time.sleep(1.0)
    from db import list_publish_tasks, list_publish, list_generated
    t = next((x for x in list_publish_tasks() if x["id"] == tid), None)
    last_status = (t or {}).get("last_status", "")
    check("AC18.5 任务执行状态已更新", bool(last_status), f"last_status={last_status}")
    # AC18.6 发布落库(publish_records): 平台=xiaohongshu 且 status=success
    pub = list_publish(200)
    pub_hit = any(p.get("platform") == "xiaohongshu" and p.get("status") == "success" for p in pub)
    check("AC18.6 发布落库(publish_records)", pub_hit,
          f"pub={len(pub)}, sample={pub[0] if pub else None}")
    # AC18.7 生成落库(generated_content): 含品牌名(取较大范围避免被 limit 截断)
    gen = list_generated(200)
    gen_hit = any("量子科技" in (g.get("title") or g.get("content") or "") for g in gen)
    check("AC18.7 生成落库(generated_content)", gen_hit, f"gen={len(gen)}")

    # AC18.8 删除任务
    r5 = requests.post(f"{BASE}/delete", json={"task_id": tid}, timeout=10)
    check("AC18.8 删除任务", r5.json().get("ok"), r5.text[:120])

    _done()


def _done():
    print(f"\nF18 结果: {len(PASS)} 通过, {len(FAIL)} 失败")
    if FAIL:
        print("失败:", FAIL)
        sys.exit(1)
    print("F18 全部通过 ✓")
    sys.exit(0)


if __name__ == "__main__":
    main()
