# F8 账号管理验收
# AC7.1: 后台能展示各平台账号登录状态
# AC7.2: 后台能触发账号登录(返回正确提示/契约)
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CORE_BASE
import requests

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'✓' if cond else '✗'}] {name}" + (f"  {detail}" if detail else ""))

print("=== F8 账号管理验收 ===")
r = requests.get(f"{CORE_BASE}/api/accounts", timeout=10)
acc = r.json().get("accounts", [])
print(f"账号总数: {len(acc)}")
for a in acc:
    print(f"  - {a['platform_name']}(type={a['type']}) status={a['status']} account={a['account']} file={a['cookiesFile']}")

# AC7.1: 至少展示出已录入的小红书账号且 status=1
xhs = [a for a in acc if a["platform_key"] == "xiaohongshu"]
check("AC7.1 后台展示小红书账号", len(xhs) >= 1, f"count={len(xhs)}")
if xhs:
    check("AC7.1 小红书账号已登录(status=1)", xhs[0]["status"] == 1, f"status={xhs[0]['status']}")

# AC7.2: 触发登录接口返回正确契约(不真弹窗, 只验证接口)
# 用一个已登录账号触发, 验证返回 ok=True 且含提示文案
if xhs:
    login = requests.post(f"{CORE_BASE}/api/accounts/login",
                          json={"type": xhs[0]["type"], "account": xhs[0]["id"]}, timeout=10)
    lj = login.json()
    check("AC7.2 触发登录接口返回 ok", lj.get("ok") is True, f"resp={lj.get('msg')}")
    check("AC7.2 返回提示含平台名", "小红书" in (lj.get("msg") or ""), f"msg={lj.get('msg')}")

check("AC7.1 HTTP 200", r.status_code == 200)

print(f"\n=== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
if FAIL:
    print("失败项:", FAIL); sys.exit(1)
print("F8 账号管理验收通过 ✓")
