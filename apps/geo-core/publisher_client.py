# 发布调度器:调用 MPP 发布端 REST API,带账号校验 + 落库
# 真实接口(已核对 sau_backend.py / multiFileUploader.py):
#   GET  /getPlatformStats -> {data:{platform_stats:[{platform,valid,...}]}}
#   POST /postVideosToMultiplePlatforms -> {code:200, msg:"发布任务已完成", data:{<platform_type>:{success,total}}}
# 注意:
#   - MPP 是"文件驱动"的: files 为空时不执行任何发布(静默跳过)。
#     故整合层对图文(fileType=1)自动将 text 写入临时文件放入发布端 videoFile/ 目录。
#   - accountFiles 必须传具体 Cookie 文件名(从 user_info 查询),空列表也会跳过。
#   - 发布端返回 data 的 key 是平台数字 type(如 "9"),值含 success/total。
import sys
import os
import uuid
import time
import sqlite3
import requests
from config import PUBLISHER_BASE
from db import insert_publish

# 稳固化: 真实发布前服务存活检查 + 杀残留 Chromium,避免 180s 超时
try:
    from proc_utils import pre_publish_cleanup
except Exception:
    pre_publish_cleanup = None

PUB_VIDEO_DIR = r"d:\GEO-XINXIANGMU-00\packages\geo-publisher\sau_backend\videoFile"
PUB_DB_PATH = r"d:\GEO-XINXIANGMU-00\packages\geo-publisher\sau_backend\db\database.db"

# Cookie 过期阈值(天): 超过则判定可能失效,发布前预警(不静默)
COOKIE_MAX_AGE_DAYS = 7

# 发布端 /getPlatformStats 返回 platform 为数字 type(如 9=百家号)
PLATFORM_CODE_MAP = {
    "xiaohongshu": 1,
    "shipinhao": 2,
    "douyin": 3,
    "kuaishou": 4,
    "tiktok": 5,
    "instagram": 6,
    "facebook": 7,
    "bilibili": 8,
    "baijiahao": 9,
}

# 发布失败结构化分类(便于 dashboard 展示与自动复盘区分)
ERROR_TYPES = {
    "unknown_platform": "未知平台",
    "no_account": "未录入账号 Cookie",
    "cookie_expired": "Cookie 可能已过期",
    "publish_failed": "发布端执行失败(反爬/元素未找到)",
    "timeout": "发布端响应超时",
    "exception": "调用发布端异常",
}


class PublisherClient:
    def __init__(self, base: str = PUBLISHER_BASE):
        self.base = base

    def get_platform_stats(self) -> dict:
        r = requests.get(f"{self.base}/getPlatformStats", timeout=10)
        r.raise_for_status()
        return r.json()

    def _account_files(self, platform):
        """返回该平台的 Cookie 文件名列表(从发布端 user_info 查询)。
        发布端 postVideosToMultiplePlatforms 需要 accountFiles 里传具体文件名,
        空列表会导致跳过发布(不报错也不执行)。
        """
        try:
            conn = sqlite3.connect(PUB_DB_PATH)
            rows = conn.execute(
                "SELECT filePath FROM user_info WHERE type=? AND status=1", (platform,)
            ).fetchall()
            conn.close()
            return [r[0] for r in rows if r[0]]
        except Exception:
            return []

    def _cookie_age_days(self, fname):
        """查 Cookie 文件 mtime,返回距今天数(文件不存在返回 None)。"""
        if not fname:
            return None
        base_dir = os.path.dirname(PUB_DB_PATH)
        candidates = [fname, os.path.join(base_dir, fname), os.path.join(base_dir, "..", fname)]
        for c in candidates:
            try:
                if os.path.exists(c):
                    return (time.time() - os.path.getmtime(c)) / 86400.0
            except Exception:
                continue
        return None

    def check_account(self, platform: str) -> dict:
        """发布前账号可用性探针。返回 {platform, code, files, age_days, ok, error_type, need_login, detail}。"""
        code = PLATFORM_CODE_MAP.get(platform)
        if not code:
            return {"platform": platform, "code": None, "ok": False,
                    "error_type": "unknown_platform", "need_login": False,
                    "detail": f"未知平台: {platform}"}
        files = self._account_files(code)
        if not files:
            return {"platform": platform, "code": code, "files": [], "ok": False,
                    "error_type": "no_account", "need_login": True,
                    "detail": f"平台 {platform}(type={code}) 未录入账号 Cookie,无法发布"}
        ages = [a for a in (self._cookie_age_days(f) for f in files) if a is not None]
        max_age = max(ages) if ages else None
        if max_age is not None and max_age > COOKIE_MAX_AGE_DAYS:
            return {"platform": platform, "code": code, "files": files, "age_days": max_age,
                    "ok": True, "error_type": "cookie_expired", "need_login": False,
                    "detail": f"Cookie 已 {max_age:.1f} 天未更新(> {COOKIE_MAX_AGE_DAYS} 天),可能失效,建议重新登录"}
        return {"platform": platform, "code": code, "files": files, "age_days": max_age,
                "ok": True, "error_type": None, "need_login": False, "detail": "账号可用"}

    def publish(self, platform: str, title: str, text: str, tags: str = "", file_type: int = 1,
                skip_cleanup: bool = False) -> dict:
        """
        发布单平台单篇(加固版)。
        流程: 发布前自检(服务存活+杀残留 Chromium) -> 账号探针 -> 图文写临时文件 ->
              调发布端 API(超时分级) -> 结果判定(结构化 error_type) -> 落库。
        返回 {platform, status, error, error_type, account, record_id, need_login}
        """
        # 1) 发布前自检: 服务存活 + 杀残留 Chromium,避免 180s 超时
        if not skip_cleanup and pre_publish_cleanup:
            try:
                pre_publish_cleanup(verbose=False)
            except Exception:
                pass

        # 2) 账号探针(含未知平台/无账号/Cookie 过期)
        acct = self.check_account(platform)
        if not acct["ok"]:
            return self._fail(platform, acct.get("code"), acct["detail"],
                              acct["error_type"], need_login=acct.get("need_login", False))
        if acct["error_type"] == "cookie_expired":
            print(f"[WARN] {acct['detail']}", file=sys.stderr)

        code = acct["code"]
        files = acct["files"]

        # 3) MPP 文件驱动: 图文模式自动生成占位 PNG
        files_list = []
        if file_type == 1 and text:
            os.makedirs(PUB_VIDEO_DIR, exist_ok=True)
            fid = str(uuid.uuid4())[:8]
            safe_title = "".join(c for c in title[:30] if c.isalnum() or c in (" ", "_", "-"))
            fname = f"{fid}_{safe_title}.png"
            fpath = os.path.join(PUB_VIDEO_DIR, fname)
            try:
                from PIL import Image, ImageDraw, ImageFont
                img = Image.new("RGB", (800, 450), "#1a1d2e")
                d = ImageDraw.Draw(img)
                d.text((40, 40), title[:50], fill="#7cc4ff")
                d.text((40, 80), text[:200], fill="#e6e6e6")
                img.save(fpath, "PNG")
            except Exception:
                fname = f"{fid}_{safe_title}.txt"
                fpath = os.path.join(PUB_VIDEO_DIR, fname)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(text)
            files_list.append(fname)

        payload = {
            "platforms": [platform],  # 发布端用 get_type_by_platform_key(key) 查类型,需传英文名非数字
            "accountFiles": {platform: files},
            "fileType": file_type,
            "files": files_list,
            "title": title,
            "text": text,
            # 发布端 baseFileUploader 对 tags 做 enumerate -> 必须是 list,
            # 传字符串会被逐字符拆成 N 个标签(超出平台上限导致提交失败)
            "tags": [t.strip() for t in tags.split(",") if t.strip()][:10],
            "thumbnail": "",
            "location": 1,
            "enableTimer": 0,
            "videosPerDay": 1,
            "dailyTimes": [],
            "startDays": 0,
        }
        try:
            # 4) 图文同步阻塞约 40-60s,设 120s 超时(分级,避免 180s 长耗)
            r = requests.post(f"{self.base}/postVideosToMultiplePlatforms", json=payload, timeout=120)
            r.raise_for_status()
            data = r.json()
            plat_data = data.get("data", {}).get(platform, {})
            if not plat_data:
                plat_data = data.get("data", {}).get(str(code), {})
            success_count = plat_data.get("success", 0)
            total_count = plat_data.get("total", 0)
            print(f"[DEBUG] 发布端返回: code={data.get('code')} data[{code}]={{success:{success_count},total:{total_count}}}", file=sys.stderr)

            if data.get("code") == 200 and success_count >= 1:
                return self._ok(platform, code, data)
            if total_count > 0 and success_count == 0:
                return self._fail(platform, code, f"发布端执行了{total_count}个任务但全部失败(查看发布端日志)", "publish_failed")
            msg = data.get("msg") or str(data)[:200]
            return self._fail(platform, code, f"发布端返回未成功: {msg}", "publish_failed")
        except requests.exceptions.Timeout:
            return self._fail(platform, code, f"发布端 {self.base} 响应超时(>120s)", "timeout")
        except Exception as e:
            return self._fail(platform, code, f"调用发布端异常: {e}", "exception")

    def _ok(self, platform, account, raw):
        rec = insert_publish(None, platform, account, "success", error_type=None)
        return {"platform": platform, "account": account, "status": "success",
                "error": None, "error_type": None, "need_login": False, "record_id": rec, "raw": raw}

    def _fail(self, platform, account, err, error_type="exception", need_login=False):
        rec = insert_publish(None, platform, account, "failed", err, error_type)
        return {"platform": platform, "account": account, "status": "failed",
                "error": err, "error_type": error_type, "need_login": need_login, "record_id": rec}
