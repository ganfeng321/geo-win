# 闭环自动复盘(F20):发布→检测可见性→低提及率话题自动换角度重生成→(可选)再次发布
# 形成"发布-检测-优化"自循环。所有数据来自整合层 db + 监控端真实返回,无假数据。
import json
import threading
import time
import datetime

from db import (
    list_auto_review_tasks, get_auto_review_task, update_auto_review_task_run,
    update_auto_review_task_angle, list_visibility_snapshots, insert_alert,
)
from llm_client import LLMClient
from content_generator import ContentGenerator
from pipeline import run as pipeline_run


def _touch_auto_review_task(tid, status, rate=None):
    """仅更新最新状态/提及率,不增加运行次数(用于达阈值未触发的记录)。"""
    conn = __import__("db").get_conn()
    if rate is not None:
        conn.execute(
            "UPDATE auto_review_tasks SET last_run_at=CURRENT_TIMESTAMP,last_status=?,last_rate=? WHERE id=?",
            (status, rate, tid))
    else:
        conn.execute(
            "UPDATE auto_review_tasks SET last_run_at=CURRENT_TIMESTAMP,last_status=? WHERE id=?",
            (status, tid))
    conn.commit()
    conn.close()


# 低提及率触发复盘的默认阈值
DEFAULT_MIN_RATE = 0.15
# 后台自动循环轮询间隔(秒)
LOOP_INTERVAL = 120

# 角度候选库:LLM 在已用角度之外挑选一个,形成"换角度"效果
ANGLE_BANK = [
    "使用场景", "选购指南", "避坑清单", "行业干货", "真实测评", "对比评测",
    "用户故事", "专家观点", "数据拆解", "趋势解读", "常见问题", "冷知识科普",
]


class ReviewLoop:
    """闭环自动复盘引擎。

    review_once(task, publish): 对单个任务执行一次复盘闭环:
        1) 取该 brand/topic 最新可见性快照的真实 after_mention_rate;
        2) 若低于阈值 -> 用 LLM 基于已用角度生成新角度,重新生成内容;
        3) 若 publish=True 则走 pipeline 真实发布(复用 F7 已验证逻辑);
        4) 更新任务 angle / last_status / last_rate / run_count。
    """

    def __init__(self, client: LLMClient = None):
        self.client = client or LLMClient()
        self._thread = None
        self._stop = threading.Event()

    # ---------- 检测:该品牌话题最新可见性 ----------
    def _latest_rate(self, brand: str, topic: str):
        """返回该 brand(及 topic)最新可见性快照的 after_mention_rate,无则 None。"""
        snaps = list_visibility_snapshots(100)
        match = None
        for s in snaps:
            if s.get("brand") == brand:
                if topic and s.get("trigger") and topic in s.get("trigger", ""):
                    match = s
                    break
                match = s  # 取最新同品牌快照
        if not match:
            return None
        return match.get("after_mention_rate")

    # ---------- 换角度:LLM 生成新切入点 ----------
    def _next_angle(self, brand: str, topic: str, used_angle: str) -> str:
        used = [used_angle] if used_angle else []
        bank = [a for a in ANGLE_BANK if a not in used] or ANGLE_BANK
        system = ("你是 GEO 内容策略师。给定品牌话题与已用过的内容角度,从候选角度中挑一个"
                  "最能补足可见性短板的新角度。只输出角度名,不要解释。")
        user = (
            f"品牌: {brand}\n话题: {topic}\n已用角度: {used_angle or '无'}\n"
            f"候选角度: {', '.join(bank)}\n请选一个最能提升 AI 回答提及率的新角度(只回角度名)。"
        )
        try:
            raw = self.client.chat(system, user, max_tokens=20, temperature=0.7).strip()
            angle = raw.strip("【】[] \"'")
            if angle in bank:
                return angle
            # 若 LLM 返回了不在候选库中的合理角度,也接受(容错)
            return angle or (bank[0] if bank else "通用科普")
        except Exception:
            # LLM 失败时退化为轮换候选库
            for a in bank:
                if a != used_angle:
                    return a
            return bank[0] if bank else "通用科普"

    # ---------- 单次复盘闭环 ----------
    def review_once(self, task: dict, publish: bool = False) -> dict:
        tid = task["id"]
        brand = task["brand"]
        topic = task["topic"]
        platform = task.get("platform") or "xiaohongshu"
        used_angle = task.get("angle") or "通用科普"
        min_rate = task.get("min_mention_rate")
        if min_rate is None:
            min_rate = DEFAULT_MIN_RATE

        rate = self._latest_rate(brand, topic)
        result = {
            "task_id": tid, "brand": brand, "topic": topic,
            "last_rate": rate, "min_rate": min_rate, "triggered": False,
            "new_angle": None, "generated_id": None, "published": False,
            "status": "skipped",
        }

        # 无可见性数据:仍允许初次主动复盘(生成新角度内容),但标记为 no_data
        if rate is None:
            result["note"] = "暂无可见性快照,执行主动复盘"
        elif rate >= min_rate:
            result["note"] = f"提及率 {rate:.3f} 已达阈值 {min_rate},无需复盘"
            # 达阈值不触发复盘:仅更新最新提及率,不增加运行次数
            _touch_auto_review_task(tid, "ok", rate)
            return result

        # 触发复盘:换角度重生成
        result["triggered"] = True
        new_angle = self._next_angle(brand, topic, used_angle)
        result["new_angle"] = new_angle
        tone_hint = f"请采用【{new_angle}】这一全新角度切入,与已有内容形成差异,提升 AI 回答提及率"
        try:
            gen = ContentGenerator().generate(platform, brand, topic, tone_hint=tone_hint)
            result["generated_id"] = gen.get("db_id")
            update_auto_review_task_angle(tid, new_angle)
        except Exception as e:
            result["status"] = "gen_failed"
            result["error"] = str(e)[:200]
            update_auto_review_task_run(tid, "gen_failed", rate)
            return result

        # 可选:真实发布(复用 F7 已验证的 pipeline.run,skip_publish 取反)
        if publish:
            try:
                pipeline_run(brand, topic, [platform], skip_publish=False)
                # 判定发布结果:查最新发布记录
                from db import list_publish
                recs = list_publish(5)
                ok = any(r.get("status") == "success" and r.get("platform") == platform
                         for r in recs)
                result["published"] = ok
                result["publish_status"] = "success" if ok else "pending_or_failed"
            except Exception as e:
                result["status"] = "publish_failed"
                result["error"] = str(e)[:200]
                update_auto_review_task_run(tid, "publish_failed", rate)
                return result

        result["status"] = "ok"
        update_auto_review_task_run(tid, "ok" if not publish else "published", rate)
        return result

    # ---------- 后台自动循环 ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                for t in list_auto_review_tasks(100):
                    if t.get("enabled") and t.get("auto_loop"):
                        self.review_once(t, publish=True)
            except Exception:
                pass
            # 等待下一次轮询
            self._stop.wait(LOOP_INTERVAL)

    @staticmethod
    def run_now(tid: int, publish: bool = False) -> dict:
        t = get_auto_review_task(tid)
        if not t:
            return {"error": f"任务 {tid} 不存在"}
        return ReviewLoop().review_once(t, publish=publish)


if __name__ == "__main__":
    tasks = list_auto_review_tasks(10)
    print(f"auto_review_tasks: {len(tasks)}")
    for t in tasks:
        print(json.dumps(ReviewLoop().review_once(t), ensure_ascii=False))
