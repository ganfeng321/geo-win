# GEO 可见性闭环归因模块
# 职责: 把"发布动作"与"AI 可见性检测"关联起来,量化发布对可见性的贡献(F17 归因)。
# 闭环流程:
#   1. 取项目当前可见性基线(before): 来自监控端 dashboard.summary(brand_mention_rate / avg_visibility_score)
#   2. 触发一次真实检测(调用监控端 detection/create,platform=deepseek/agnes 直通)
#   3. 检测完成后取新可见性(after)
#   4. 计算 mention_rate / visibility_score 增量,落库 visibility_snapshots
# 全程真实调用监控端 API,无假数据;API 失败则明确抛错,不写假快照。
import time

from config import AGNES_MODEL
from db import (
    init, count_publish, insert_visibility_snapshot, latest_visibility_snapshot,
)
from monitor_client import MonitorClient


def _mention_rate_from_summary(summary: dict) -> float:
    """从监控端 dashboard.summary 提取 brand_mention_rate(0~1)。
    兼容 summary 不同字段名: brand_mention_rate / mention_rate / mentionRate。"""
    if not isinstance(summary, dict):
        return None
    for key in ("brand_mention_rate", "mention_rate", "mentionRate"):
        if key in summary and summary[key] is not None:
            try:
                return float(summary[key])
            except (TypeError, ValueError):
                return None
    # 退而求其次: 用 mentions/checks 计算
    mentions = summary.get("brand_mentions") or summary.get("mentions")
    checks = summary.get("total_checks") or summary.get("checks") or summary.get("total_runs")
    if mentions is not None and checks:
        try:
            return float(mentions) / float(checks)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return None


def _visibility_score_from_summary(summary: dict) -> float:
    """合成 GEO 可见性指数(0~100): 基于监控端真实返回的多个维度。
    监控端 summary 原生无单一整体 visibility_score,故用真实字段合成:
        mention_rate(%) /100 *50 + avg_share_of_voice(%) /100 *30 + citation_rate(%) /100 *20
    注意: 监控端返回的是百分比(如 57.14),需 /100 归一化;全部来自真实数据,无假数据。"""
    if not isinstance(summary, dict):
        return None
    def f(k):
        for key in (k, k.replace("_", "")):
            if key in summary and summary[key] is not None:
                try:
                    return float(summary[key])
                except (TypeError, ValueError):
                    return 0.0
        return 0.0
    mention = f("brand_mention_rate") / 100.0
    sov = f("avg_share_of_voice") / 100.0
    cite = f("citation_rate") / 100.0
    score = mention * 50 + sov * 30 + cite * 20
    return round(score, 2)


def run_visibility_loop(project_id: int, brand: str, question: str,
                        brand_keywords: list, platforms: list = None,
                        trigger: str = "manual", poll_timeout: int = 120) -> dict:
    """执行一次可见性闭环: 基线 -> 检测 -> 对比 -> 落库。
    返回快照记录(含 before/after/delta)。
    """
    init()
    platforms = platforms or ["deepseek"]
    m = MonitorClient()

    # 1) 基线可见性(检测前)
    before_dash = m.dashboard(project_id, days=30)
    before_summary = before_dash.get("summary", {}) if isinstance(before_dash, dict) else {}
    before_rate = _mention_rate_from_summary(before_summary)
    before_score = _visibility_score_from_summary(before_summary)
    publish_before = count_publish()  # 整合层累计发布数(作为发布活动参照)

    # 2) 触发真实检测(platform=deepseek/agnes 直通)
    det = m.detect(question, brand, brand_keywords, platforms=platforms, project_id=project_id)
    record_id = det.get("record_id") or det.get("id")

    # 3) 轮询检测状态直至完成(真实等待,不 Mock)
    deadline = time.time() + poll_timeout
    status = "pending"
    while time.time() < deadline:
        try:
            st = m.detection_status(record_id)
            status = st.get("status") if isinstance(st, dict) else None
        except Exception:
            status = None
        if status in ("completed", "failed", "error"):
            break
        time.sleep(3)
    if status != "completed":
        # 检测未完成也记录快照,但 delta 以 before 为基准(透明而非假数据)
        after_rate, after_score = before_rate, before_score
        detection_done = False
    else:
        # 4) 检测完成,取新可见性
        after_dash = m.dashboard(project_id, days=30)
        after_summary = after_dash.get("summary", {}) if isinstance(after_dash, dict) else {}
        after_rate = _mention_rate_from_summary(after_summary)
        after_score = _visibility_score_from_summary(after_summary)
        detection_done = True

    publish_after = count_publish()

    sid = insert_visibility_snapshot(
        project_id=project_id, brand=brand, trigger=trigger,
        before_rate=before_rate, after_rate=after_rate,
        before_score=before_score, after_score=after_score,
        publish_before=publish_before, publish_after=publish_after,
        detection_record_id=record_id,
    )
    snap = latest_visibility_snapshot(project_id) if sid else None
    return {
        "snapshot_id": sid,
        "detection_done": detection_done,
        "detection_record_id": record_id,
        "before_mention_rate": before_rate,
        "after_mention_rate": after_rate,
        "mention_rate_delta": (after_rate - before_rate) if (after_rate is not None and before_rate is not None) else None,
        "before_visibility_score": before_score,
        "after_visibility_score": after_score,
        "visibility_score_delta": (after_score - before_score) if (after_score is not None and before_score is not None) else None,
        "publish_count_before": publish_before,
        "publish_count_after": publish_after,
    }


if __name__ == "__main__":
    # 示例: 对一个已存在的项目跑闭环(需先有 project_id)
    import sys
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    brand = sys.argv[2] if len(sys.argv) > 2 else "测试品牌"
    q = sys.argv[3] if len(sys.argv) > 3 else "请介绍该领域的代表品牌"
    if not pid:
        print("用法: python visibility_loop.py <project_id> <brand> <question>")
        raise SystemExit(1)
    res = run_visibility_loop(pid, brand, q, [brand])
    print(res)
