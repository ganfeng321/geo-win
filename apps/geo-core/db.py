# 整合层数据库(自研 SQLite):生成/发布/流水线记录
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "geo_core.db"
SCHEMA = """
CREATE TABLE IF NOT EXISTS generated_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    topic TEXT,
    platform TEXT NOT NULL,
    title TEXT,
    body TEXT,
    tags TEXT,
    model TEXT,
    content_type TEXT DEFAULT 'article',
    status TEXT DEFAULT 'generated',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS publish_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_content_id INTEGER,
    platform TEXT NOT NULL,
    account TEXT,
    status TEXT,
    error TEXT,
    published_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT,
    topic TEXT,
    platforms TEXT,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME,
    result_summary TEXT
);
CREATE TABLE IF NOT EXISTS visibility_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    brand TEXT NOT NULL,
    trigger TEXT NOT NULL,
    before_mention_rate REAL,
    after_mention_rate REAL,
    mention_rate_delta REAL,
    before_visibility_score REAL,
    after_visibility_score REAL,
    visibility_score_delta REAL,
    publish_count_before INTEGER DEFAULT 0,
    publish_count_after INTEGER DEFAULT 0,
    detection_record_id INTEGER,
    captured_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT DEFAULT 'warning',
    scope TEXT,
    message TEXT NOT NULL,
    metric TEXT,
    value REAL,
    threshold REAL,
    resolved INTEGER DEFAULT 0,
    pushed INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT,
    summary TEXT,
    opportunities TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS monitor_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    brand TEXT NOT NULL,
    keywords TEXT,
    platforms TEXT DEFAULT 'doubao,deepseek',
    remote_project_id INTEGER,
    last_run_at DATETIME,
    last_status TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS publish_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    topic TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'xiaohongshu',
    cron_hour INTEGER NOT NULL DEFAULT 9,
    cron_minute INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    last_run_at DATETIME,
    last_status TEXT,
    next_run_at DATETIME,
    run_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS auto_review_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brand TEXT NOT NULL,
    topic TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'xiaohongshu',
    angle TEXT NOT NULL DEFAULT '通用科普',
    min_mention_rate REAL NOT NULL DEFAULT 0.15,
    enabled INTEGER DEFAULT 1,
    auto_loop INTEGER DEFAULT 0,
    last_run_at DATETIME,
    last_status TEXT,
    last_rate REAL,
    run_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init():
    conn = get_conn()
    conn.executescript(SCHEMA)
    # 为已存在的旧表补齐新增列(幂等,ALTER 仅在列缺失时执行)
    _ensure_columns(conn, "generated_content", {
        "content_type": "TEXT DEFAULT 'article'",
    })
    _ensure_columns(conn, "alerts", {
        "scope": "TEXT",
        "metric": "TEXT",
        "value": "REAL",
        "threshold": "REAL",
        "pushed": "INTEGER DEFAULT 0",
    })
    _ensure_columns(conn, "publish_records", {
        "error_type": "TEXT",
    })
    conn.commit()
    conn.close()


def _ensure_columns(conn, table, columns):
    existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col, dtype in columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")


def insert_generated(brand, topic, platform, title, body, tags, model, content_type="article"):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO generated_content (brand,topic,platform,title,body,tags,model,content_type,status) "
        "VALUES (?,?,?,?,?,?,?,?, 'generated')",
        (brand, topic, platform, title, body, tags, model, content_type))
    conn.commit()
    gid = cur.lastrowid
    conn.close()
    return gid


def insert_publish(generated_content_id, platform, account, status, error=None, error_type=None):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO publish_records (generated_content_id,platform,account,status,error,error_type) "
        "VALUES (?,?,?,?,?,?)",
        (generated_content_id, platform, account, status, error, error_type))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def count_generated():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM generated_content").fetchone()[0]
    conn.close()
    return n


def count_publish(status=None):
    conn = get_conn()
    if status:
        n = conn.execute("SELECT COUNT(*) FROM publish_records WHERE status=?", (status,)).fetchone()[0]
    else:
        n = conn.execute("SELECT COUNT(*) FROM publish_records").fetchone()[0]
    conn.close()
    return n


def list_generated(limit=50):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM generated_content ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_publish(limit=50):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM publish_records ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_visibility_snapshot(project_id, brand, trigger, before_rate, after_rate,
                                before_score, after_score, publish_before, publish_after,
                                detection_record_id=None):
    delta_rate = None if before_rate is None or after_rate is None else round(after_rate - before_rate, 6)
    delta_score = None if before_score is None or after_score is None else round(after_score - before_score, 6)
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO visibility_snapshots "
        "(project_id,brand,trigger,before_mention_rate,after_mention_rate,mention_rate_delta,"
        " before_visibility_score,after_visibility_score,visibility_score_delta,"
        " publish_count_before,publish_count_after,detection_record_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, brand, trigger, before_rate, after_rate, delta_rate,
         before_score, after_score, delta_score, publish_before, publish_after, detection_record_id))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def latest_visibility_snapshot(project_id=None):
    conn = get_conn()
    if project_id:
        row = conn.execute(
            "SELECT * FROM visibility_snapshots WHERE project_id=? ORDER BY id DESC LIMIT 1",
            (project_id,)).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM visibility_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def list_visibility_snapshots(limit=50):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM visibility_snapshots ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- 告警(F12) ----
# 默认阈值: 提及率 < 0.05 或可见性指数 < 30 视为告警
MENTION_RATE_THRESHOLD = 0.05
VISIBILITY_SCORE_THRESHOLD = 30.0


def insert_alert(level, message, scope=None, metric=None, value=None, threshold=None):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO alerts (level,scope,message,metric,value,threshold) "
        "VALUES (?,?,?,?,?,?)",
        (level, scope, message, metric, value, threshold))
    conn.commit()
    conn.close()
    return cur.lastrowid


def list_alerts(resolved=0, limit=50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM alerts WHERE resolved=? ORDER BY id DESC LIMIT ?",
        (resolved, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_visibility_alert(snapshot):
    """根据最新可见性快照判定是否需要告警,需要则落库并返回告警列表。"""
    if not snapshot:
        return []
    new_alerts = []
    ar = snapshot.get("after_mention_rate")
    av = snapshot.get("after_visibility_score")
    if ar is not None and ar < MENTION_RATE_THRESHOLD:
        msg = f"品牌【{snapshot.get('brand')}】AI 提及率 {ar:.3f} 低于阈值 {MENTION_RATE_THRESHOLD}"
        insert_alert("warning", msg, scope="visibility",
                     metric="mention_rate", value=ar, threshold=MENTION_RATE_THRESHOLD)
        new_alerts.append(msg)
    if av is not None and av < VISIBILITY_SCORE_THRESHOLD:
        msg = f"品牌【{snapshot.get('brand')}】合成可见性指数 {av:.2f} 低于阈值 {VISIBILITY_SCORE_THRESHOLD}"
        insert_alert("warning", msg, scope="visibility",
                     metric="visibility_score", value=av, threshold=VISIBILITY_SCORE_THRESHOLD)
        new_alerts.append(msg)
    return new_alerts


def mark_alert_pushed(aid, ok=True):
    """F12: 标记告警已推送(或推送失败 pushed=-1 便于重试区分)。"""
    conn = get_conn()
    val = 1 if ok else -1
    conn.execute("UPDATE alerts SET pushed=? WHERE id=?", (val, aid))
    conn.commit()
    conn.close()


def resolve_alert(aid):
    """F12: 标记告警已解决,关闭闭环。"""
    conn = get_conn()
    conn.execute("UPDATE alerts SET resolved=1 WHERE id=?", (aid,))
    conn.commit()
    conn.close()


def list_alerts_pending_push(limit=50):
    """F12: 待推送(未解决且未成功推送)的告警。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM alerts WHERE resolved=0 AND pushed<>1 ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- 机会洞察(F15) ----
def insert_insight(scope, summary, opportunities):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO insights (scope,summary,opportunities) VALUES (?,?,?)",
        (scope, summary, opportunities))
    conn.commit()
    conn.close()
    return cur.lastrowid


def list_insights(limit=20):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM insights ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- 监测项目管理(F3) ----
def upsert_monitor_project(name, brand, keywords, platforms="doubao,deepseek",
                           remote_project_id=None, last_status=None):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO monitor_projects (name,brand,keywords,platforms,remote_project_id,last_status) "
        "VALUES (?,?,?,?,?,?)",
        (name, brand, keywords, platforms, remote_project_id, last_status))
    conn.commit()
    conn.close()
    return cur.lastrowid


def list_monitor_projects(limit=100):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM monitor_projects ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_monitor_project_run(pid, status, remote_id=None):
    conn = get_conn()
    if remote_id:
        conn.execute(
            "UPDATE monitor_projects SET last_run_at=CURRENT_TIMESTAMP,last_status=?,remote_project_id=? WHERE id=?",
            (status, remote_id, pid))
    else:
        conn.execute(
            "UPDATE monitor_projects SET last_run_at=CURRENT_TIMESTAMP,last_status=? WHERE id=?",
            (status, pid))
    conn.commit()
    conn.close()


# ---------- 定时发布任务(publish_tasks) ----------
def insert_publish_task(brand, topic, platform="xiaohongshu", cron_hour=9, cron_minute=0, enabled=1):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO publish_tasks (brand,topic,platform,cron_hour,cron_minute,enabled) "
        "VALUES (?,?,?,?,?,?)",
        (brand, topic, platform, cron_hour, cron_minute, enabled))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def list_publish_tasks(limit=100):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM publish_tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_publish_task(tid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM publish_tasks WHERE id=?", (tid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_publish_task_run(tid, status):
    conn = get_conn()
    conn.execute(
        "UPDATE publish_tasks SET last_run_at=CURRENT_TIMESTAMP,last_status=?,run_count=run_count+1 WHERE id=?",
        (status, tid))
    conn.commit()
    conn.close()


def compute_next_run_at(task):
    """计算下一次应运行时间(当天或次日 cron_hour:cron_minute)。"""
    import datetime
    now = datetime.datetime.now()
    cand = now.replace(hour=task["cron_hour"], minute=task["cron_minute"], second=0, microsecond=0)
    if cand <= now:
        cand += datetime.timedelta(days=1)
    return cand.strftime("%Y-%m-%d %H:%M")


def delete_publish_task(tid):
    conn = get_conn()
    conn.execute("DELETE FROM publish_tasks WHERE id=?", (tid,))
    conn.commit()
    conn.close()


# ---------- 闭环自动复盘任务(auto_review_tasks, F20) ----------
def insert_auto_review_task(brand, topic, platform="xiaohongshu", angle="通用科普",
                            min_mention_rate=0.15, enabled=1, auto_loop=0):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO auto_review_tasks "
        "(brand,topic,platform,angle,min_mention_rate,enabled,auto_loop) "
        "VALUES (?,?,?,?,?,?,?)",
        (brand, topic, platform, angle, min_mention_rate, enabled, auto_loop))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def list_auto_review_tasks(limit=100):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM auto_review_tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_auto_review_task(tid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM auto_review_tasks WHERE id=?", (tid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_auto_review_task_run(tid, status, rate=None):
    conn = get_conn()
    if rate is not None:
        conn.execute(
            "UPDATE auto_review_tasks SET last_run_at=CURRENT_TIMESTAMP,last_status=?,"
            "last_rate=?,run_count=run_count+1 WHERE id=?",
            (status, rate, tid))
    else:
        conn.execute(
            "UPDATE auto_review_tasks SET last_run_at=CURRENT_TIMESTAMP,last_status=?,"
            "run_count=run_count+1 WHERE id=?",
            (status, tid))
    conn.commit()
    conn.close()


def update_auto_review_task_angle(tid, angle):
    conn = get_conn()
    conn.execute("UPDATE auto_review_tasks SET angle=? WHERE id=?", (angle, tid))
    conn.commit()
    conn.close()


def set_auto_review_task_enabled(tid, enabled):
    conn = get_conn()
    conn.execute("UPDATE auto_review_tasks SET enabled=? WHERE id=?", (int(enabled), tid))
    conn.commit()
    conn.close()


def set_auto_review_task_loop(tid, auto_loop):
    conn = get_conn()
    conn.execute("UPDATE auto_review_tasks SET auto_loop=? WHERE id=?", (int(auto_loop), tid))
    conn.commit()
    conn.close()


def delete_auto_review_task(tid):
    conn = get_conn()
    conn.execute("DELETE FROM auto_review_tasks WHERE id=?", (tid,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init()
    print("db initialized at", DB_PATH)
