# 监控端客户端:整合层调用 Goodie 监控端 REST API
# 真实接口(已核对 backend/routes):
#   POST /api/users/login         {username,password} -> {data:{token,user}}
#   POST /api/geo-projects         {name,primary_keywords,platforms:["deepseek"],...}
#   POST /api/detection/create     {question,brand,brand_keywords,platforms:["deepseek"]}
#   GET  /api/geo-projects/:id/dashboard
# 监测平台仅支持 ["doubao","deepseek"];本系统用 deepseek(已配 agnes 网关)
import time
import json
import os
import requests
from config import MONITOR_BASE, PUBLISHER_ADMIN, PUBLISHER_PASSWORD

TOKEN_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token_cache.json")


class MonitorClient:
    def __init__(self, base: str = MONITOR_BASE, username: str = PUBLISHER_ADMIN, password: str = PUBLISHER_PASSWORD):
        self.base = base
        self.username = username
        self.password = password
        self.token = None

    def _load_cached_token(self):
        """复用未过期的登录 token,避免触发监控端 15min/5次的登录限流(生产行为)。"""
        try:
            if not os.path.exists(TOKEN_CACHE):
                return None
            with open(TOKEN_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            exp = data.get("expires_at", 0)
            if time.time() < exp and data.get("token"):
                return data["token"]
        except Exception:
            return None
        return None

    def _save_token(self, token):
        try:
            with open(TOKEN_CACHE, "w", encoding="utf-8") as f:
                json.dump({"token": token, "expires_at": time.time() + 23 * 3600}, f)
        except Exception:
            pass

    def login(self, retries: int = 6, force: bool = False):
        # 优先复用缓存 token(未过期),规避登录 429 限流
        if not force:
            cached = self._load_cached_token()
            if cached:
                self.token = cached
                return {"username": self.username, "role": "admin", "cached": True}
        # 指数退避: 3,6,12,24,48,48 秒(累计约 141s),应对监控端登录 429 限流
        backoff = 3
        last = None
        for i in range(retries):
            try:
                r = requests.post(f"{self.base}/users/login", json={"username": self.username, "password": self.password}, timeout=15)
                if r.status_code == 429:
                    time.sleep(backoff * (2 ** i))
                    last = "429 限流,退避重试"
                    continue
                r.raise_for_status()
                data = r.json()
                if not data.get("success"):
                    raise RuntimeError(f"监控端登录失败: {data.get('message')}")
                self.token = data["data"]["token"]
                self._save_token(self.token)
                return data["data"]["user"]
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    time.sleep(backoff * (2 ** i))
                    last = "429 限流,退避重试"
                    continue
                raise
        raise RuntimeError(f"监控端登录失败(限流): {last}")

    def _headers(self):
        if not self.token:
            self.login()
        return {"Authorization": f"Bearer {self.token}"}

    def create_project(self, name: str, keywords: list, platforms: list = None) -> dict:
        platforms = platforms or ["deepseek"]
        # 校验合法平台(监控端仅接受 doubao/deepseek)
        platforms = [p for p in platforms if p in ("doubao", "deepseek")] or ["deepseek"]
        # 幂等: 若同名项目已存在则复用,避免 409 冲突(验收/重复运行友好)
        for p in self.get_projects():
            if p.get("name") == name:
                return p
        r = requests.post(f"{self.base}/geo-projects", json={
            "name": name,
            "primary_keywords": keywords,
            "platforms": platforms,
            "monitoring_enabled": True,
            "monitoring_time": "09:00",
        }, headers=self._headers(), timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"创建项目失败: {data.get('message')}")
        return data["data"]

    def detect(self, question: str, brand: str, brand_keywords: list, platforms: list = None, project_id: int = None) -> dict:
        platforms = platforms or ["deepseek"]
        platforms = [p for p in platforms if p in ("doubao", "deepseek")] or ["deepseek"]
        payload = {
            "question": question,
            "brand": brand,
            "brand_keywords": brand_keywords,
            "platforms": platforms,
        }
        if project_id:
            payload["project_id"] = project_id
        r = requests.post(f"{self.base}/detection/create", json=payload, headers=self._headers(), timeout=60)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"触发检测失败: {data.get('message')}")
        # 监控端返回 {results:[{record_id,platform,status}]}(数组)
        results = data["data"].get("results", []) if isinstance(data.get("data"), dict) else []
        if not results:
            raise RuntimeError("检测未返回记录")
        first = results[0]
        return {
            "record_id": first.get("record_id"),
            "platform": first.get("platform"),
            "status": first.get("status"),
        }

    def detection_status(self, record_id: int) -> dict:
        r = requests.get(f"{self.base}/detection/status/{record_id}", headers=self._headers(), timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"查询检测状态失败: {data.get('message')}")
        return data["data"]

    def get_projects(self) -> list:
        r = requests.get(f"{self.base}/geo-projects", headers=self._headers(), timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return []
        return data.get("data", {}).get("projects", data.get("data", [])) if isinstance(data.get("data"), dict) else data.get("data", [])

    def dashboard(self, project_id: int, days: int = 30) -> dict:
        r = requests.get(f"{self.base}/geo-projects/{project_id}/dashboard", params={"days": days},
                         headers=self._headers(), timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"获取看板失败: {data.get('message')}")
        return data["data"]


if __name__ == "__main__":
    m = MonitorClient()
    u = m.login()
    print("login:", u["role"])
    proj = m.create_project("测试品牌X", ["量子计算", "云服务"])
    print("project id:", proj["id"])
    det = m.detect("请介绍量子计算云服务领域的代表品牌", "测试品牌X", ["量子计算", "云服务"])
    print("detection:", det)
