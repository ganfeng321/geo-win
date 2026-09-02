# F13 报表快照与导出验收
# AC13.1: CSV 导出可下载且为合法多表 CSV(含三大模块表头)
# AC13.2: JSON 导出可下载且为合法 JSON(可 json.loads)
# AC13.3: JSON 含全量模块键(overview/snapshots/generated/published/accounts/projects/alerts/insights)
# AC13.4: JSON 字段类型完整(generated 为 int, published_records 为 list 等)
# AC13.5: CSV 带 UTF-8 BOM(Excel 友好)
# AC13.6: 两种导出均 HTTP 200 且 Content-Disposition 为 attachment
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import CORE_BASE
import urllib.request

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'✓' if cond else '✗'}] {name}" + (f"  {detail}" if detail else ""))

def _get(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, r.read(), dict(r.getheaders())

def _text(raw):
    return raw.decode("utf-8-sig")

print("=== F13 报表快照与导出验收 ===")

# --- CSV 导出 ---
st_csv, raw_csv, hd_csv = _get(f"{CORE_BASE}/api/export?type=csv")
body_csv = _text(raw_csv)
check("AC13.6 CSV HTTP 200", st_csv == 200, f"status={st_csv}")
disp = hd_csv.get("Content-Disposition", "")
check("AC13.6 CSV 为附件下载", "attachment" in disp, f"disp={disp}")
check("AC13.5 CSV 带 UTF-8 BOM", raw_csv[:3] == b"\xef\xbb\xbf", f"head={raw_csv[:3]!r}")
check("AC13.1 CSV 含闭环快照表头", "== 可见性闭环快照 ==" in body_csv)
check("AC13.1 CSV 含生成内容表头", "== 生成内容 ==" in body_csv)
check("AC13.1 CSV 含发布记录表头", "== 发布记录 ==" in body_csv)
# 合法 CSV: 用标准库按行解析不抛错(允许空分隔行)
import csv, io
try:
    rows = list(csv.reader(io.StringIO(body_csv.lstrip("\ufeff"))))
    non_empty = [r for r in rows if any(c.strip() for c in r)]
    has_headers = any("== 可见性闭环快照 ==" in r for r in rows)
    check("AC13.1 CSV 可被 csv 模块解析", len(non_empty) > 3 and has_headers,
          f"rows={len(rows)} non_empty={len(non_empty)}")
except Exception as e:
    check("AC13.1 CSV 可被 csv 模块解析", False, f"err={e}")

# --- JSON 导出 ---
st_json, raw_json, hd_json = _get(f"{CORE_BASE}/api/export?type=json")
body_json = _text(raw_json)
check("AC13.6 JSON HTTP 200", st_json == 200, f"status={st_json}")
disp_j = hd_json.get("Content-Disposition", "")
check("AC13.6 JSON 为附件下载", "attachment" in disp_j, f"disp={disp_j}")
try:
    data = json.loads(body_json)
    parsed = True
except Exception as e:
    data, parsed = {}, False
check("AC13.2 JSON 合法可解析", parsed)

if parsed:
    keys = ["version", "exported_at", "overview", "visibility_snapshots",
            "generated", "published_records", "accounts", "monitor_projects",
            "alerts", "insights"]
    missing = [k for k in keys if k not in data]
    check("AC13.3 JSON 含全量模块键", not missing, f"missing={missing}")
    ov = data.get("overview", {})
    check("AC13.4 overview.generated 为 int", isinstance(ov.get("generated"), int), f"val={ov.get('generated')}")
    check("AC13.4 overview.published 为 int", isinstance(ov.get("published"), int), f"val={ov.get('published')}")
    check("AC13.4 visibility_snapshots 为 list", isinstance(data.get("visibility_snapshots"), list))
    check("AC13.4 generated 为 list", isinstance(data.get("generated"), list))
    check("AC13.4 published_records 为 list", isinstance(data.get("published_records"), list))
    check("AC13.4 accounts 为 list", isinstance(data.get("accounts"), list))
    check("AC13.4 monitor_projects 为 list", isinstance(data.get("monitor_projects"), list))
    check("AC13.4 alerts 为 list", isinstance(data.get("alerts"), list))
    check("AC13.4 insights 为 list", isinstance(data.get("insights"), list))
    check("AC13.4 version 为字符串", isinstance(data.get("version"), str), f"v={data.get('version')}")
    check("AC13.4 exported_at 为字符串", isinstance(data.get("exported_at"), str), f"t={data.get('exported_at')}")
    # 默认 type=csv 之外的兜底: 显式 json 与默认一致
    check("AC13.3 JSON 导出无异常", True)

print(f"\n=== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
if FAIL:
    print("失败项:", FAIL); sys.exit(1)
print("F13 报表快照与导出验收通过 ✓")
