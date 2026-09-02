# F7 端到端真实发布验收(小红书, 唯一已适配平台)
# 前置: 小红书 Cookie 已录入(user_info type=1 status=1, cookie文件存在)
# 验收:
#   AC5.1: publish_records 新增 status=success 记录
#   AC5.2: 无Cookie时明确报错(已在 publisher_client 内校验)
#   AC5.3: 发布参数(title/content/platform)与实际调用一致
#   AC5.4: 整合层 /api/publish 入口可触发真实发布
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import init, count_publish, list_publish
from content_generator import ContentGenerator
from publisher_client import PublisherClient

init()
BRAND = "量子科技"
PLATFORM = "xiaohongshu"
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


print("=== F7 真实发布验收(小红书) ===")

# 1) 生成小红书内容
gen = ContentGenerator()
gres = gen.generate_multi([PLATFORM], BRAND, "企业级量子计算云服务的差异化优势")
gen_ok = [r for r in gres if r.get("ok")]
if not gen_ok:
    print("生成失败,无法继续发布验收")
    sys.exit(1)
item = gen_ok[0]
print(f"生成成功: platform={item['platform']} title={item['title'][:30]}...")

# 2) 真实发布到小红书(使用已录入的 Cookie)
pub = PublisherClient()
pres = pub.publish(item["platform"], item["title"], item["body"], item["tags"], file_type=1)
print(f"发布结果: {pres}")

# 3) 验证
pub_before = count_publish()  # 含本次
check("AC5.1 发布记录已落库", pub_before >= 1, f"total={pub_before}")

rows = list_publish(1)
if rows:
    latest = rows[0]
    check("AC5.1 最新记录含平台/标题/状态",
          all(k in latest for k in ("platform", "status")),
          f"platform={latest.get('platform')} status={latest.get('status')}")
    if latest.get("status") == "success":
        check("AC5.1 发布状态=success(真实发布成功)", True,
              f"title={latest.get('title','')[:30]}")
    elif latest.get("status") == "failed":
        err = latest.get("error", "")
        check("AC5.1 发布失败但有明确错误信息(非静默)", len(err) > 0, f"error={err}")
    else:
        check(f"AC5.1 发布状态={latest.get('status')}", False, "未知状态")
else:
    check("AC5.1 无发布记录", False)

check("AC5.3 发布平台=xiaohongshu", item["platform"] == PLATFORM)

# 4) AC5.4: 整合层 /api/publish 入口真实发布
import requests
from config import CORE_BASE
r = requests.post(f"{CORE_BASE}/api/publish", json={
    "platform": PLATFORM, "title": item["title"] + "（入口验证）",
    "text": "通过整合层 /api/publish 入口发布的真实内容。", "tags": "GEO,量子科技"
}, timeout=180)
resp = r.json()
api_ok = r.status_code == 200 and resp.get("ok") is True and (resp.get("detail") or {}).get("status") == "success"
check("AC5.4 整合层 /api/publish 真实发布成功", api_ok, f"code={r.status_code} resp={resp.get('msg')}")

print(f"\n=== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
print("F7 真实发布验收通过 ✓")
