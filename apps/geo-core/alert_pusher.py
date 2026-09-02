# F12 告警推送闭环: 将告警推送到外部渠道(Webhook,兼容企业微信/飞书/Slack)
# 设计原则: 推送失败绝不致命(标记 pushed=-1 便于重试),不影响主链路与看板。
import json
import urllib.request
import urllib.error

import db
from config import ALERT_WEBHOOK_URL, ALERT_PUSH_ENABLED


class AlertPusher:
    def __init__(self, webhook_url: str = None):
        self.webhook_url = webhook_url or ALERT_WEBHOOK_URL

    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def _render(self, alert: dict) -> str:
        """把告警渲染成推送文本。"""
        level = (alert.get("level") or "warning").upper()
        scope = alert.get("scope") or "system"
        msg = alert.get("message") or ""
        return f"[{level}] ({scope}) {msg}"

    def push_alert(self, alert: dict) -> bool:
        """推送单条告警;成功返回 True 并标记 pushed=1,失败返回 False 标记 pushed=-1。"""
        aid = alert.get("id")
        if not self.enabled():
            # 未配置 webhook: 标记为"无需推送"(pushed=1,避免反复重试),不致命
            if aid:
                db.mark_alert_pushed(aid, ok=True)
            return False
        payload = {
            "msg_type": "text",
            "content": {"text": "[GEO 闭环看板告警]\n" + self._render(alert)},
        }
        try:
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                ok = resp.status == 200
            if aid:
                db.mark_alert_pushed(aid, ok=ok)
            return ok
        except Exception:
            if aid:
                db.mark_alert_pushed(aid, ok=False)
            return False

    def push_pending(self, limit: int = 50) -> dict:
        """推送所有待推送告警(未解决且未成功推送);返回 {pushed, failed, skipped}。"""
        pending = db.list_alerts_pending_push(limit)
        pushed = failed = skipped = 0
        for a in pending:
            if a.get("pushed") == -1:
                # 上次失败的也重试;但 fetch 已含未成功推送的。这里统一处理
                pass
            if a.get("pushed") == 1:
                skipped += 1
                continue
            if self.push_alert(a):
                pushed += 1
            else:
                if self.enabled():
                    failed += 1
                else:
                    skipped += 1  # 未配置 webhook,视为无需推送
        return {"pushed": pushed, "failed": failed, "skipped": skipped, "total": len(pending)}
