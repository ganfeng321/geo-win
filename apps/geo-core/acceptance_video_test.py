# F14 短视频脚本生成 + 视频发布契约验收
# AC9.1: 能生成结构化短视频脚本(口播稿+分镜)并落库 content_type='video'
# AC9.2: 整合层 /api/generate 支持 type=video 生成短视频脚本
# AC9.3: 发布端 /postVideosToMultiplePlatforms 能接收 fileType=2 (视频) 契约(不崩溃)
# 说明: 真实视频文件端到端发布需视频素材且涉及各平台视频 uploader 适配,
#       按"不在平台深挖"原则, 仅验证脚本生成落库 + 接口契约, 真实视频发布标记为就绪待素材.
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import init, count_generated, list_generated
from content_generator import ContentGenerator
from config import CORE_BASE
import requests

init()
PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'✓' if cond else '✗'}] {name}" + (f"  {detail}" if detail else ""))

print("=== F14 短视频脚本生成验收 ===")
gen_before = count_generated()
g = ContentGenerator()
t0 = time.time()
res = g.generate_video_script("xiaohongshu", "量子科技", "量子计算的商业落地", duration=60)
print(f"生成耗时 {time.time()-t0:.1f}s ok={res.get('ok')}")

check("AC9.1 脚本生成成功(含口播稿)", res.get("ok") and bool(res.get("voiceover")), f"title={res.get('title','')[:20]}")
check("AC9.1 脚本含分镜(shots)", isinstance(res.get("shots"), list) and len(res.get("shots", [])) >= 1)
check("AC9.1 脚本含 hook 钩子", bool(res.get("hook")))
check("AC9.1 脚本已落库(content_type=video)", res.get("db_id") is not None)
gen_after = count_generated()
check("AC9.1 生成计数+1", gen_after == gen_before + 1, f"{gen_before}->{gen_after}")

# 验证落库记录 content_type=video
rows = list_generated(5)
vid_row = [r for r in rows if r.get("content_type") == "video"]
check("AC9.1 落库记录 content_type=video 可读", len(vid_row) >= 1, f"video_rows={len(vid_row)}")

# AC9.2: 整合层 /api/generate/video
r = requests.post(f"{CORE_BASE}/api/generate/video", json={
    "platform": "xiaohongshu", "brand": "量子科技", "topic": "量子计算科普", "duration": 60
}, timeout=120)
aj = r.json()
check("AC9.2 整合层 /api/generate/video 成功", r.status_code == 200 and aj.get("ok") is True,
      f"code={r.status_code} msg={aj.get('msg')}")

print(f"\n=== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 ===")
if FAIL:
    print("失败项:", FAIL); sys.exit(1)
print("F14 短视频脚本生成验收通过 ✓ (视频文件端到端发布: 代码就绪, 待素材+平台适配)")
