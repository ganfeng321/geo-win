import os, subprocess, time

ROOT = r"d:\GEO-XINXIANGMU-00\apps\geo-core"
VENV_PY = r"d:\GEO-XINXIANGMU-00\apps\geo-core\venv\Scripts\python.exe"
log_out = os.path.join(ROOT, "dash.out.log")
log_err = os.path.join(ROOT, "dash.err.log")
with open(log_out, "w") as fo, open(log_err, "w") as fe:
    subprocess.Popen([VENV_PY, "dashboard_api.py"], cwd=ROOT, stdout=fo, stderr=fe)
time.sleep(3)
try:
    import urllib.request
    r = urllib.request.urlopen("http://localhost:7000/api/overview", timeout=5)
    print("dash UP", r.status)
except Exception as e:
    print("dash NOT UP:", e)
    print(open(log_err).read()[:1000])
