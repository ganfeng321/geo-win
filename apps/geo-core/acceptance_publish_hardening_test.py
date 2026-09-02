# B 真实发布自动化加固 验收(对应 F7/F10 健壮性增强)
# 设计原则: 纯标准库 + 不依赖真实登录态即可全量验收;真实发布按 ALLOW_REAL_PUBLISH=1 才跑,否则 SKIP(同 CI --skip-real 精神)。
# AC_B1: 未知平台 -> error_type=unknown_platform, need_login=False, 且账号探针前置短路(不调发布端)
# AC_B2: 无账号平台 -> error_type=no_account, need_login=True(半自动登录衔接信号)
# AC_B3: Cookie 过期探针(_cookie_age_days 纯函数): 超龄文件返回>阈值, 不存在文件返回 None
# AC_B4: 发布前自检 pre_publish_cleanup 可调用且不抛错
# AC_B5: 账号探针前置短路(unknown_platform 不进入 requests 超时路径)
# AC_B6: error_type 结构化落库(insert_publish 后 list_publish 最新含 error_type, 旧库兼容)
# AC_B7: /api/publish 接口返回含 error_type 键 + need_login 信号结构
# AC_B8: 真实发布按约定跳过(ALLOW_REAL_PUBLISH 未置则 SKIP, 不判失败)
import sys, os, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CORE_BASE
import urllib.request, urllib.error

PASS, FAIL, SKIP = [], [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'✓' if cond else '✗'}] {name}" + (f"  {detail}" if detail else ""))
def skip(name, detail=""):
    SKIP.append(name)
    print(f"  [~] {name}" + (f"  {detail}" if detail else ""))

print("=== B 真实发布自动化加固 验收 ===")
from db import init, list_publish, insert_publish
from publisher_client import PublisherClient
init()
pub = PublisherClient()

# --- AC_B1: 未知平台 ---
ac = pub.check_account("not_a_platform")
check("AC_B1 未知平台探针 ok=False", ac["ok"] is False, str(ac))
check("AC_B1 error_type=unknown_platform", ac["error_type"] == "unknown_platform", ac.get("error_type"))
check("AC_B1 need_login=False", ac["need_login"] is False)
res = pub.publish("not_a_platform", "t", "x")
check("AC_B1 发布返回 failed", res["status"] == "failed")
check("AC_B1 发布 error_type=unknown_platform", res["error_type"] == "unknown_platform")
check("AC_B1 发布 need_login=False", res.get("need_login") is False)
check("AC_B1 结构化含 error_type 键", "error_type" in res and "record_id" in res)

# --- AC_B2: 无账号平台(自动探测, 环境无该平台账号才验) ---
# 选一个 MAP 中存在但发布端大概率无账号的平台做验证;若环境已有账号则 SKIP
probe = pub.check_account("douyin")
if probe["ok"]:
    skip("AC_B2 无账号 -> no_account", "环境已录入 douyin 账号,跳过以防误真实发布")
else:
    check("AC_B2 无账号 error_type=no_account", probe["error_type"] == "no_account", probe.get("error_type"))
    check("AC_B2 无账号 need_login=True(半自动衔接)", probe["need_login"] is True)
    r2 = pub.publish("douyin", "t", "x")
    check("AC_B2 发布返回 need_login=True", r2.get("need_login") is True, str(r2.get("need_login")))
    check("AC_B2 发布 error_type=no_account", r2["error_type"] == "no_account")

# --- AC_B3: Cookie 过期探针纯函数 ---
import tempfile
tf = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
tf.write(b"{}"); tf.close()
old = os.path.getmtime(tf.name)
# 改 mtime 到 30 天前
os.utime(tf.name, (old - 30*86400, old - 30*86400))
age = pub._cookie_age_days(tf.name)
check("AC_B3 超龄 cookie 探测 > 阈值(7天)", age is not None and age > 7, f"age={age}")
none_age = pub._cookie_age_days("__no_such_cookie_file__.json")
check("AC_B3 不存在 cookie 返回 None", none_age is None)
os.unlink(tf.name)

# --- AC_B4: 发布前自检可调用 ---
try:
    from proc_utils import pre_publish_cleanup
    pre_publish_cleanup(verbose=False)
    check("AC_B4 pre_publish_cleanup 可调用不抛错", True)
except Exception as e:
    check("AC_B4 pre_publish_cleanup 可调用不抛错", False, f"err={e}")

# --- AC_B5: 账号探针前置短路(unknown_platform 不应进入发布端网络调用) ---
t0 = time.time()
pub.publish("not_a_platform", "t", "x", skip_cleanup=True)  # skip_cleanup 避免自检干扰计时
dt = time.time() - t0
check("AC_B5 未知平台不进入发布端(耗时<2s,前置短路)", dt < 2.0, f"dt={dt:.2f}s")

# --- AC_B6: error_type 结构化落库(旧库兼容) ---
pid = insert_publish(None, "xiaohongshu", 1, "failed", "测试错误", error_type="unknown_platform")
rows = list_publish(1)
latest = rows[0] if rows else {}
check("AC_B6 error_type 落库可读", latest.get("error_type") == "unknown_platform", f"latest={latest.get('error_type')}")
check("AC_B6 旧库含 error_type 列(兼容)", "error_type" in latest)

# --- AC_B7: /api/publish 接口结构 ---
def _post(url, obj):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

st, body = _post(f"{CORE_BASE}/api/publish", {"platform": "not_a_platform", "title": "t", "text": "x"})
check("AC_B7 未知平台接口 ok=False", body.get("ok") is False, str(body))
check("AC_B7 接口返回含 error_type 键", "error_type" in body, str(body.get("error_type")))
st2, body2 = _post(f"{CORE_BASE}/api/publish", {})  # 缺 platform
check("AC_B7 缺参数接口 ok=False", body2.get("ok") is False)

# --- AC_B8: 真实发布按约定跳过 ---
if os.getenv("ALLOW_REAL_PUBLISH") == "1":
    acct = pub.check_account("xiaohongshu")
    if acct["ok"]:
        r = pub.publish("xiaohongshu", "GEO自动化测试", "这是自动化加固验收的测试发布", tags="GEO")
        check("AC_B8 真实发布成功", r["status"] == "success", str(r))
    else:
        skip("AC_B8 真实发布", "小红书未登录,跳过")
else:
    skip("AC_B8 真实发布", "ALLOW_REAL_PUBLISH 未置位,按 --skip-real 约定跳过(不判失败)")

print(f"\n=== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 / {len(SKIP)} 跳过 ===")
if FAIL:
    print("失败项:", FAIL); sys.exit(1)
print("B 真实发布自动化加固 验收通过 ✓")
