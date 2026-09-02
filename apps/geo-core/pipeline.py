# 端到端编排流水线:生成(多平台) -> 发布(对应平台) -> 落库
# 用法:
#   python pipeline.py --brand "量子科技" --topic "量子计算云服务的企业级优势" --platforms xiaohongshu douyin
#   python pipeline.py --brand X --topic Y --platforms xiaohongshu --skip-publish   # 仅生成
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import init, get_conn
from content_generator import ContentGenerator
from publisher_client import PublisherClient
from config import AGNES_MODEL

# 修正:管道运行记录单独处理
from db import get_conn


def _log_run(brand, topic, platforms, summary):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO pipeline_runs (brand,topic,platforms,finished_at,result_summary) VALUES (?,?,?,CURRENT_TIMESTAMP,?)",
        (brand, topic, ",".join(platforms), summary))
    conn.commit()
    conn.close()


def run(brand: str, topic: str, platforms: list, skip_publish: bool = False):
    init()
    gen = ContentGenerator()
    pub = PublisherClient() if not skip_publish else None

    print(f"[1] 生成 {len(platforms)} 个平台内容(模型 {AGNES_MODEL})...")
    results = gen.generate_multi(platforms, brand, topic)

    summary_lines = []
    if not skip_publish:
        # 发布前自检(服务存活 + 杀残留 Chromium),避免同步阻塞 180s 超时
        try:
            from proc_utils import pre_publish_cleanup
            pre_publish_cleanup(verbose=False)
        except Exception:
            pass
    for r in results:
        if not r.get("ok"):
            print(f"  ✗ {r['platform']} 生成失败: {r.get('error')}")
            summary_lines.append(f"{r['platform']}:生成失败")
            continue
        print(f"  ✓ {r['platform']}: {r['title']}  (db_id={r.get('db_id')})")
        if skip_publish:
            summary_lines.append(f"{r['platform']}:已生成")
            continue
        # 发布(隔离失败:某平台失败不影响其他)
        pres = pub.publish(r["platform"], r["title"], r["body"], r["tags"], file_type=1)
        # 关联发布记录到生成内容
        conn = get_conn()
        conn.execute("UPDATE publish_records SET generated_content_id=? WHERE id=?", (r.get("db_id"), pres.get("record_id")))
        conn.commit()
        conn.close()
        status = "✓发布成功" if pres["status"] == "success" else f"✗发布失败:{pres['error']}"
        print(f"    └ {status}")
        summary_lines.append(f"{r['platform']}:{pres['status']}")

    _log_run(brand, topic, platforms, "; ".join(summary_lines))
    print("\n[完成] 汇总:", "; ".join(summary_lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", required=True)
    ap.add_argument("--topic", required=True)
    ap.add_argument("--platforms", nargs="+", default=["xiaohongshu", "douyin"])
    ap.add_argument("--skip-publish", action="store_true", help="仅生成不发布")
    args = ap.parse_args()
    run(args.brand, args.topic, args.platforms, args.skip_publish)
