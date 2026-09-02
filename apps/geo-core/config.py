# GEO 自用品 · 整合层配置
# 所有密钥走环境变量/本地 .env,禁止硬编码真实 Key
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 用户自有 OpenAI 兼容 API (agnes-ai)
AGNES_BASE_URL = os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1/chat/completions")
AGNES_API_KEY = os.getenv("AGNES_API_KEY", "")  # 真值在 .env(不入库)
AGNES_MODEL = os.getenv("AGNES_MODEL", "agnes-2.5-flash")

# 监控端 / 发布端 / 整合层地址
MONITOR_BASE = os.getenv("MONITOR_BASE", "http://localhost:3002/api")
PUBLISHER_BASE = os.getenv("PUBLISHER_BASE", "http://localhost:5409")
CORE_BASE = os.getenv("CORE_BASE", "http://localhost:7000")

# 发布端管理员凭据(本地自用,默认弱口令,请自行修改)
PUBLISHER_ADMIN = os.getenv("PUBLISHER_ADMIN", "admin")
PUBLISHER_PASSWORD = os.getenv("PUBLISHER_PASSWORD", "Admin@123456")

# F12 告警推送闭环: 告警外部推送渠道(企业微信/飞书/Slack 兼容的 Webhook)
# 留空则不推送(仅入库+后台展示,不致命);CI/本地不强制配置
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")
ALERT_PUSH_ENABLED = bool(ALERT_WEBHOOK_URL)

# 平台调性模板:不同平台生成不同语气/长度/格式的内容
PLATFORM_TONE = {
    "xiaohongshu": "小红书风格:口语化、带emoji、有痛点共鸣、结尾引导互动,300-500字",
    "douyin": "抖音风格:短平快、抓眼球开头、强情绪、适合口播文案,200-400字",
    "kuaishou": "快手风格:接地气、老铁语气、真实感,200-400字",
    "bilibili": "B站风格:信息密度高、有梗、分段清晰,400-800字",
    "baijiahao": "百家号风格:偏资讯/干货、结构严谨、适合SEO,500-800字",
    "shipinhao": "视频号风格:克制专业、价值导向,200-400字",
}
