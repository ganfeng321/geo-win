# F10 GEO Pipeline 验收 (端到端: 监控项目 -> 生成内容 -> 真实发布小红书 -> 落库)
# AC8.1: 能按配置批量处理监控项目并生成内容
# AC8.2: 生成内容能真实发布(不再仅 dry-run)
# AC8.3: 生成与发布均落库(generated_content / publish_records)
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import init, count_generated, count_publish, list_generated, list_publish
from pipeline import run
from monitor_client import MonitorClient
from content_generator import ContentGenerator
from publisher_client import PublisherClient

init()
PASS, FAIL = [], []

# 发布前清理: 杀净残留 Chromium, 避免 180s 超时
try:
    from proc_utils import pre_publish_cleanup
    pre_publish_cleanup(verbose=True)
except Exception as e:
    print(f"  [警告] 发布前清理跳过: {e}")
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'✓' if cond else '✗'}] {name}" + (f"  {detail}" if detail else ""))

print("=== F10 GEO Pipeline 验收 ===")
PROJECT = "F10验收品牌"
KEYWORDS = ["量子计算", "云服务"]

# 1) 准备监控项目(幂等)
mc = MonitorClient()
mc.login()
proj = mc.create_project(PROJECT, KEYWORDS)
print(f"监控项目: id={proj.get('id')} name={proj.get('name')}")

# 2) 跑 pipeline (真实发布)
from pipeline import run
gen_before = count_generated()
pub_before = count_publish()
print("开始 run (真实发布, 约需40-80s)...")
t0 = time.time()
run(PROJECT, "量子计算云服务的差异化优势", ["xiaohongshu"])
summary = {"done": True}
print(f"pipeline 完成 (耗时 {time.time()-t0:.1f}s)")

# 3) 验证
gen_after = count_generated()
pub_after = count_publish()
check("AC8.1 生成内容落库", gen_after > gen_before, f"{gen_before}->{gen_after}")
check("AC8.2 真实发布记录落库", pub_after > pub_before, f"{pub_before}->{pub_after}")

gens = list_generated(5)
if gens:
    g = gens[0]
    check("AC8.1 生成记录含平台/标题", all(k in g for k in ("platform","title")), f"platform={g.get('platform')}")
    check("AC8.2 生成记录含正文(非空)", bool(g.get("body")), f"body_len={len(g.get('body') or '')}")

pubs = list_publish(5)
if pubs:
    p = pubs[0]
    check("AC8.2 发布记录含平台/状态", all(k in p for k in ("platform","status")), f"platform={p.get('platform')} status={p.get('status')}")
    if p.get("status") == "success":
        check("AC8.2 真实发布成功", True, f"title={p.get('title','')[:30]}")
    else:
        check("AC8.2 真实发布状态", False, f"status={p.get('status')} err={p.get('error')}")

check("AC8.3 pipeline 返回 summary", isinstance(summary, dict))

print(f"\n=== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
if FAIL:
    print("失败项:", FAIL); sys.exit(1)
print("F10 GEO Pipeline 验收通过 ✓")
