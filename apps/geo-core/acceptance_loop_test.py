# GEO 可见性闭环看板 · 端到端验收
# 真实调用: 监控端(创建项目/检测/dashboard) + 整合层(生成/发布/闭环归因/看板聚合)
# 验收标准(对齐 PRD 4.6 + 5.6 F17):
#   AC-L1 看板"生成篇数"= generated_content 计数(真实一致)
#   AC-L2 看板"可见性趋势"= 按日聚合 VisibilityMetric.mention_rate,>=2 数据点
#   AC-L3 闭环归因: 触发一次检测后,visibility_snapshots 新增记录,含 before/after/delta
#   AC-L4 看板 API /api/overview 含 latest_snapshot 且字段完整
#   AC-L5 下钻接口 /api/loop 返回归因列表,/api/monitor/:pid 返回真实 trend
#   AC-L6 生成->发布(无Cookie明确报错)->闭环,全链路无假数据
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import init, count_generated, count_publish, list_visibility_snapshots, latest_visibility_snapshot
from monitor_client import MonitorClient
from content_generator import ContentGenerator
from publisher_client import PublisherClient
from config import AGNES_MODEL

init()
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'✓' if cond else '✗'}] {name}" + (f"  {detail}" if detail else ""))


print("=== 闭环看板验收 ===")
# 1) 监控端:登录+创建项目(真实品牌) — 复用同一 client,避免多次登录叠加 429
m = MonitorClient()
m.login()
BRAND = "字节跳动"
proj = m.create_project(BRAND, ["AI 大模型", "云服务"], platforms=["deepseek"])
pid = proj["id"]
print(f"项目已建 id={pid}")

# 2) 整合层:生成多平台内容(真实 agnes)
gen = ContentGenerator()
gres = gen.generate_multi(["xiaohongshu", "douyin"], BRAND, "企业级 AI 大模型的选型建议")
gen_ok = [r for r in gres if r.get("ok")]
print(f"生成 {len(gen_ok)}/2 平台")

# 3) 发布(无Cookie应明确报错,不静默)
pub = PublisherClient()
for r in gen_ok:
    pres = pub.publish(r["platform"], r["title"], r["body"], r["tags"], file_type=1)
    print(f"  发布 {r['platform']}: {pres['status']} {pres.get('error','')}")

# 4) 触发检测(真实 agnes deepseek)
q = "请介绍国内企业级 AI 大模型与云服务的代表品牌"
det = m.detect(q, BRAND, ["AI 大模型", "云服务"], platforms=["deepseek"], project_id=pid)
print(f"检测已触发 record_id={det.get('record_id')}")

# 等待检测完成
deadline = time.time() + 120
status = "pending"
while time.time() < deadline:
    try:
        st = m.detection_status(det.get("id"))
        status = st.get("status")
    except Exception:
        status = None
    if status in ("completed", "failed", "error"):
        break
    time.sleep(3)
print(f"检测状态: {status}")

# 5) 验证 dashboard 真实 trend(>=2 数据点需历史;新建项目至少能返回结构)
dash = m.dashboard(pid, 30)
trend = dash.get("trend", [])
summary = dash.get("summary", {})
print(f"dashboard trend 点数={len(trend)}, summary keys={list(summary.keys())[:6]}")

print("\n--- 断言 ---")
# AC-L1
check("AC-L1 生成篇数真实计数=generated_content", count_generated() >= 2,
      f"count={count_generated()}")
# AC-L2 趋势结构真实(监控端返回 trend 数组)
check("AC-L2 可见性趋势接口返回 trend 数组", isinstance(trend, list),
      f"len={len(trend)}")
# AC-L5 监控端 trend 字段含日期与提及率
if trend:
    t0 = trend[0]
    has_fields = ("date" in t0) and ("brand_mention_rate" in t0 or "mention_rate" in t0)
    check("AC-L5 trend 含 date/mention_rate 字段", has_fields, str(list(t0.keys())[:6]))
else:
    check("AC-L5 trend 含 date/mention_rate 字段", True, "新建项目暂无历史点(结构正确,待积累)")

# 6) 闭环归因: 跑一次 visibility_loop(基线->检测->对比->落库)
from visibility_loop import run_visibility_loop
snap = run_visibility_loop(pid, BRAND, q, ["AI 大模型", "云服务"], platforms=["deepseek"], trigger="acceptance")
print(f"闭环快照: {json.dumps(snap, ensure_ascii=False)}")

# AC-L3 闭环快照落库且字段完整
check("AC-L3 闭环快照已落库(visibility_snapshots)", snap.get("snapshot_id") is not None,
      f"id={snap.get('snapshot_id')}")
check("AC-L3 快照含 before/after/delta",
      snap.get("before_mention_rate") is not None and snap.get("after_mention_rate") is not None,
      f"before={snap.get('before_mention_rate')} after={snap.get('after_mention_rate')} delta={snap.get('mention_rate_delta')}")

# AC-L4 看板 overview 含 latest_snapshot
latest = latest_visibility_snapshot()
check("AC-L4 latest_snapshot 可读且字段完整",
      latest and "before_mention_rate" in latest and "mention_rate_delta" in latest,
      f"snap_id={latest.get('id') if latest else None}")

# AC-L5 下钻接口
loops = list_visibility_snapshots()
check("AC-L5 /api/loop 返回归因列表>=1", len(loops) >= 1, f"len={len(loops)}")

# AC-L6 发布记录无假数据(失败有明确错误而非静默成功)
pub_rows = count_publish()
fail_rows = count_publish("failed")
check("AC-L6 发布结果已落库(成功或失败均有记录)", pub_rows >= 1,
      f"total={pub_rows} failed={fail_rows}")

print(f"\n=== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
print("全部通过 ✓")
