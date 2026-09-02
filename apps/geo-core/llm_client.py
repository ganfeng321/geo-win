# LLMClient:统一 AI 生成接口(开发规则 §5)
# 当前实现:用户自有 OpenAI 兼容 API (agnes-ai)
# 后续接其他家只需新增一个 _call_xxx 分支或新实现类
import requests
from config import AGNES_BASE_URL, AGNES_API_KEY, AGNES_MODEL


class LLMClient:
    def __init__(self, base_url=AGNES_BASE_URL, api_key=AGNES_API_KEY, model=AGNES_MODEL):
        if not api_key:
            raise RuntimeError("AGNES_API_KEY 未配置,请在 apps/geo-core/.env 设置")
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 1200, temperature: float = 0.8) -> str:
        """标准 OpenAI chat/completions 调用"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        resp = requests.post(self.base_url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


if __name__ == "__main__":
    # 自测
    c = LLMClient()
    print(c.chat("你是中文内容助手", "用一句话介绍Geo优化"))
