# 机会洞察生成器(F15): 汇聚真实运行数据(可见性快照/生成/发布/告警),
# 用 LLM 产出 GEO 优化机会洞察报告, 落库供后台查看。
# 数据全部来自整合层 db + 监控端真实返回, 无假数据; LLM 调用失败则明确报错。
import json
from db import (
    list_visibility_snapshots, list_generated, list_publish,
    list_alerts, insert_insight,
)
from llm_client import LLMClient


class InsightGenerator:
    def __init__(self, client: LLMClient = None):
        self.client = client or LLMClient()

    def _collect_context(self, brand: str = None) -> dict:
        snaps = list_visibility_snapshots(50)
        if brand:
            snaps = [s for s in snaps if s.get("brand") == brand] or snaps
        gen = list_generated(50)
        pub = list_publish(50)
        alerts = list_alerts(0, 30)
        return {"snapshots": snaps, "generated": gen, "published": pub, "alerts": alerts}

    def generate(self, brand: str = None, scope: str = "global") -> dict:
        ctx = self._collect_context(brand)
        # 精简上下文, 避免 token 过大
        snap_summary = [
            {
                "brand": s.get("brand"), "trigger": s.get("trigger"),
                "before_rate": s.get("before_mention_rate"),
                "after_rate": s.get("after_mention_rate"),
                "rate_delta": s.get("mention_rate_delta"),
                "before_score": s.get("before_visibility_score"),
                "after_score": s.get("after_visibility_score"),
                "score_delta": s.get("visibility_score_delta"),
            }
            for s in ctx["snapshots"][:20]
        ]
        gen_summary = [
            {"platform": g.get("platform"), "title": g.get("title"), "status": g.get("status")}
            for g in ctx["generated"][:20]
        ]
        pub_summary = [
            {"platform": p.get("platform"), "account": p.get("account"), "status": p.get("status")}
            for p in ctx["published"][:20]
        ]
        alert_summary = [a.get("message") for a in ctx["alerts"][:10]]

        system = ("你是 GEO(生成式引擎优化)战略顾问。基于真实运行数据,产出可执行的"
                  "GEO 机会洞察:哪些话题/平台/内容形式能提升品牌在 AI 回答中的可见性。"
                  "严格输出 JSON。")
        user = (
            f"品牌范围: {brand or '全部'}\n\n"
            f"可见性闭环快照(最新 {len(snap_summary)} 条):\n{json.dumps(snap_summary, ensure_ascii=False)}\n\n"
            f"已生成内容({len(gen_summary)} 条):\n{json.dumps(gen_summary, ensure_ascii=False)}\n\n"
            f"已发布记录({len(pub_summary)} 条):\n{json.dumps(pub_summary, ensure_ascii=False)}\n\n"
            f"当前告警({len(alert_summary)} 条):\n{json.dumps(alert_summary, ensure_ascii=False)}\n\n"
            "请输出 JSON,字段:\n"
            "summary(一句话总体判断,不超过60字)、\n"
            "opportunities(数组,3-6 条,每条 {topic:机会主题, platform:建议平台/引擎, "
            "action:具体动作, reason:依据数据的理由})。\n"
            "洞察必须紧扣上方真实数据,禁止编造不存在的指标。"
        )
        raw = self.client.chat(system, user, max_tokens=1600, temperature=0.6)
        parsed = self._parse(raw)
        parsed["brand"] = brand
        parsed["scope"] = scope
        # 落库
        parsed["db_id"] = insert_insight(
            scope, parsed.get("summary", ""), json.dumps(parsed.get("opportunities", []), ensure_ascii=False))
        return parsed

    @staticmethod
    def _parse(raw: str) -> dict:
        import re
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.M)
        try:
            d = json.loads(raw)
        except Exception:
            # 退而求其次: 提取 summary/opportunities 文本
            d = {"summary": raw[:200], "opportunities": []}
        return {
            "summary": str(d.get("summary", "")).strip(),
            "opportunities": d.get("opportunities", []) or [],
        }


if __name__ == "__main__":
    g = InsightGenerator()
    print(json.dumps(g.generate(), ensure_ascii=False, indent=2))
