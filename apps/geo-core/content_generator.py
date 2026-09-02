# 内容生成器:基于 LLMClient 按平台调性生成可发布的图文内容,落库 + 重试 + 校验
import json
import re
import time
from llm_client import LLMClient
from config import PLATFORM_TONE
from db import insert_generated

MAX_LEN = 800
MIN_LEN = 100
RETRY = 2


class ContentGenerator:
    def __init__(self, client: LLMClient = None):
        self.client = client or LLMClient()

    def generate(self, platform: str, brand: str, topic: str, model: str = None,
                 tone_hint: str = None) -> dict:
        """生成单平台内容,返回 {platform,title,body,tags,model,ok,error}。
        tone_hint: 可选的角度/风格追加提示(如'采用【选购指南】角度'),用于换角度复盘。"""
        tone = PLATFORM_TONE.get(platform, "通用风格,简洁有条理,300-500字")
        system = ("你是专业的 GEO(生成式引擎优化)内容运营。请为品牌创作能在"
                  "AI 搜索中被引用、对用户有用的高质量内容。严格按照 JSON 输出。")
        angle_note = f"\n角度要求:{tone_hint}\n" if tone_hint else ""
        user = (f"品牌:{brand}\n话题:{topic}\n平台调性:{tone}{angle_note}\n\n"
                f"请输出 JSON,字段:title(标题,含平台风格,不超过20字)、"
                f"body(正文,纯文本不要markdown代码块,100-800字)、tags(3-5个标签,逗号分隔)。"
                f"内容要自然融入品牌名'{brand}',强调其差异化价值,避免硬广感。")
        last_err = None
        for attempt in range(RETRY + 1):
            try:
                raw = self.client.chat(system, user, max_tokens=1200, temperature=0.85)
                parsed = self._parse(raw)
                if not self._valid(parsed, brand):
                    last_err = "生成内容校验未通过(空字段/品牌未出现/超长)"
                    time.sleep(1)
                    continue
                parsed["platform"] = platform
                parsed["model"] = model or self.client.model
                parsed["ok"] = True
                parsed["error"] = None
                # 落库
                parsed["db_id"] = insert_generated(
                    brand, topic, platform, parsed["title"], parsed["body"], parsed["tags"], parsed["model"])
                return parsed
            except Exception as e:
                last_err = str(e)
                time.sleep(1)
        return {"platform": platform, "ok": False, "error": last_err,
                "title": "", "body": "", "tags": ""}

    @staticmethod
    def _valid(c: dict, brand: str) -> bool:
        if not c.get("title") or not c.get("body"):
            return False
        if not (MIN_LEN <= len(c["body"]) <= MAX_LEN):
            return False
        if brand and brand not in c["body"]:
            return False
        return True

    def generate_video_script(self, platform: str, brand: str, topic: str,
                              duration: int = 60, model: str = None) -> dict:
        """F14: 生成短视频脚本(口播稿+分镜),落库 content_type='video'。
        返回 {platform,title,body(口播+分镜),tags,model,script,ok,error}"""
        tone = PLATFORM_TONE.get(platform, "通用风格,节奏明快")
        system = ("你是 GEO(生成式引擎优化)短视频脚本编剧。请基于品牌与话题,"
                  "创作一个能在 AI 搜索/短视频平台被推荐的口播脚本,自然融入品牌,"
                  "严格 JSON 输出。")
        user = (
            f"品牌:{brand}\n话题:{topic}\n平台调性:{tone}\n目标时长:{duration}秒\n\n"
            "请输出 JSON,字段:\n"
            "title(短视频标题,不超过18字)、\n"
            "hook(开场钩子,1句话抓注意力)、\n"
            "voiceover(完整口播稿,纯文本,自然融入品牌名'"+brand+"',200-400字)、\n"
            "shots(分镜数组,3-4个,每幕 {time:时间点,visual:画面描述,line:该幕口播})、\n"
            "tags(3-5个标签,逗号分隔)。\n"
            "注意: 必须输出完整闭合的 JSON, shots 数组要写完整, 不要截断。"
            "脚本要突出品牌差异化价值,节奏紧凑,适合口播。"
        )
        last_err = None
        for attempt in range(RETRY + 1):
            try:
                # 重试时把上一次错误反馈给模型, 引导补完截断/品牌缺失
                prompt = user
                if attempt > 0 and last_err:
                    prompt = (user + f"\n\n[上一次生成未通过校验: {last_err}]"
                                      f"\n请务必输出完整闭合 JSON, 且品牌名'{brand}'要出现在口播稿或分镜中。")
                raw = self.client.chat(system, prompt, max_tokens=2500, temperature=0.8)
                parsed = self._parse_video(raw)
                if not parsed.get("title") or not parsed.get("voiceover"):
                    last_err = "视频脚本校验未通过(缺标题或口播稿)"
                    time.sleep(1)
                    continue
                # 品牌校验放宽: 出现在 口播稿/标题/分镜任一即可(模型常把品牌写进标题或分镜)
                brand_hit = (
                    (brand and brand in parsed["voiceover"])
                    or (brand and brand in parsed.get("title", ""))
                    or (brand and any(brand in str(s) for s in parsed.get("shots", []) if isinstance(s, dict)))
                    or (brand and len(brand) >= 2 and brand[:2] in parsed["voiceover"])  # 允许品牌核心词部分匹配
                )
                if brand and not brand_hit:
                    last_err = "品牌未在脚本中出现(口播/标题/分镜)"
                    time.sleep(1)
                    continue
                # shots 缺失容错: 解析已保证为 list, 空时给占位提示而非整体失败
                if not parsed.get("shots"):
                    parsed["shots"] = [{"time": "0:00", "visual": "品牌主视觉", "line": parsed["voiceover"][:40]}]
                # 组合可读正文(口播+分镜), 便于落库/展示
                body = self._compose_video_body(parsed)
                parsed["body"] = body
                parsed["platform"] = platform
                parsed["model"] = model or self.client.model
                parsed["ok"] = True
                parsed["error"] = None
                parsed["db_id"] = insert_generated(
                    brand, topic, platform, parsed["title"], body, parsed["tags"],
                    parsed["model"], content_type="video")
                return parsed
            except Exception as e:
                last_err = str(e)
                time.sleep(1)
        return {"platform": platform, "ok": False, "error": last_err,
                "title": "", "body": "", "tags": "", "script": None}

    @staticmethod
    def _parse_video(raw: str) -> dict:
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.M)
        try:
            d = json.loads(raw)
        except Exception:
            # 截断/非法 JSON 容错: 用正则尽力从原文提取各字段
            def grab(key):
                m = re.search(rf'"{key}"\s*:\s*"(.*?)(?:"\s*[,\}}]|$)', raw, re.S)
                return m.group(1).strip() if m else ""
            # 尽力提取 shots 数组中的对象(截断时可能不完整, 只收完整 {...})
            shots = []
            for sm in re.finditer(r'\{\s*"time"\s*:\s*"([^"]*)"\s*,\s*"visual"\s*:\s*"([^"]*)"\s*,\s*"line"\s*:\s*"([^"]*)"\s*\}', raw, re.S):
                shots.append({"time": sm.group(1), "visual": sm.group(2), "line": sm.group(3)})
            d = {
                "title": grab("title"),
                "hook": grab("hook"),
                "voiceover": grab("voiceover"),
                "shots": shots,
                "tags": grab("tags"),
            }
        shots = d.get("shots", []) or []
        return {
            "title": str(d.get("title", "")).strip(),
            "hook": str(d.get("hook", "")).strip(),
            "voiceover": str(d.get("voiceover", "")).strip(),
            "shots": shots,
            "tags": str(d.get("tags", "")).strip(),
        }

    @staticmethod
    def _compose_video_body(p: dict) -> str:
        lines = [f"【{p.get('title','')}】", ""]
        if p.get("hook"):
            lines.append(f"开场钩子: {p['hook']}")
            lines.append("")
        lines.append("口播稿:")
        lines.append(p.get("voiceover", ""))
        lines.append("")
        lines.append("分镜:")
        for i, s in enumerate(p.get("shots", []), 1):
            t = s.get("time", "") if isinstance(s, dict) else ""
            v = s.get("visual", "") if isinstance(s, dict) else ""
            l = s.get("line", "") if isinstance(s, dict) else ""
            lines.append(f"  {i}. [{t}] {v} — {l}")
        return "\n".join(lines)

    @staticmethod
    def _parse(raw: str) -> dict:
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.M)
        try:
            d = json.loads(raw)
            return {"title": str(d.get("title", "")).strip(),
                    "body": str(d.get("body", "")).strip(),
                    "tags": str(d.get("tags", "")).strip()}
        except Exception:
            title = body = tags = ""
            for line in raw.splitlines():
                if line.startswith("title"): title = line.split(":", 1)[-1].strip()
                elif line.startswith("body"): body = line.split(":", 1)[-1].strip()
                elif line.startswith("tags"): tags = line.split(":", 1)[-1].strip()
            return {"title": title, "body": body, "tags": tags}

    def generate_multi(self, platforms: list, brand: str, topic: str) -> list:
        return [self.generate(p, brand, topic) for p in platforms]
