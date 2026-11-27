from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
import sqlite3
from datetime import date, datetime, timedelta
import calendar
import html
import os
from urllib.parse import quote

app = FastAPI()


def make_tel_link(phone: str, label: str = None) -> str:
    """電話番号を安全な tel: リンクにする。"""
    phone = phone or ""
    tel_number = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    if not tel_number:
        return html.escape(label if label is not None else phone)
    shown = html.escape(label if label is not None else phone)
    return f'<a href="tel:{html.escape(tel_number, quote=True)}">{shown}</a>'
# =========================================================
# PWA（iPhone・Androidのホーム画面に追加）
# =========================================================

@app.get("/manifest.webmanifest")
def pwa_manifest():
    return JSONResponse({
        "name": "訪問看護システム",
        "short_name": "訪問看護",
        "description": "訪問予定・休暇申請管理",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f4f7fa",
        "theme_color": "#1677c8",
        "icons": [{"src": "/pwa-icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}]
    })

@app.get("/pwa-icon.svg")
def pwa_icon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="90" fill="#1677c8"/><path d="M80 245 256 95 432 245v175H305V300h-98v120H80z" fill="white"/><path d="M235 175h42v105h-42zM204 206h104v42H204z" fill="#1677c8"/></svg>'
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

@app.get("/service-worker.js")
def service_worker():
    # 個人情報を含む画面はキャッシュしない。オフライン時は案内だけ表示。
    js = """const CACHE_NAME = 'houmon-kango-static-v1';
self.addEventListener('install', (event) => { self.skipWaiting(); });
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((key) => key !== CACHE_NAME ? caches.delete(key) : Promise.resolve()));
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith(fetch(req).catch(() => {
    if (req.mode === 'navigate') return new Response(
      '<!doctype html><html lang=\\"ja\\"><meta charset=\\"utf-8\\"><meta name=\\"viewport\\" content=\\"width=device-width,initial-scale=1\\"><title>オフライン</title><body style=\\"font-family:sans-serif;padding:24px\\"><h2>インターネットに接続できません</h2><p>通信を復旧して、もう一度お試しください。</p></body></html>',
      { headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } }
    );
    return new Response('', { status: 503, statusText: 'Offline' });
  }));
});"""
    return Response(content=js, media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})

@app.middleware("http")
async def add_pwa_to_html(request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    html_text = body.decode("utf-8", errors="replace")
    head_addition = (
        '<link rel="manifest" href="/manifest.webmanifest">'
        '<meta name="theme-color" content="#1677c8">'
        '<meta name="apple-mobile-web-app-capable" content="yes">'
        '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
        '<meta name="apple-mobile-web-app-title" content="訪問看護">'
        '<link rel="apple-touch-icon" href="/pwa-icon.svg">'
    )
    script_addition = (
        '<script>if ("serviceWorker" in navigator) {'
        'window.addEventListener("load", function(){navigator.serviceWorker.register("/service-worker.js").catch(function(e){console.error("PWA service worker:",e);});});'
        '}</script>'
    )
    if "</head>" in html_text:
        html_text = html_text.replace("</head>", head_addition + "</head>", 1)
    if "</body>" in html_text:
        html_text = html_text.replace("</body>", script_addition + "</body>", 1)
    headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type", "content-encoding")}
    return HTMLResponse(content=html_text, status_code=response.status_code, headers=headers)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Renderでは環境変数 DATA_DIR を /var/data に設定する。
# ローカル実行時は従来どおり main.py と同じフォルダを使用する。
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
DB = os.path.join(DATA_DIR, "database.db")


# =========================================================
# データベース
# =========================================================

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table_name, column_name):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    columns = cur.fetchall()

    for column in columns:
        if column[1] == column_name:
            return True

    return False



def format_wareki(value):
    """ISO日付を和暦表示。保存値は西暦のまま保持する。"""
    if not value:
        return ""
    try:
        d = date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return str(value)
    eras = [
        (date(2019, 5, 1), "令和"),
        (date(1989, 1, 8), "平成"),
        (date(1926, 12, 25), "昭和"),
        (date(1912, 7, 30), "大正"),
        (date(1868, 1, 25), "明治"),
    ]
    for start, name in eras:
        if d >= start:
            year = d.year - start.year + 1
            year_text = "元" if year == 1 else str(year)
            return f"{name}{year_text}年{d.month}月{d.day}日"
    return f"{d.year}年{d.month}月{d.day}日"


def parse_birth_date(value):
    """西暦 yyyy-mm-dd または簡単な和暦入力をISO形式に変換。"""
    value = (value or "").strip()
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    import re
    m = re.fullmatch(r"(令和|平成|昭和|大正|明治)\s*(元|\d+)年\s*(\d{1,2})月\s*(\d{1,2})日?", value)
    if not m:
        return value
    era, y, mo, day = m.groups()
    base = {"令和": 2018, "平成": 1988, "昭和": 1925, "大正": 1911, "明治": 1867}[era]
    year = base + (1 if y == "元" else int(y))
    try:
        return date(year, int(mo), int(day)).isoformat()
    except ValueError:
        return value


def confirm_delete_form(action, label="削除"):
    return f"<form action='{action}' method='post' style='display:inline;' onsubmit=\"return confirm('本当に{label}しますか？この操作は取り消せません。');\"><button type='submit' class='danger'>{label}</button></form>"


def visit_conflict(conn, staff_id, visit_date, visit_time, end_time="", exclude_id=None):
    """同じスタッフの同日訪問について、時間帯の重なりを検出する。終了未入力は20分枠として扱う。"""
    try:
        start = datetime.strptime((visit_time or "")[:5], "%H:%M")
        end = datetime.strptime((end_time or "")[:5], "%H:%M") if end_time else start + timedelta(minutes=20)
    except ValueError:
        return "訪問時刻の形式が正しくありません。"
    if end <= start:
        return "終了時刻は開始時刻より後に設定してください。"
    sql = "SELECT id, visit_time, end_time, patient_name FROM visits WHERE staff_id = ? AND visit_date = ?"
    params = [staff_id, visit_date]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    cur = conn.cursor()
    cur.execute(sql, params)
    for row in cur.fetchall():
        try:
            other_start = datetime.strptime((row["visit_time"] or "")[:5], "%H:%M")
            other_end = datetime.strptime((row["end_time"] or "")[:5], "%H:%M") if row["end_time"] else other_start + timedelta(minutes=20)
        except ValueError:
            continue
        if start < other_end and other_start < end:
            return f"同じスタッフに訪問予定が重複しています（{row['visit_time']}〜{row['end_time'] or '20分枠'}：{row['patient_name']}）。時間または担当スタッフを変更してください。"
    return ""


def service_filter_sql(service_type):
    return "" if service_type in (None, "", "all") else " AND COALESCE(visits.service_type, '看護') = ?"


def init_db():

    conn = get_db()
    cur = conn.cursor()

    # -----------------------------------------------------
    # スタッフ
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            phone TEXT DEFAULT '',
            address TEXT DEFAULT '',
            role TEXT DEFAULT 'staff'
        )
    """)

    # 既存データベース対応
    if not column_exists(conn, "staff", "role"):
        cur.execute("ALTER TABLE staff ADD COLUMN role TEXT DEFAULT 'staff'")

    if not column_exists(conn, "staff", "phone"):
        cur.execute("""
            ALTER TABLE staff
            ADD COLUMN phone TEXT DEFAULT ''
        """)

    if not column_exists(conn, "staff", "address"):
        cur.execute("""
            ALTER TABLE staff
            ADD COLUMN address TEXT DEFAULT ''
        """)

    if not column_exists(conn, "staff", "calendar_color"):
        cur.execute("ALTER TABLE staff ADD COLUMN calendar_color TEXT DEFAULT '#2563eb'")

    if not column_exists(conn, "staff", "furigana"):
        cur.execute("ALTER TABLE staff ADD COLUMN furigana TEXT DEFAULT ''")

    if not column_exists(conn, "staff", "staff_number"):
        cur.execute("ALTER TABLE staff ADD COLUMN staff_number INTEGER")

    if not column_exists(conn, "staff", "show_in_schedule"):
        cur.execute("ALTER TABLE staff ADD COLUMN show_in_schedule INTEGER DEFAULT 1")

    # -----------------------------------------------------
    # 利用者
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            address TEXT DEFAULT '',
            birth_date TEXT DEFAULT '',
            memo TEXT DEFAULT ''
        )
    """)

    if not column_exists(conn, "clients", "furigana"):
        cur.execute("ALTER TABLE clients ADD COLUMN furigana TEXT DEFAULT ''")

    # 同時登録などでアプリ側チェックをすり抜けても、DBトリガーで同名・同生年月日の登録を拒否
    cur.execute("DROP TRIGGER IF EXISTS prevent_duplicate_client_insert")
    cur.execute("""
        CREATE TRIGGER prevent_duplicate_client_insert
        BEFORE INSERT ON clients
        WHEN COALESCE(NEW.birth_date, '') != '' AND EXISTS (
            SELECT 1 FROM clients c
            WHERE c.birth_date = NEW.birth_date
              AND lower(replace(replace(trim(c.name), ' ', ''), '　', '')) =
                  lower(replace(replace(trim(NEW.name), ' ', ''), '　', ''))
        )
        BEGIN
            SELECT RAISE(ABORT, 'duplicate client name and birth_date');
        END
    """)
    cur.execute("DROP TRIGGER IF EXISTS prevent_duplicate_client_update")
    cur.execute("""
        CREATE TRIGGER prevent_duplicate_client_update
        BEFORE UPDATE OF name, birth_date ON clients
        WHEN COALESCE(NEW.birth_date, '') != '' AND EXISTS (
            SELECT 1 FROM clients c
            WHERE c.id != NEW.id AND c.birth_date = NEW.birth_date
              AND lower(replace(replace(trim(c.name), ' ', ''), '　', '')) =
                  lower(replace(replace(trim(NEW.name), ' ', ''), '　', ''))
        )
        BEGIN
            SELECT RAISE(ABORT, 'duplicate client name and birth_date');
        END
    """)

    # -----------------------------------------------------
    # 休暇申請
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            reason TEXT DEFAULT '',
            status TEXT DEFAULT '申請中',
            created_at TEXT DEFAULT '',
            reject_reason TEXT DEFAULT ''
        )
    """)

    # 既存データベース対応：休暇申請の追加項目
    if not column_exists(conn, "leave_requests", "created_at"):
        cur.execute("""
            ALTER TABLE leave_requests
            ADD COLUMN created_at TEXT DEFAULT ''
        """)

    if not column_exists(conn, "leave_requests", "reject_reason"):
        cur.execute("""
            ALTER TABLE leave_requests
            ADD COLUMN reject_reason TEXT DEFAULT ''
        """)

    # 有給／普通の休みを区別（既存申請は普通の休みとして保持）
    if not column_exists(conn, "leave_requests", "leave_type"):
        cur.execute("ALTER TABLE leave_requests ADD COLUMN leave_type TEXT DEFAULT '普通の休み'")

    # 有給付与履歴・付与予定
    cur.execute("""
        CREATE TABLE IF NOT EXISTS paid_leave_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL,
            planned_date TEXT DEFAULT '',
            planned_days REAL DEFAULT 0,
            grant_date TEXT DEFAULT '',
            granted_days REAL DEFAULT 0,
            notes TEXT DEFAULT ''
        )
    """)

    # 基本スケジュール（曜日単位のコピー元）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weekday INTEGER NOT NULL,
            staff_id INTEGER NOT NULL,
            visit_time TEXT NOT NULL,
            end_time TEXT DEFAULT '',
            patient_name TEXT NOT NULL,
            address TEXT DEFAULT '',
            memo TEXT DEFAULT '',
            client_id INTEGER,
            service_type TEXT DEFAULT '看護',
            is_day_off INTEGER DEFAULT 0
        )
    """)

    # -----------------------------------------------------
    # 訪問予定
    # -----------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER NOT NULL,
            visit_date TEXT NOT NULL,
            visit_time TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            address TEXT DEFAULT '',
            memo TEXT DEFAULT ''
        )
    """)

    # 新しい利用者管理用
    if not column_exists(conn, "visits", "client_id"):
        cur.execute("""
            ALTER TABLE visits
            ADD COLUMN client_id INTEGER
        """)

    if not column_exists(conn, "visits", "end_time"):
        cur.execute("ALTER TABLE visits ADD COLUMN end_time TEXT DEFAULT ''")

    # 改善案②：看護／リハ区分と利用者休みフラグ
    if not column_exists(conn, "visits", "service_type"):
        cur.execute("ALTER TABLE visits ADD COLUMN service_type TEXT DEFAULT '看護'")
    if not column_exists(conn, "visits", "is_day_off"):
        cur.execute("ALTER TABLE visits ADD COLUMN is_day_off INTEGER DEFAULT 0")

    # 同時送信などでアプリ側チェックをすり抜けないよう、DB側でも時間帯重複を拒否
    cur.execute("DROP TRIGGER IF EXISTS prevent_visit_overlap_insert")
    cur.execute("""
        CREATE TRIGGER prevent_visit_overlap_insert
        BEFORE INSERT ON visits
        WHEN EXISTS (
            SELECT 1 FROM visits v
            WHERE v.staff_id = NEW.staff_id
              AND v.visit_date = NEW.visit_date
              AND time(NEW.visit_time) < time(COALESCE(NULLIF(NEW.end_time, ''), time(NEW.visit_time, '+20 minutes')))
              AND time(v.visit_time) < time(COALESCE(NULLIF(v.end_time, ''), time(v.visit_time, '+20 minutes')))
              AND time(NEW.visit_time) < time(COALESCE(NULLIF(v.end_time, ''), time(v.visit_time, '+20 minutes')))
              AND time(v.visit_time) < time(COALESCE(NULLIF(NEW.end_time, ''), time(NEW.visit_time, '+20 minutes')))
        )
        BEGIN SELECT RAISE(ABORT, 'visit time overlap'); END
    """)
    cur.execute("DROP TRIGGER IF EXISTS prevent_visit_overlap_update")
    cur.execute("""
        CREATE TRIGGER prevent_visit_overlap_update
        BEFORE UPDATE OF staff_id, visit_date, visit_time, end_time ON visits
        WHEN EXISTS (
            SELECT 1 FROM visits v
            WHERE v.id != NEW.id
              AND v.staff_id = NEW.staff_id
              AND v.visit_date = NEW.visit_date
              AND time(NEW.visit_time) < time(COALESCE(NULLIF(NEW.end_time, ''), time(NEW.visit_time, '+20 minutes')))
              AND time(v.visit_time) < time(COALESCE(NULLIF(v.end_time, ''), time(v.visit_time, '+20 minutes')))
              AND time(NEW.visit_time) < time(COALESCE(NULLIF(v.end_time, ''), time(v.visit_time, '+20 minutes')))
              AND time(v.visit_time) < time(COALESCE(NULLIF(NEW.end_time, ''), time(NEW.visit_time, '+20 minutes')))
        )
        BEGIN SELECT RAISE(ABORT, 'visit time overlap'); END
    """)

    # -----------------------------------------------------
    # 管理者アカウント
    # -----------------------------------------------------

    # 以前のテストアカウントが残っている場合は、既存パスワードを維持して名前とメールを変更。
    cur.execute("SELECT id FROM staff WHERE email = ?", ("staff@example.com",))
    old_test = cur.fetchone()
    cur.execute("SELECT id FROM staff WHERE email = ?", ("takaaki@gmail.com",))
    main_admin = cur.fetchone()

    if old_test and not main_admin:
        cur.execute("UPDATE staff SET name = ?, email = ?, role = 'admin' WHERE email = ?",
                    ("山田孝昭", "takaaki@gmail.com", "staff@example.com"))
    elif main_admin:
        cur.execute("UPDATE staff SET name = ?, role = 'admin' WHERE email = ?",
                    ("山田孝昭", "takaaki@gmail.com"))
    else:
        cur.execute("""
            INSERT INTO staff (name, email, password, phone, address, role)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("山田孝昭", "takaaki@gmail.com", "1234", "", "", "admin"))

    # 指定された不要アカウントを削除する（メールアドレス完全一致）。
    # staffテーブルのアカウント行のみ削除し、過去の訪問予定・申請データは保持する。
    cur.execute("DELETE FROM staff WHERE lower(email) = lower(?)", ("tomoya@gmail.com",))

    # 2人目の管理者。既に存在する場合はパスワードを上書きせず、権限だけ確実に管理者にする。
    cur.execute("SELECT id FROM staff WHERE email = ?", ("admin@gmail.com",))
    second_admin = cur.fetchone()
    if second_admin:
        cur.execute("UPDATE staff SET role = 'admin' WHERE email = ?", ("admin@gmail.com",))
    else:
        cur.execute("""
            INSERT INTO staff (name, email, password, phone, address, role)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("管理者2", "admin@gmail.com", "1234", "", "", "admin"))


    conn.commit()
    conn.close()


init_db()


# =========================================================
# 共通CSS
# =========================================================

CSS = """
<style>

:root {
    --primary: #1677c8;
    --primary-dark: #0f5fa8;
    --primary-light: #eaf5ff;
    --bg: #f4f7fa;
    --card: #ffffff;
    --text: #1f2937;
    --muted: #6b7280;
    --border: #e5e7eb;
    --success: #16a34a;
    --danger: #dc2626;
    --warning: #d97706;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        "Yu Gothic",
        Meiryo,
        sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
}

header {
    background: white;
    min-height: 72px;
    display: flex;
    align-items: center;
    padding: 0 30px;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 100;
}

header h1 {
    margin: 0;
    font-size: 21px;
}

.container {
    max-width: 1250px;
    margin: 0 auto;
    padding: 30px;
}

.nav {
    display: flex;
    gap: 5px;
    margin-bottom: 28px;
    background: white;
    padding: 7px;
    border-radius: 12px;
    border: 1px solid var(--border);
    overflow-x: auto;
}

.nav a {
    text-decoration: none;
    color: #64748b;
    padding: 10px 15px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    white-space: nowrap;
}

.nav a:hover {
    background: var(--primary-light);
    color: var(--primary);
}

.card {
    background: white;
    padding: 26px;
    margin-bottom: 22px;
    border-radius: 14px;
    border: 1px solid var(--border);
    box-shadow: 0 2px 8px rgba(15,23,42,.04);
}

.card h2 {
    margin-top: 0;
}

label {
    display: block;
    margin-top: 17px;
    margin-bottom: 7px;
    font-size: 14px;
    font-weight: 700;
}

input,
select,
textarea {
    width: 100%;
    padding: 12px 14px;
    border: 1px solid #d7dee7;
    border-radius: 9px;
    font-size: 15px;
    background: white;
    color: #111827;
}

textarea {
    resize: vertical;
}

button {
    border: none;
    background: var(--primary);
    color: white;
    padding: 11px 18px;
    border-radius: 8px;
    cursor: pointer;
    margin-top: 16px;
    font-size: 14px;
    font-weight: 700;
}

button:hover {
    background: var(--primary-dark);
}

.success {
    background: var(--success);
}

.danger {
    background: var(--danger);
}

.gray {
    background: #64748b;
}

table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    background: white;
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
}

th,
td {
    border-bottom: 1px solid var(--border);
    padding: 13px 14px;
    text-align: left;
    font-size: 14px;
}

th {
    background: #f8fafc;
    color: #475569;
    white-space: nowrap;
}

tr:last-child td {
    border-bottom: none;
}

.small {
    font-size: 12px;
    color: var(--muted);
}

.event {
    display: block;
    background: #eef7ff;
    border-left: 4px solid var(--primary);
    padding: 8px;
    margin-top: 6px;
    border-radius: 7px;
    font-size: 12px;
}

.calendar {
    width: 100%;
    table-layout: fixed;
}

.calendar td {
    height: 145px;
    vertical-align: top;
    padding: 7px;
}

.calendar td.empty {
    background: #f8fafc;
}

.day-number {
    font-weight: 700;
    margin-bottom: 5px;
}

.calendar-nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}

.calendar-nav a {
    text-decoration: none;
    color: var(--primary);
    background: var(--primary-light);
    padding: 9px 14px;
    border-radius: 8px;
    font-weight: 700;
}

.calendar-event {
    display: block;
    text-decoration: none;
    color: #1e3a8a;
    background: #dbeafe;
    border-left: 4px solid #2563eb;
    padding: 7px;
    margin-bottom: 5px;
    border-radius: 6px;
    font-size: 12px;
}

.calendar-event span {
    display: block;
}

.today-cell {
    background: #eff6ff !important;
}

.add-link {
    display: inline-block;
    text-decoration: none;
    background: var(--primary);
    color: white;
    padding: 10px 16px;
    border-radius: 8px;
    font-weight: 700;
    margin-bottom: 15px;
}

.info-box {
    background: #f8fafc;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 15px;
    margin-top: 15px;
}

.login-wrapper {
    min-height: calc(100vh - 72px);
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 30px;
}

.login-card {
    width: 100%;
    max-width: 430px;
    background: white;
    padding: 35px;
    border-radius: 18px;
    border: 1px solid var(--border);
}

/* 改善案②：印刷・ドラッグ＆ドロップ・休み表示 */
.print-button { background:#475569; margin:4px; }
.calendar-event { cursor:grab; }
.calendar td.drop-target { outline:3px dashed #1677c8; outline-offset:-4px; background:#eff6ff; }
.calendar-event.day-off, .timeline-event.day-off { background:#fee2e2 !important; border-left-color:#dc2626 !important; color:#991b1b !important; }
.filter-row { display:flex; gap:12px; flex-wrap:wrap; align-items:end; margin:12px 0 18px; }
.filter-row > div { min-width:170px; flex:1; }
.filter-row label { margin-top:0; }
@media print {
    header, .nav, .no-print, button, form, .calendar-nav a, .add-link { display:none !important; }
    body { background:white !important; }
    .container { max-width:none; padding:0; }
    .card { border:0; box-shadow:none; padding:0; }
    .calendar td { height:110px; }
    .calendar-event, .timeline-event { break-inside:avoid; }
}

@media (max-width: 700px) {

    header {
        padding: 0 16px;
    }

    .container {
        padding: 15px 10px;
    }

    .card {
        padding: 18px;
    }

    table {
        display: block;
        overflow-x: auto;
        white-space: nowrap;
    }

    .calendar td {
        height: 105px;
        padding: 4px;
    }

    .calendar-event {
        font-size: 9px;
        padding: 5px;
    }

}

</style>
"""


# =========================================================
# 共通HTML
# =========================================================

def admin_nav():
    return """
    <div class="nav">
        <a href="/admin">申請管理</a>
        <a href="/admin/staff">スタッフ管理</a>
        <a href="/admin/clients">利用者管理</a>
        <a href="/admin/visits">訪問予定</a>
        <a href="/admin/calendar">カレンダー</a>
        <a href="/admin/leave/history">休暇履歴</a>
        <a href="/admin/leave/apply">管理者休暇申請</a>
        <a href="/admin/paid-leave">有給管理</a>
        <a href="/admin/schedule-base">基本スケジュール</a>
    </div>
    """


def staff_nav(staff_id):
    return f"""
    <div class="nav">
        <a href="/staff/{staff_id}">ホーム</a>
        <a href="/staff/{staff_id}/calendar">カレンダー</a>
        <a href="/staff/{staff_id}/visits">訪問予定</a>
        <a href="/staff/{staff_id}/leave">休暇申請</a>
        <a href="/staff/{staff_id}/requests">休暇履歴・申請状況</a>
    </div>
    """


# =========================================================
# ログイン
# =========================================================

@app.get("/", response_class=HTMLResponse)
def login_page():

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>訪問看護システム</title>
        {CSS}
    </head>

    <body>

    <header>
        <h1>訪問看護システム</h1>
    </header>

    <div class="login-wrapper">

        <div class="login-card">

            <h2>スタッフログイン</h2>

            <p class="small">
                登録されたスタッフのアカウントでログインしてください。
            </p>

            <form action="/login" method="post">

                <label>メールアドレス</label>

                <input
                    type="email"
                    name="email"
                    required
                >

                <label>パスワード</label>

                <input
                    type="password"
                    name="password"
                    required
                >

                <button type="submit">
                    ログイン
                </button>

            </form>

        </div>

    </div>

    </body>
    </html>
    """)


@app.post("/login")
def login(
    email: str = Form(...),
    password: str = Form(...)
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, role
        FROM staff
        WHERE email = ?
        AND password = ?
    """, (email, password))

    staff = cur.fetchone()

    conn.close()

    if staff is None:
        return HTMLResponse("""
        <h2>ログイン情報が違います。</h2>
        <a href="/">ログイン画面へ戻る</a>
        """)

    if staff["role"] == "admin":
        return RedirectResponse("/admin", status_code=303)

    return RedirectResponse(
        f"/staff/{staff['id']}",
        status_code=303
    )


# =========================================================
# スタッフホーム
# =========================================================

@app.get("/staff/{staff_id}", response_class=HTMLResponse)
def staff_home(staff_id: int):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM staff
        WHERE id = ?
    """, (staff_id,))

    staff = cur.fetchone()

    if staff is None:
        conn.close()
        return HTMLResponse("スタッフが見つかりません。")

    today = date.today().isoformat()

    cur.execute("""
        SELECT
            visits.*,
            clients.name AS client_name,
            clients.phone AS client_phone
        FROM visits
        LEFT JOIN clients
        ON visits.client_id = clients.id
        WHERE visits.staff_id = ?
        AND visits.visit_date = ?
        ORDER BY visits.visit_time
    """, (staff_id, today))

    visits = cur.fetchall()

    conn.close()

    events = ""

    for visit in visits:

        client_name = visit["client_name"] or visit["patient_name"]

        phone_html = make_tel_link(visit["client_phone"] or "", "📞 " + (visit["client_phone"] or "電話番号未登録"))
        events += f"""
        <div class="event">
            <strong>{html.escape(visit["visit_time"])}</strong><br>
            {html.escape(client_name)}<br>
            {(f'<a href="https://www.google.com/maps/search/?api=1&query={quote(visit["address"] or "")}" target="_blank" rel="noopener">{html.escape(visit["address"] or "")} 🗺️</a>') if visit["address"] else ""}<br>
            {phone_html}
        </div>
        """

    if not events:
        events = "<p>本日の訪問予定はありません。</p>"

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>スタッフホーム</title>
        {CSS}
    </head>

    <body>

    <header>
        <h1>スタッフホーム</h1>
    </header>

    <div class="container">

        {staff_nav(staff_id)}

        <div class="card">

            <h2>
                こんにちは、{html.escape(staff["name"])}さん
            </h2>

            <p class="small">
                電話番号：
                {html.escape(staff["phone"] or "未登録")}
            </p>

            <p class="small">
                住所：
                {html.escape(staff["address"] or "未登録")}
            </p>

        </div>

        <div class="card">

            <h2>今日の訪問予定</h2>

            {events}

        </div>

    </div>

    </body>
    </html>
    """)


# =========================================================
# スタッフ：カレンダー
# =========================================================

@app.get(
    "/staff/{staff_id}/calendar",
    response_class=HTMLResponse
)
def staff_calendar(
    staff_id: int,
    year: int = None,
    month: int = None,
    service_type: str = "all"
):

    today = date.today()

    year = year or today.year
    month = month or today.month

    first_day = date(year, month, 1)

    if month == 12:
        next_month_date = date(year + 1, 1, 1)
    else:
        next_month_date = date(year, month + 1, 1)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM staff
        WHERE id = ?
    """, (staff_id,))

    staff = cur.fetchone()

    if staff is None:
        conn.close()
        return HTMLResponse("スタッフが見つかりません。")

    cur.execute("""
        SELECT
            visits.*,
            clients.name AS client_name,
            staff.calendar_color AS staff_color
        FROM visits
        JOIN staff ON visits.staff_id = staff.id
        LEFT JOIN clients
        ON visits.client_id = clients.id
        WHERE visits.staff_id = ?
        AND visits.visit_date >= ?
        AND visits.visit_date < ?
        AND (? = 'all' OR COALESCE(visits.service_type, '看護') = ?)
        ORDER BY visits.visit_date, visits.visit_time
    """, (
        staff_id,
        first_day.isoformat(),
        next_month_date.isoformat(),
        service_type, service_type
    ))

    visits = cur.fetchall()

    conn.close()

    visit_by_date = {}

    for visit in visits:

        visit_by_date.setdefault(
            visit["visit_date"],
            []
        ).append(visit)

    cal = calendar.Calendar(firstweekday=0)

    calendar_html = ""

    for week in cal.monthdayscalendar(year, month):

        calendar_html += "<tr>"

        for day in week:

            if day == 0:
                calendar_html += '<td class="empty"></td>'
                continue

            current_date = date(
                year,
                month,
                day
            ).isoformat()

            today_class = ""

            if current_date == today.isoformat():
                today_class = "today-cell"

            events = ""

            for visit in visit_by_date.get(current_date, []):

                client_name = (
                    visit["client_name"]
                    or visit["patient_name"]
                )

                is_off = bool(visit["is_day_off"])
                event_style = "border-left-color:#dc2626;background:#fee2e2;color:#991b1b" if is_off else f"border-left-color:{html.escape(visit['staff_color'] or '#2563eb')};background:{html.escape(visit['staff_color'] or '#2563eb')}18"
                events += f"""
                <div class="event" style="{event_style}">
                    <strong>{html.escape(visit["visit_time"])}{('〜' + html.escape(visit['end_time'])) if visit['end_time'] else ''}</strong><br>
                    {html.escape(client_name)} {"【休み】" if is_off else ""}<br>
                    <small>{html.escape(visit['service_type'] or '看護')}</small>
                </div>
                """

            calendar_html += f"""
            <td class="{today_class}">

                <div class="day-number">
                    {day}
                </div>

                {events}

            </td>
            """

        calendar_html += "</tr>"

    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1

    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>自分のカレンダー</title>
        {CSS}
    </head>

    <body>

    <header>
        <h1>{html.escape(staff["name"])}さんのカレンダー</h1>
    </header>

    <div class="container">

        {staff_nav(staff_id)}

        <div class="card">

            <div class="calendar-nav">

                <a href="/staff/{staff_id}/calendar?year={prev_year}&month={prev_month}&service_type={quote(service_type)}">
                    ← 前月
                </a>

                <h2>
                    {year}年{month}月
                </h2>

                <a href="/staff/{staff_id}/calendar?year={next_year}&month={next_month}&service_type={quote(service_type)}">
                    次月 →
                </a>

            </div>

            <form method="get" class="filter-row no-print">
                <input type="hidden" name="year" value="{year}"><input type="hidden" name="month" value="{month}">
                <div><label>業務区分</label><select name="service_type"><option value="all" {"selected" if service_type == "all" else ""}>すべて</option><option value="看護" {"selected" if service_type == "看護" else ""}>看護のみ</option><option value="リハビリ" {"selected" if service_type == "リハビリ" else ""}>リハビリのみ</option></select></div>
                <button type="submit">絞り込む</button><button type="button" class="print-button" onclick="window.print()">印刷／PDF</button>
            </form>

            <table class="calendar">

                <tr>
                    <th>月</th>
                    <th>火</th>
                    <th>水</th>
                    <th>木</th>
                    <th>金</th>
                    <th>土</th>
                    <th>日</th>
                </tr>

                {calendar_html}

            </table>

        </div>

    </div>

    </body>
    </html>
    """)


# =========================================================
# スタッフ：訪問予定
# =========================================================

@app.get(
    "/staff/{staff_id}/visits",
    response_class=HTMLResponse
)
def staff_visits(staff_id: int):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            visits.*,
            clients.name AS client_name,
            clients.phone AS client_phone,
            clients.address AS client_address
        FROM visits
        LEFT JOIN clients
        ON visits.client_id = clients.id
        WHERE visits.staff_id = ?
        ORDER BY visits.visit_date, visits.visit_time
    """, (staff_id,))

    visits = cur.fetchall()
    conn.close()

    # 日付ごとに訪問予定をまとめる
    grouped_visits = {}
    for visit in visits:
        grouped_visits.setdefault(visit["visit_date"], []).append(visit)

    day_sections = ""
    for visit_date, day_visits in grouped_visits.items():
        day_rows = ""

        for i, visit in enumerate(day_visits):
            client_name = visit["client_name"] or visit["patient_name"]
            current_address = visit["address"] or visit["client_address"] or ""

            destination_url = (
                "https://www.google.com/maps/dir/?api=1"
                f"&destination={quote(current_address)}"
                "&travelmode=driving"
            ) if current_address else ""

            next_visit = day_visits[i + 1] if i + 1 < len(day_visits) else None
            next_url = ""
            next_name = ""
            if next_visit is not None:
                next_address = next_visit["address"] or next_visit["client_address"] or ""
                next_name = next_visit["client_name"] or next_visit["patient_name"]
                if current_address and next_address:
                    next_url = (
                        "https://www.google.com/maps/dir/?api=1"
                        f"&origin={quote(current_address)}"
                        f"&destination={quote(next_address)}"
                        "&travelmode=driving"
                    )

            route_buttons = ""
            if destination_url:
                route_buttons += f"""
                    <a href="{html.escape(destination_url, quote=True)}"
                       target="_blank" rel="noopener" class="route-button">
                        🗺️ ここへ行く
                    </a>
                """
            if next_url:
                route_buttons += f"""
                    <a href="{html.escape(next_url, quote=True)}"
                       target="_blank" rel="noopener" class="route-button next-route-button">
                        🗺️ 次の患者へ（{html.escape(next_name)}）
                    </a>
                """

            phone_html = make_tel_link(
                visit["client_phone"] or "",
                "📞 " + (visit["client_phone"] or "電話番号未登録")
            )
            map_link = (
                f'<a href="https://www.google.com/maps/search/?api=1&query={quote(current_address)}" target="_blank" rel="noopener">{html.escape(current_address)} 🗺️</a>'
                if current_address else ""
            )
            service_type = visit["service_type"] if "service_type" in visit.keys() else "看護"
            day_rows += f"""
                <tr>
                    <td class="time-cell">{html.escape(visit["visit_time"] or "")}</td>
                    <td>{html.escape(service_type or "看護")}</td>
                    <td><strong>{html.escape(client_name or "")}</strong></td>
                    <td>{phone_html}</td>
                    <td>{map_link}</td>
                    <td>{html.escape(visit["memo"] or "")}</td>
                    <td>{route_buttons or '<span class="small">住所が登録されていません</span>'}</td>
                </tr>
            """

        try:
            d = datetime.strptime(visit_date, "%Y-%m-%d").date()
            weekday = "月火水木金土日"[d.weekday()]
            date_label = f"{d.year}年{d.month}月{d.day}日（{weekday}）"
        except (ValueError, TypeError):
            date_label = html.escape(str(visit_date))

        day_sections += f"""
            <section class="visit-day-card">
                <div class="visit-day-heading">
                    <h2>📅 {date_label}</h2>
                    <span class="visit-count">{len(day_visits)}件</span>
                </div>
                <div class="table-wrap">
                    <table class="day-visit-table">
                        <thead>
                            <tr>
                                <th>時間</th><th>区分</th><th>利用者</th><th>電話</th>
                                <th>訪問先</th><th>メモ</th><th>ルート</th>
                            </tr>
                        </thead>
                        <tbody>{day_rows}</tbody>
                    </table>
                </div>
            </section>
        """

    if not day_sections:
        day_sections = '<div class="empty-visits">訪問予定はありません。</div>'

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>訪問予定</title>
        {CSS}
        <style>
            .visit-day-card {{
                background: #fff; border: 1px solid #dce3ea; border-radius: 12px;
                margin: 18px 0; overflow: hidden; box-shadow: 0 2px 7px rgba(0,0,0,.04);
            }}
            .visit-day-heading {{
                display: flex; align-items: center; justify-content: space-between;
                gap: 10px; padding: 13px 16px; background: #edf5fc;
                border-bottom: 1px solid #dce8f2;
            }}
            .visit-day-heading h2 {{ margin: 0; font-size: 18px; color: #174b75; }}
            .visit-count {{ background: #1677c8; color: white; border-radius: 20px;
                padding: 4px 11px; font-size: 13px; font-weight: bold; white-space: nowrap; }}
            .table-wrap {{ overflow-x: auto; }}
            .day-visit-table {{ width: 100%; min-width: 760px; border-collapse: collapse; margin: 0; }}
            .day-visit-table th, .day-visit-table td {{ padding: 10px 9px; border-bottom: 1px solid #edf0f3; text-align: left; vertical-align: middle; }}
            .day-visit-table th {{ background: #f8fafc; white-space: nowrap; }}
            .day-visit-table tbody tr:last-child td {{ border-bottom: 0; }}
            .time-cell {{ font-weight: bold; white-space: nowrap; color: #174b75; }}
            .route-button {{
                display: inline-block; margin: 3px; padding: 8px 12px;
                background: #1677c8; color: white; text-decoration: none;
                border-radius: 7px; font-weight: 600; font-size: 13px; white-space: nowrap;
            }}
            .route-button:hover {{ opacity: 0.85; }}
            .next-route-button {{ background: #16a34a; }}
            .empty-visits {{ background: white; padding: 25px; border-radius: 10px; text-align: center; }}
            @media (max-width: 700px) {{ .visit-day-heading h2 {{ font-size: 16px; }} }}
            @media print {{
                header, nav, .nav, .route-button {{ display: none !important; }}
                .visit-day-card {{ break-inside: avoid; box-shadow: none; }}
                body {{ background: white !important; }}
            }}
        </style>
    </head>
    <body>
    <header><h1>自分の訪問予定</h1></header>
    <div class="container">
        {staff_nav(staff_id)}
        <div class="card">
            <p class="small">
                日付ごとに訪問予定をまとめています。「ここへ行く」は現在地から訪問先まで、「次の患者へ」は同日の次の訪問先までのルートをGoogleマップで開きます。
            </p>
            {day_sections}
        </div>
    </div>
    </body>
    </html>
    """)


# =========================================================
# 休暇申請
# =========================================================

@app.get(
    "/staff/{staff_id}/leave",
    response_class=HTMLResponse
)
def leave_page(staff_id: int):

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>休暇申請</title>
        {CSS}
    </head>

    <body>

    <header>
        <h1>休暇申請</h1>
    </header>

    <div class="container">

        {staff_nav(staff_id)}

        <div class="card">

            <form action="/staff/{staff_id}/leave" method="post">

                <label>開始日</label>
                <input type="date" name="start_date" required>

                <label>終了日</label>
                <input type="date" name="end_date" required>

                <label>休暇の種類</label>
                <select name="leave_type" required>
                    <option value="普通の休み" selected>普通の休み（有給残日数に影響しない）</option>
                    <option value="有給休暇">有給休暇（承認後に残日数から差し引く）</option>
                </select>

                <label>申請理由</label>
                <select name="reason_choice" id="reason_choice" onchange="toggleOtherLeaveReason()" required>
                    <option value="私用のため" selected>私用のため</option>
                    <option value="体調不良のため">体調不良のため</option>
                    <option value="通院のため">通院のため</option>
                    <option value="家庭の事情のため">家庭の事情のため</option>
                    <option value="その他">その他</option>
                </select>
                <div id="other_leave_reason_wrap" style="display:none;">
                    <label>その他の理由</label>
                    <input type="text" name="reason_other" id="reason_other" maxlength="200" placeholder="理由を入力してください">
                </div>
                <script>
                function toggleOtherLeaveReason() {{
                    const isOther = document.getElementById('reason_choice').value === 'その他';
                    document.getElementById('other_leave_reason_wrap').style.display = isOther ? 'block' : 'none';
                    document.getElementById('reason_other').required = isOther;
                }}
                </script>

                <button type="submit">
                    申請する
                </button>

            </form>

        </div>

    </div>

    </body>
    </html>
    """)


@app.post("/staff/{staff_id}/leave")
def submit_leave(
    staff_id: int,
    start_date: str = Form(...),
    end_date: str = Form(...),
    reason_choice: str = Form("私用のため"),
    reason_other: str = Form(""),
    leave_type: str = Form("普通の休み")
):

    # 日付の逆転・不正入力を防止
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if end < start:
            return HTMLResponse("<meta charset='utf-8'><h2>終了日は開始日以降にしてください。</h2><a href='/staff/" + str(staff_id) + "/leave'>戻る</a>", status_code=400)
    except ValueError:
        return HTMLResponse("<meta charset='utf-8'><h2>日付が正しくありません。</h2><a href='/staff/" + str(staff_id) + "/leave'>戻る</a>", status_code=400)

    allowed_reasons = {"私用のため", "体調不良のため", "通院のため", "家庭の事情のため", "その他"}
    if reason_choice not in allowed_reasons:
        reason_choice = "私用のため"
    reason = reason_other.strip() if reason_choice == "その他" else reason_choice
    if leave_type not in {"普通の休み", "有給休暇"}:
        leave_type = "普通の休み"
    if not reason:
        return HTMLResponse("<meta charset='utf-8'><h2>申請理由を入力してください。</h2><a href='/staff/" + str(staff_id) + "/leave'>戻る</a>", status_code=400)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id FROM staff WHERE id = ?", (staff_id,))
    if cur.fetchone() is None:
        conn.close()
        return HTMLResponse("スタッフが見つかりません。", status_code=404)

    cur.execute("""
        INSERT INTO leave_requests
        (staff_id, start_date, end_date, reason, status, created_at, leave_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        staff_id,
        start_date,
        end_date,
        reason,
        "申請中",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        leave_type
    ))

    conn.commit()
    conn.close()

    return RedirectResponse(
        f"/staff/{staff_id}/requests",
        status_code=303
    )


# =========================================================
# スタッフ：申請状況
# =========================================================

@app.get(
    "/staff/{staff_id}/requests",
    response_class=HTMLResponse
)
def staff_requests(staff_id: int):

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT name FROM staff WHERE id = ?", (staff_id,))
    staff = cur.fetchone()
    if staff is None:
        conn.close()
        return HTMLResponse("スタッフが見つかりません。", status_code=404)

    cur.execute("""
        SELECT * FROM leave_requests
        WHERE staff_id = ?
        ORDER BY start_date DESC, id DESC
    """, (staff_id,))
    requests = cur.fetchall()
    conn.close()

    approved_days = 0
    paid_days = 0
    pending_count = 0
    rows = ""
    for request in requests:
        status = request["status"] or "申請中"
        if status == "承認":
            try:
                days = (date.fromisoformat(request["end_date"]) - date.fromisoformat(request["start_date"])).days + 1
                if (request["leave_type"] or "普通の休み") == "有給休暇":
                    paid_days += days
                else:
                    approved_days += days
            except (ValueError, TypeError):
                pass
        elif status == "申請中":
            pending_count += 1
        rows += f"""
        <tr>
            <td>{html.escape(format_wareki(request["start_date"]))}</td>
            <td>{html.escape(format_wareki(request["end_date"]))}</td>
            <td>{html.escape(request["leave_type"] or "普通の休み")}</td>
            <td>{html.escape(request["reason"] or "")}</td>
            <td><strong>{html.escape(status)}</strong></td>
            <td>{html.escape(request["reject_reason"] or "")}</td>
        </tr>
        """

    if not rows:
        rows = '<tr><td colspan="6">休暇申請の履歴はありません。</td></tr>'

    return HTMLResponse(f"""
    <!DOCTYPE html><html lang="ja"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>休暇履歴・申請状況</title>{CSS}
    </head><body>
    <header><h1>休暇履歴・申請状況</h1></header>
    <div class="container">{staff_nav(staff_id)}
      <div class="card">
        <h2>{html.escape(staff["name"])} さんの休暇履歴</h2>
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin:16px 0;">
          <div class="info-box" style="flex:1;min-width:140px;margin:0;"><div class="small">普通の休み（承認済み）</div><strong style="font-size:26px;color:#64748b;">{approved_days}日</strong></div>
          <div class="info-box" style="flex:1;min-width:140px;margin:0;"><div class="small">有給取得日数（承認済み）</div><strong style="font-size:26px;color:#1677c8;">{paid_days}日</strong></div>
          <div class="info-box" style="flex:1;min-width:140px;margin:0;"><div class="small">申請中</div><strong style="font-size:26px;color:#d97706;">{pending_count}件</strong></div>
          <div class="info-box" style="flex:1;min-width:140px;margin:0;"><div class="small">申請履歴</div><strong style="font-size:26px;">{len(requests)}件</strong></div>
        </div>
        <p class="small">承認済み日数は開始日・終了日を含む暦日数で集計しています。申請中・却下は取得日数に含みません。</p>
        <h3>申請・取得履歴</h3>
        <table><tr><th>開始日</th><th>終了日</th><th>休暇種類</th><th>理由</th><th>状態</th><th>却下理由</th></tr>{rows}</table>
      </div>
    </div></body></html>
    """)


# =========================================================
# 管理者：スタッフ別休暇履歴
# =========================================================

@app.get("/admin/leave/history", response_class=HTMLResponse)
def admin_leave_history(staff_id: int = 0):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM staff ORDER BY name")
    staff_list = cur.fetchall()
    cur.execute("""
        SELECT leave_requests.*, staff.name AS staff_name
        FROM leave_requests
        LEFT JOIN staff ON leave_requests.staff_id = staff.id
        WHERE (? = 0 OR leave_requests.staff_id = ?)
        ORDER BY leave_requests.start_date DESC, leave_requests.id DESC
    """, (staff_id, staff_id))
    requests = cur.fetchall()
    conn.close()

    options = '<option value="0">全スタッフ</option>'
    for st in staff_list:
        options += f'<option value="{st["id"]}" {"selected" if staff_id == st["id"] else ""}>{html.escape(st["name"])}</option>'

    approved_days = 0
    paid_days = 0
    pending_count = 0
    rows = ""
    for request in requests:
        status = request["status"] or "申請中"
        if status == "承認":
            try:
                days = (date.fromisoformat(request["end_date"]) - date.fromisoformat(request["start_date"])).days + 1
                if (request["leave_type"] or "普通の休み") == "有給休暇":
                    paid_days += days
                else:
                    approved_days += days
            except (ValueError, TypeError):
                pass
        elif status == "申請中":
            pending_count += 1
        rows += f"""
        <tr>
          <td>{html.escape(request["staff_name"] or "退職・削除済みスタッフ")}</td>
          <td>{html.escape(format_wareki(request["start_date"]))}</td>
          <td>{html.escape(format_wareki(request["end_date"]))}</td>
          <td>{html.escape(request["leave_type"] or "普通の休み")}</td>
          <td>{html.escape(request["reason"] or "")}</td>
          <td>{html.escape(status)}</td>
          <td>{html.escape(request["reject_reason"] or "")}</td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="7">該当する履歴はありません。</td></tr>'

    return HTMLResponse(f"""
    <!DOCTYPE html><html lang="ja"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>スタッフ別休暇履歴</title>{CSS}
    </head><body>
    <header><h1>スタッフ別休暇履歴</h1></header>
    <div class="container">{admin_nav()}
      <div class="card">
        <h2>スタッフごとの休暇履歴</h2>
        <form method="get" action="/admin/leave/history" class="filter-row">
          <div><label>スタッフを選択</label><select name="staff_id">{options}</select></div>
          <button type="submit">表示</button>
        </form>
        <div style="display:flex;gap:12px;flex-wrap:wrap;margin:16px 0;">
          <div class="info-box" style="flex:1;min-width:140px;margin:0;"><div class="small">普通の休み（承認済み）</div><strong style="font-size:26px;color:#64748b;">{approved_days}日</strong></div>
          <div class="info-box" style="flex:1;min-width:140px;margin:0;"><div class="small">有給取得日数（承認済み）</div><strong style="font-size:26px;color:#1677c8;">{paid_days}日</strong></div>
          <div class="info-box" style="flex:1;min-width:140px;margin:0;"><div class="small">申請中</div><strong style="font-size:26px;color:#d97706;">{pending_count}件</strong></div>
          <div class="info-box" style="flex:1;min-width:140px;margin:0;"><div class="small">申請履歴</div><strong style="font-size:26px;">{len(requests)}件</strong></div>
        </div>
        <p class="small">承認済み日数は開始日・終了日を含む暦日数で集計しています。全スタッフを選ぶと会社全体の合計です。</p>
        <table><tr><th>スタッフ</th><th>開始日</th><th>終了日</th><th>休暇種類</th><th>理由</th><th>状態</th><th>却下理由</th></tr>{rows}</table>
      </div>
    </div></body></html>
    """)


# =========================================================
# 管理者：申請管理
# =========================================================

@app.get("/admin", response_class=HTMLResponse)
def admin_page():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            leave_requests.*,
            staff.name AS staff_name
        FROM leave_requests
        JOIN staff
        ON leave_requests.staff_id = staff.id
        ORDER BY leave_requests.id DESC
    """)

    requests = cur.fetchall()

    conn.close()

    rows = ""

    for request in requests:

        rows += f"""
        <tr>

            <td>{request["id"]}</td>

            <td>{html.escape(request["staff_name"])}</td>

            <td>{html.escape(request["start_date"])}</td>

            <td>{html.escape(request["end_date"])}</td>

            <td>{html.escape(request["leave_type"] or "普通の休み")}</td>

            <td>{html.escape(request["reason"] or "")}</td>

            <td>{html.escape(request["status"])}</td>

            <td>{html.escape(request["reject_reason"] or "")}</td>

            <td>

                <form
                    action="/admin/leave/{request["id"]}/approve"
                    method="post"
                    style="display:inline;"
                >
                    <button class="success">
                        承認
                    </button>
                </form>

                <form
                    action="/admin/leave/{request["id"]}/reject"
                    method="post"
                    style="display:inline;"
                >
                    <input
                        type="text"
                        name="reject_reason"
                        placeholder="却下理由を入力"
                        required
                        style="width:180px; margin:0 4px 0 0;"
                    >
                    <button class="danger" type="submit">
                        却下
                    </button>
                </form>

            </td>

        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="9">
                申請はありません。
            </td>
        </tr>
        """

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>管理者</title>
        {CSS}
    </head>

    <body>

    <header>
        <h1>管理者画面</h1>
    </header>

    <div class="container">

        {admin_nav()}

        <div class="card">

            <h2>休暇申請一覧</h2>
            <p><a href="/admin/leave/history">スタッフ別の休暇取得履歴を確認する →</a></p>

            <table>

                <tr>
                    <th>ID</th>
                    <th>スタッフ</th>
                    <th>開始日</th>
                    <th>終了日</th>
                    <th>休暇種類</th>
                    <th>理由</th>
                    <th>状態</th>
                    <th>却下理由</th>
                    <th>操作</th>
                </tr>

                {rows}

            </table>

        </div>

    </div>

    </body>
    </html>
    """)


@app.post("/admin/leave/{request_id}/approve")
def approve_leave(request_id: int):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE leave_requests
        SET status = '承認'
        WHERE id = ?
    """, (request_id,))

    conn.commit()
    conn.close()

    return RedirectResponse(
        "/admin",
        status_code=303
    )


@app.post("/admin/leave/{request_id}/reject")
def reject_leave(
    request_id: int,
    reject_reason: str = Form(...)
):

    conn = get_db()
    cur = conn.cursor()

    reject_reason = reject_reason.strip()

    if not reject_reason:
        conn.close()
        return RedirectResponse("/admin", status_code=303)

    cur.execute("""
        UPDATE leave_requests
        SET status = '却下',
            reject_reason = ?
        WHERE id = ?
    """, (reject_reason, request_id))

    conn.commit()
    conn.close()

    return RedirectResponse("/admin", status_code=303)


# =========================================================
# 管理者：スタッフ管理
# =========================================================

@app.get(
    "/admin/staff",
    response_class=HTMLResponse
)
def staff_management():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM staff
        ORDER BY CASE WHEN staff_number IS NULL THEN 1 ELSE 0 END,
                 staff_number, name, id
    """)

    staff_list = cur.fetchall()

    conn.close()

    rows = ""

    for staff in staff_list:

        rows += f"""
        <tr>

            <td>{staff["id"]}</td>

            <td>{html.escape(str(staff["staff_number"] or "未設定"))}</td>

            <td>{html.escape(staff["name"])}</td>

            <td>{html.escape(staff["furigana"] or "")}</td>

            <td>{"表示" if staff["show_in_schedule"] else "非表示"}</td>

            <td>{html.escape(staff["email"])}</td>

            <td>{html.escape(staff["phone"] or "")}</td>

            <td>{html.escape(staff["address"] or "")}</td>

            <td>
                <a href="/admin/staff/{staff["id"]}/edit">
                    <button type="button">編集</button>
                </a>
            </td>

        </tr>
        """

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>スタッフ管理</title>
        {CSS}
    </head>

    <body>

    <header>
        <h1>スタッフ管理</h1>
    </header>

    <div class="container">

        {admin_nav()}

        <div class="card">

            <h2>スタッフを追加</h2>

            <form action="/admin/staff/add" method="post">

                <label>スタッフ番号（並び順）</label>
                <input type="number" name="staff_number" min="1" placeholder="例：1、35、38">

                <label>名前</label>
                <input type="text" name="name" required>

                <label>フリガナ</label>
                <input type="text" name="furigana" placeholder="例：ヤマダ タロウ">

                <label>時間割に表示する</label>
                <label style="font-weight:400"><input type="checkbox" name="show_in_schedule" value="1" checked style="width:auto"> 表示する（訪問予定の担当者候補にも表示）</label>

                <label>メールアドレス</label>
                <input type="email" name="email" required>

                <label>パスワード</label>
                <input type="password" name="password" required>

                <label>電話番号</label>
                <input type="tel" name="phone">

                <label>住所</label>
                <input type="text" name="address">

                <button type="submit">
                    スタッフを追加
                </button>

            </form>

        </div>

        <div class="card">

            <h2>登録スタッフ</h2>

            <table>

                <tr>
                    <th>番号</th>
                    <th>名前</th>
                    <th>フリガナ</th>
                    <th>時間割</th>
                    <th>メール</th>
                    <th>電話番号</th>
                    <th>住所</th>
                    <th>操作</th>
                </tr>

                {rows}

            </table>

        </div>

    </div>

    </body>
    </html>
    """)


@app.get("/admin/staff/{staff_id}/edit", response_class=HTMLResponse)
def edit_staff_page(staff_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM staff WHERE id = ?", (staff_id,))
    staff = cur.fetchone()
    conn.close()

    if staff is None:
        return HTMLResponse("<h2>スタッフが見つかりません。</h2><a href='/admin/staff'>戻る</a>", status_code=404)

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>スタッフ編集</title>
        {CSS}
    </head>
    <body>
        <header><h1>スタッフ編集</h1></header>
        <div class="container">
            {admin_nav()}
            <div class="card">
                <form action="/admin/staff/{staff_id}/edit" method="post">
                    <label>スタッフ番号（並び順）</label>
                    <input type="number" name="staff_number" min="1" value="{html.escape(str(staff['staff_number'] or ''), quote=True)}" placeholder="例：1、35、38">

                    <label>名前</label>
                    <input type="text" name="name" value="{html.escape(staff['name'] or '', quote=True)}" required>

                    <label>フリガナ</label>
                    <input type="text" name="furigana" value="{html.escape(staff['furigana'] or '', quote=True)}" placeholder="例：ヤマダ タロウ">

                    <label>時間割に表示する</label>
                    <label style="font-weight:400"><input type="checkbox" name="show_in_schedule" value="1" {"checked" if staff["show_in_schedule"] else ""} style="width:auto"> 表示する（訪問予定の担当者候補にも表示）</label>

                    <label>メールアドレス</label>
                    <input type="email" name="email" value="{html.escape(staff['email'] or '', quote=True)}" required>

                    <label>新しいパスワード（変更する場合のみ入力）</label>
                    <input type="password" name="password" autocomplete="new-password" placeholder="変更しない場合は空欄">

                    <label>電話番号</label>
                    <input type="tel" name="phone" value="{html.escape(staff['phone'] or '', quote=True)}">

                    <label>住所</label>
                    <input type="text" name="address" value="{html.escape(staff['address'] or '', quote=True)}">

                    <label>カレンダーの色</label>
                    <input type="color" name="calendar_color" value="{html.escape(staff['calendar_color'] or '#2563eb', quote=True)}">

                    <button type="submit">変更を保存</button>
                    <a href="/admin/staff">キャンセル</a>
                </form>
            </div>
        </div>
    </body>
    </html>
    """)


@app.post("/admin/staff/{staff_id}/edit")
def edit_staff(
    staff_id: int,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    calendar_color: str = Form("#2563eb"),
    staff_number: str = Form(""),
    furigana: str = Form(""),
    show_in_schedule: str = Form("")
):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM staff WHERE id = ?", (staff_id,))
    existing = cur.fetchone()
    if existing is None:
        conn.close()
        return HTMLResponse("<h2>スタッフが見つかりません。</h2><a href='/admin/staff'>戻る</a>", status_code=404)

    try:
        if password.strip():
            cur.execute("""
                UPDATE staff
                SET name = ?, email = ?, password = ?, phone = ?, address = ?,
                    calendar_color = ?, staff_number = ?, furigana = ?, show_in_schedule = ?
                WHERE id = ?
            """, (name.strip(), email.strip(), password, phone.strip(), address.strip(),
                  calendar_color, int(staff_number) if staff_number.strip() else None,
                  furigana.strip(), 1 if show_in_schedule == "1" else 0, staff_id))
        else:
            cur.execute("""
                UPDATE staff
                SET name = ?, email = ?, phone = ?, address = ?, calendar_color = ?,
                    staff_number = ?, furigana = ?, show_in_schedule = ?
                WHERE id = ?
            """, (name.strip(), email.strip(), phone.strip(), address.strip(), calendar_color,
                  int(staff_number) if staff_number.strip() else None,
                  furigana.strip(), 1 if show_in_schedule == "1" else 0, staff_id))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return HTMLResponse("""
            <h2>このメールアドレスはすでに使われています。</h2>
            <a href="/admin/staff">スタッフ管理に戻る</a>
        """, status_code=400)
    finally:
        # connが既に閉じている場合にも備えて、ここでは再度closeしない
        pass

    conn.close()
    return RedirectResponse("/admin/staff", status_code=303)


@app.post("/admin/staff/add")
def add_staff(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    staff_number: str = Form(""),
    furigana: str = Form(""),
    show_in_schedule: str = Form("")
):

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO staff
            (name, email, password, phone, address, staff_number, furigana, show_in_schedule)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name.strip(),
            email.strip(),
            password,
            phone.strip(),
            address.strip(),
            int(staff_number) if staff_number.strip() else None,
            furigana.strip(),
            1 if show_in_schedule == "1" else 0
        ))

        conn.commit()

    except sqlite3.IntegrityError:

        conn.close()

        return HTMLResponse("""
        <h2>このメールアドレスはすでに登録されています。</h2>
        <a href="/admin/staff">戻る</a>
        """)

    conn.close()

    return RedirectResponse(
        "/admin/staff",
        status_code=303
    )


# =========================================================
# 利用者管理
# =========================================================

@app.get(
    "/admin/clients",
    response_class=HTMLResponse
)
def client_management():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM clients
        ORDER BY id DESC
    """)

    clients = cur.fetchall()

    conn.close()

    rows = ""

    for client in clients:

        rows += f"""
        <tr data-search="{html.escape(((client["name"] or "") + (client["furigana"] or "")).replace(" ", "").replace("　", "").lower(), quote=True)}">

            <td>{client["id"]}</td>

            <td>{html.escape(client["name"])}</td>

            <td>{make_tel_link(client["phone"] or "")}</td>

            <td>{(f'<a href="https://www.google.com/maps/search/?api=1&query={quote(client["address"] or "")}" target="_blank" rel="noopener">{html.escape(client["address"] or "")} 🗺️</a>') if client["address"] else ""}</td>

            <td>{html.escape(format_wareki(client["birth_date"] or ""))}</td>

            <td>{html.escape(client["memo"] or "")}</td>

            <td>

                <a href="/admin/clients/{client["id"]}/edit">
                    <button type="button">
                        編集
                    </button>
                </a>

                <form
                    action="/admin/clients/{client["id"]}/delete"
                    method="post"
                    style="display:inline;"
                    onsubmit="return confirm('この利用者を削除しますか？関連する訪問予定への影響を確認してください。');"
                >

                    <button type="submit" class="danger">削除</button>

                </form>

            </td>

        </tr>
        """

    if not rows:

        rows = """
        <tr>
            <td colspan="7">
                利用者は登録されていません。
            </td>
        </tr>
        """

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>利用者管理</title>
        {CSS}
    </head>

    <body>

    <header>
        <h1>利用者管理</h1>
    </header>

    <div class="container">

        {admin_nav()}

        <div class="card">

            <h2>新規利用者を登録</h2>

            <form action="/admin/clients/add" method="post">

                <label>利用者名</label>
                <input type="text" name="name" required>

                <label>フリガナ</label>
                <input type="text" name="furigana" placeholder="例：ヤマダ タロウ">

                <label>生年月日（和暦）</label>
                <input type="text" name="birth_date" placeholder="例：平成10年4月1日 または 1998-04-01">
                <small>和暦・西暦どちらでも入力できます。</small>

                <label>住所</label>
                <input type="text" name="address">

                <label>電話番号</label>
                <input type="tel" name="phone">

                <label>メモ</label>
                <textarea name="memo" rows="4"></textarea>

                <button type="submit">
                    利用者を登録
                </button>

            </form>

        </div>

        <div class="card">

            <h2>登録済み利用者</h2>
            <label>利用者を検索（氏名・フリガナ）</label>
            <input type="search" id="client_list_search" placeholder="氏名またはフリガナを入力" oninput="filterClientRows()">
            <script>
            function filterClientRows() {{
                const q = (document.getElementById("client_list_search").value || "").toLowerCase().replace(/\\s/g, "");
                document.querySelectorAll("#client_list_table tbody tr[data-search]").forEach(row => {{
                    row.style.display = row.dataset.search.includes(q) ? "" : "none";
                }});
            }}
            </script>

            <table id="client_list_table">

                <tr>
                    <th>ID</th>
                    <th>利用者名</th>
                    <th>電話番号</th>
                    <th>住所</th>
                    <th>生年月日</th>
                    <th>メモ</th>
                    <th>操作</th>
                </tr>

                {rows}

            </table>

        </div>

    </div>

    </body>
    </html>
    """)


@app.post("/admin/clients/add")
def add_client(
    name: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    birth_date: str = Form(""),
    memo: str = Form(""),
    furigana: str = Form("")
):

    birth_date = parse_birth_date(birth_date)
    normalized_name = "".join((name or "").split()).casefold()
    conn = get_db()
    cur = conn.cursor()

    if birth_date:
        cur.execute("SELECT id, name FROM clients WHERE birth_date = ?", (birth_date,))
        duplicates = [r for r in cur.fetchall() if "".join((r["name"] or "").split()).casefold() == normalized_name]
        if duplicates:
            conn.close()
            return HTMLResponse(f"""<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><h2>重複登録の可能性があります</h2><p>同じ氏名・生年月日の利用者がすでに登録されています。登録内容を確認してください。</p><p>氏名：{html.escape(name)} / 生年月日：{html.escape(format_wareki(birth_date))}</p><a href='/admin/clients'>利用者管理へ戻る</a>""", status_code=409)

    cur.execute("""
        INSERT INTO clients
        (name, phone, address, birth_date, memo, furigana)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        name.strip(), phone, address, birth_date, memo, furigana.strip()
    ))

    try:
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return HTMLResponse("<meta charset='utf-8'><h2>重複登録の可能性があります。同じ氏名・生年月日の利用者が登録されています。</h2><a href='/admin/clients'>利用者管理へ戻る</a>", status_code=409)
    conn.close()

    return RedirectResponse(
        "/admin/clients",
        status_code=303
    )


@app.get(
    "/admin/clients/{client_id}/edit",
    response_class=HTMLResponse
)
def edit_client_page(client_id: int):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM clients
        WHERE id = ?
    """, (client_id,))

    client = cur.fetchone()

    conn.close()

    if client is None:
        return HTMLResponse("""
        <h2>利用者が見つかりません。</h2>
        <a href="/admin/clients">戻る</a>
        """)

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>利用者編集</title>
        {CSS}
    </head>

    <body>

    <header>
        <h1>利用者編集</h1>
    </header>

    <div class="container">

        {admin_nav()}

        <div class="card">

            <form
                action="/admin/clients/{client_id}/edit"
                method="post"
            >

                <label>利用者名</label>

                <input
                    type="text"
                    name="name"
                    value="{html.escape(client["name"])}"
                    required
                >

                <label>フリガナ</label>
                <input type="text" name="furigana" value="{html.escape(client["furigana"] or "", quote=True)}" placeholder="例：ヤマダ タロウ">

                <label>生年月日（和暦）</label>
                <input type="text" name="birth_date" value="{html.escape(format_wareki(client["birth_date"] or ""), quote=True)}" placeholder="例：平成10年4月1日 または 1998-04-01">
                <small>和暦・西暦どちらでも入力できます。</small>

                <label>住所</label>

                <input
                    type="text"
                    name="address"
                    value="{html.escape(client["address"] or "")}"
                >

                <label>電話番号</label>

                <input
                    type="tel"
                    name="phone"
                    value="{html.escape(client["phone"] or "")}"
                >

                <label>メモ</label>

                <textarea
                    name="memo"
                    rows="5"
                >{html.escape(client["memo"] or "")}</textarea>

                <button type="submit">
                    保存する
                </button>

            </form>

        </div>

    </div>

    </body>
    </html>
    """)


@app.post("/admin/clients/{client_id}/edit")
def edit_client(
    client_id: int,
    name: str = Form(...),
    phone: str = Form(""),
    address: str = Form(""),
    birth_date: str = Form(""),
    memo: str = Form(""),
    furigana: str = Form("")
):

    birth_date = parse_birth_date(birth_date)
    normalized_name = "".join((name or "").split()).casefold()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM clients WHERE birth_date = ? AND id != ?", (birth_date, client_id))
    duplicates = [r for r in cur.fetchall() if "".join((r["name"] or "").split()).casefold() == normalized_name]
    if birth_date and duplicates:
        conn.close()
        return HTMLResponse(f"""<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><h2>重複登録の可能性があります</h2><p>同じ氏名・生年月日の利用者がすでに登録されています。登録内容を確認してください。</p><a href='/admin/clients/{client_id}/edit'>編集画面へ戻る</a>""", status_code=409)

    cur.execute("""
        UPDATE clients
        SET name = ?, phone = ?, address = ?, birth_date = ?, memo = ?, furigana = ?
        WHERE id = ?
    """, (name.strip(), phone, address, birth_date, memo, furigana.strip(), client_id))

    try:
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return HTMLResponse("<meta charset='utf-8'><h2>重複登録の可能性があります。同じ氏名・生年月日の利用者が登録されています。</h2><a href='/admin/clients'>利用者管理へ戻る</a>", status_code=409)
    conn.close()

    return RedirectResponse(
        "/admin/clients",
        status_code=303
    )


@app.post("/admin/clients/{client_id}/delete")
def delete_client(client_id: int):

    conn = get_db()
    cur = conn.cursor()

    # 利用者を削除しても既存の訪問予定は消さない
    cur.execute("""
        UPDATE visits
        SET client_id = NULL
        WHERE client_id = ?
    """, (client_id,))

    cur.execute("""
        DELETE FROM clients
        WHERE id = ?
    """, (client_id,))

    conn.commit()
    conn.close()

    return RedirectResponse(
        "/admin/clients",
        status_code=303
    )


# =========================================================
# 管理者：訪問予定一覧
# =========================================================

@app.get(
    "/admin/visits",
    response_class=HTMLResponse
)
def admin_visits():

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            visits.*,
            staff.name AS staff_name,
            staff.calendar_color AS staff_color,
            clients.name AS client_name
        FROM visits
        JOIN staff
        ON visits.staff_id = staff.id
        LEFT JOIN clients
        ON visits.client_id = clients.id
        ORDER BY visits.visit_date, visits.visit_time
    """)

    visits = cur.fetchall()

    conn.close()

    rows = ""

    for visit in visits:

        client_name = (
            visit["client_name"]
            or visit["patient_name"]
        )

        rows += f"""
        <tr>

            <td>{html.escape(visit["visit_date"])}</td>

            <td>{html.escape(visit["visit_time"])}</td>

            <td>{html.escape(visit["staff_name"])}</td>

            <td>{html.escape(client_name)} {"【休み】" if visit["is_day_off"] else ""}</td>

            <td>{html.escape(visit["service_type"] or "看護")}</td>

            <td>{(f'<a href="https://www.google.com/maps/search/?api=1&query={quote(visit["address"] or "")}" target="_blank" rel="noopener">{html.escape(visit["address"] or "")} 🗺️</a>') if visit["address"] else ""}</td>

            <td>{html.escape(visit["memo"] or "")}</td>

            <td>

                <a href="/admin/visits/{visit["id"]}/edit">
                    <button type="button">
                        編集
                    </button>
                </a>

                <form
                    action="/admin/visits/{visit["id"]}/delete"
                    method="post"
                    style="display:inline;"
                    onsubmit="return confirm('この訪問予定・実績を削除しますか？この操作は取り消せません。');"
                >

                    <button type="submit" class="danger">削除</button>

                </form>

            </td>

        </tr>
        """

    if not rows:

        rows = """
        <tr>
            <td colspan="7">
                訪問予定はありません。
            </td>
        </tr>
        """

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>訪問予定</title>
        {CSS}
    </head>

    <body>

    <header>
        <h1>訪問予定管理</h1>
    </header>

    <div class="container">

        {admin_nav()}

        <div class="card">

            <h2>訪問予定</h2>

            <a href="/admin/calendar/day?date={date.today().isoformat()}" class="add-link" style="margin-right:8px;">今日のスタッフ別時間割</a>
            <a
                href="/admin/visits/add"
                class="add-link"
            >
                ＋ 訪問予定を追加
            </a>
            <button type="button" class="print-button no-print" onclick="window.print()">印刷／PDF</button>

            <table>

                <tr>
                    <th>日付</th>
                    <th>時間</th>
                    <th>スタッフ</th>
                    <th>利用者</th>
                    <th>区分</th>
                    <th>訪問先</th>
                    <th>メモ</th>
                    <th>操作</th>
                </tr>

                {rows}

            </table>

        </div>

    </div>

    </body>
    </html>
    """)


# =========================================================
# 訪問予定追加
# =========================================================

@app.get(
    "/admin/visits/add",
    response_class=HTMLResponse
)
def add_visit_page(date: str = ""):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, furigana, staff_number, show_in_schedule
        FROM staff
        WHERE COALESCE(show_in_schedule, 1) = 1
        ORDER BY CASE WHEN staff_number IS NULL THEN 1 ELSE 0 END, staff_number, name
    """)

    staff_list = cur.fetchall()

    cur.execute("""
        SELECT id, name, phone, address, furigana
        FROM clients
        ORDER BY name
    """)

    clients = cur.fetchall()

    conn.close()

    staff_options = ""

    for staff in staff_list:

        staff_search = f'{staff["name"] or ""} {staff["furigana"] or ""} {staff["staff_number"] or ""}'
        staff_label = f'{staff["staff_number"]}番　' if staff["staff_number"] else ''
        staff_options += f"""
        <option value="{staff["id"]}" data-search="{html.escape(staff_search, quote=True)}">
            {html.escape(staff_label + staff["name"])}
        </option>
        """

    client_options = ""

    for client in clients:

        client_options += f"""
        <option
            value="{client["id"]}"
            data-phone="{html.escape(client["phone"] or "")}"
            data-address="{html.escape(client["address"] or "")}"
            data-search="{html.escape((client["name"] or "") + " " + (client["furigana"] or ""), quote=True)}"
        >
            {html.escape(client["name"])}
        </option>
        """

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>

        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >

        <title>訪問予定を追加</title>

        {CSS}

        <script>

        function filterStaff() {{
            const q = (document.getElementById("staff_search").value || "").toLowerCase();
            const select = document.getElementById("staff_id");
            for (const option of select.options) {{
                if (!option.value) {{ option.hidden = false; continue; }}
                option.hidden = !(option.text.toLowerCase().includes(q) || (option.dataset.search || "").toLowerCase().includes(q));
            }}
        }}

        function filterClients() {{
            const q = (document.getElementById("client_search").value || "").toLowerCase();
            const select = document.getElementById("client_id");
            for (const option of select.options) {{
                if (!option.value) {{ option.hidden = false; continue; }}
                option.hidden = !(option.text.toLowerCase().includes(q) || (option.dataset.search || "").toLowerCase().includes(q));
            }}
        }}

        function updateClientInfo() {{

            const select =
                document.getElementById("client_id");

            const option =
                select.options[select.selectedIndex];

            const phone =
                option.getAttribute("data-phone") || "";

            const address =
                option.getAttribute("data-address") || "";

            document.getElementById("client_phone").value =
                phone;

            document.getElementById("address").value =
                address;
        }}

        </script>

    </head>

    <body>

    <header>
        <h1>訪問予定を追加</h1>
    </header>

    <div class="container">

        {admin_nav()}

        <div class="card">

            <form
                action="/admin/visits/add"
                method="post"
            >

                <label>スタッフを検索（氏名・フリガナ・番号）</label>
                <input type="search" id="staff_search" placeholder="名前・フリガナ・番号で検索" oninput="filterStaff()">

                <label>スタッフ</label>

                <select name="staff_id" id="staff_id" required>
                    {staff_options}
                </select>

                <label>訪問日</label>

                <input
                    type="date"
                    name="visit_date"
                    value="{html.escape(date)}"
                    required
                >

                <label>訪問時間</label>

                <label>開始予定時刻</label>
                <input type="time" name="visit_time" required>

                <label>終了予定時刻</label>
                <input type="time" name="end_time">

                <label>業務区分</label>
                <select name="service_type"><option value="看護">看護</option><option value="リハビリ">リハビリ</option></select>

                <label style="font-weight:400"><input type="checkbox" name="is_day_off" value="1" style="width:auto"> 利用者の休みとして登録（カレンダーに赤色表示）</label>

                <label>利用者を検索（氏名・フリガナ）</label>
                <input type="search" id="client_search" placeholder="名前・フリガナを入力して絞り込み" oninput="filterClients()">

                <label>利用者</label>

                <select
                    name="client_id"
                    id="client_id"
                    onchange="updateClientInfo()"
                    required
                >

                    <option value="">
                        利用者を選択してください
                    </option>

                    {client_options}

                </select>

                <label>利用者の電話番号</label>

                <input
                    type="text"
                    id="client_phone"
                    readonly
                >

                <label>訪問先</label>

                <input
                    type="text"
                    name="address"
                    id="address"
                >

                <label>メモ</label>

                <textarea
                    name="memo"
                    rows="4"
                ></textarea>

                <button type="submit">
                    訪問予定を追加
                </button>

            </form>

            <div class="info-box">

                <strong>
                    利用者について
                </strong>

                <p class="small">
                    利用者管理で登録した利用者を選択すると、
                    電話番号と住所が自動で表示されます。
                </p>

            </div>

        </div>

    </div>

    </body>
    </html>
    """)


@app.post("/admin/visits/add")
def add_visit(
    staff_id: int = Form(...),
    visit_date: str = Form(...),
    visit_time: str = Form(...),
    end_time: str = Form(""),
    client_id: int = Form(...),
    address: str = Form(""),
    memo: str = Form(""),
    service_type: str = Form("看護"),
    is_day_off: str = Form("")
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT name, address
        FROM clients
        WHERE id = ?
    """, (client_id,))

    client = cur.fetchone()

    if client is None:

        conn.close()

        return HTMLResponse("""
        <h2>利用者が見つかりません。</h2>
        <a href="/admin/visits/add">
            戻る
        </a>
        """)

    conflict = visit_conflict(conn, staff_id, visit_date, visit_time, end_time)
    if conflict:
        conn.close()
        return HTMLResponse(f"<meta charset='utf-8'><h2>登録できません</h2><p>{html.escape(conflict)}</p><a href='/admin/visits/add?date={quote(visit_date)}'>入力画面に戻る</a>", status_code=409)

    # 利用者の名前を旧 patient_name にも保存
    patient_name = client["name"]

    # 住所が空なら利用者住所を使用
    if not address:
        address = client["address"] or ""

    cur.execute("""
        INSERT INTO visits
        (
            staff_id,
            visit_date,
            visit_time,
            patient_name,
            address,
            memo,
            client_id,
            end_time,
            service_type,
            is_day_off
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        staff_id,
        visit_date,
        visit_time,
        patient_name,
        address,
        memo,
        client_id,
        end_time,
        service_type if service_type in ("看護", "リハビリ") else "看護",
        1 if is_day_off == "1" else 0
    ))

    conn.commit()
    conn.close()

    return RedirectResponse(
        "/admin/calendar",
        status_code=303
    )


# =========================================================
# 訪問予定編集
# =========================================================

@app.get(
    "/admin/visits/{visit_id}/edit",
    response_class=HTMLResponse
)
def edit_visit_page(visit_id: int):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM visits
        WHERE id = ?
    """, (visit_id,))

    visit = cur.fetchone()

    if visit is None:

        conn.close()

        return HTMLResponse("""
        <h2>訪問予定が見つかりません。</h2>
        <a href="/admin/calendar">
            カレンダーへ戻る
        </a>
        """)

    cur.execute("""
        SELECT id, name, furigana, staff_number, show_in_schedule
        FROM staff
        ORDER BY CASE WHEN staff_number IS NULL THEN 1 ELSE 0 END, staff_number, name
    """)

    staff_list = cur.fetchall()

    cur.execute("""
        SELECT id, name, phone, address, furigana
        FROM clients
        ORDER BY name
    """)

    clients = cur.fetchall()

    conn.close()

    staff_options = ""

    for staff in staff_list:

        selected = ""

        if staff["id"] == visit["staff_id"]:
            selected = "selected"

        staff_search = f'{staff["name"] or ""} {staff["furigana"] or ""} {staff["staff_number"] or ""}'
        staff_label = f'{staff["staff_number"]}番　' if staff["staff_number"] else ''
        hidden_label = "（時間割非表示）" if not staff["show_in_schedule"] else ""
        staff_options += f"""
        <option value="{staff["id"]}" data-search="{html.escape(staff_search, quote=True)}" {selected}>
            {html.escape(staff_label + staff["name"] + hidden_label)}
        </option>
        """

    client_options = ""

    for client in clients:

        selected = ""

        if client["id"] == visit["client_id"]:
            selected = "selected"

        client_options += f"""
        <option
            value="{client["id"]}"
            data-phone="{html.escape(client["phone"] or "")}"
            data-address="{html.escape(client["address"] or "")}"
            data-search="{html.escape((client["name"] or "") + " " + (client["furigana"] or ""), quote=True)}"
            {selected}
        >
            {html.escape(client["name"])}
        </option>
        """

    current_client_id = visit["client_id"]

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>

        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >

        <title>訪問予定を編集</title>

        {CSS}

        <script>

        function filterStaff() {{
            const q = (document.getElementById("staff_search").value || "").toLowerCase();
            const select = document.getElementById("staff_id");
            for (const option of select.options) {{
                if (!option.value) {{ option.hidden = false; continue; }}
                option.hidden = !(option.text.toLowerCase().includes(q) || (option.dataset.search || "").toLowerCase().includes(q));
            }}
        }}

        function filterClients() {{
            const q = (document.getElementById("client_search").value || "").toLowerCase();
            const select = document.getElementById("client_id");
            for (const option of select.options) {{
                if (!option.value) {{ option.hidden = false; continue; }}
                option.hidden = !(option.text.toLowerCase().includes(q) || (option.dataset.search || "").toLowerCase().includes(q));
            }}
        }}

        function updateClientInfo() {{

            const select =
                document.getElementById("client_id");

            const option =
                select.options[select.selectedIndex];

            const phone =
                option.getAttribute("data-phone") || "";

            const clientAddress =
                option.getAttribute("data-address") || "";

            document.getElementById("client_phone").value =
                phone;

            if (clientAddress) {{
                document.getElementById("address").value =
                    clientAddress;
            }}
        }}

        </script>

    </head>

    <body>

    <header>
        <h1>訪問予定を編集</h1>
    </header>

    <div class="container">

        {admin_nav()}

        <div style="margin:12px 0 16px;">
            <a href="/admin/calendar" class="button" style="display:inline-block;text-decoration:none;padding:10px 14px;border-radius:8px;background:#e5e7eb;color:#111827;font-weight:600;">← カレンダーに戻る</a>
        </div>

        <div class="card">

            <form
                action="/admin/visits/{visit_id}/edit"
                method="post"
            >

                <label>スタッフを検索（氏名・フリガナ・番号）</label>
                <input type="search" id="staff_search" placeholder="名前・フリガナ・番号で検索" oninput="filterStaff()">

                <label>スタッフ</label>

                <select name="staff_id" id="staff_id" required>
                    {staff_options}
                </select>

                <label>訪問日</label>

                <input
                    type="date"
                    name="visit_date"
                    value="{html.escape(visit["visit_date"])}"
                    required
                >

                <label>訪問時間</label>

                <label>開始予定時刻</label>
                <input type="time" name="visit_time" value="{html.escape(visit["visit_time"])}" required>

                <label>終了予定時刻</label>
                <input type="time" name="end_time" value="{html.escape(visit["end_time"] or "")}">

                <label>業務区分</label>
                <select name="service_type"><option value="看護" {"selected" if (visit["service_type"] or "看護") == "看護" else ""}>看護</option><option value="リハビリ" {"selected" if visit["service_type"] == "リハビリ" else ""}>リハビリ</option></select>

                <label style="font-weight:400"><input type="checkbox" name="is_day_off" value="1" {"checked" if visit["is_day_off"] else ""} style="width:auto"> 利用者の休みとして登録（カレンダーに赤色表示）</label>

                <label>利用者を検索（氏名・フリガナ）</label>
                <input type="search" id="client_search" placeholder="名前・フリガナを入力して絞り込み" oninput="filterClients()">

                <label>利用者</label>

                <select
                    name="client_id"
                    id="client_id"
                    onchange="updateClientInfo()"
                    required
                >

                    <option value="">
                        利用者を選択してください
                    </option>

                    {client_options}

                </select>

                <label>利用者の電話番号</label>

                <input
                    type="text"
                    id="client_phone"
                    readonly
                >

                <label>訪問先</label>

                <input
                    type="text"
                    name="address"
                    id="address"
                    value="{html.escape(visit["address"] or "")}"
                >

                <label>メモ</label>

                <textarea
                    name="memo"
                    rows="4"
                >{html.escape(visit["memo"] or "")}</textarea>

                <button type="submit">
                    保存する
                </button>

            </form>

            <form
                action="/admin/visits/{visit_id}/delete"
                method="post"
                onsubmit="return confirm('この訪問予定・実績を削除しますか？この操作は取り消せません。');"
            >

                <button
                    type="submit"
                    class="danger"
                >
                    この予定を削除
                </button>

            </form>

        </div>

    </div>

    <script>

    document.addEventListener("DOMContentLoaded", function() {{

        const select =
            document.getElementById("client_id");

        if (select.value) {{
            updateClientInfo();
        }}

    }});

    </script>

    </body>
    </html>
    """)


@app.post("/admin/visits/{visit_id}/edit")
def edit_visit(
    visit_id: int,
    staff_id: int = Form(...),
    visit_date: str = Form(...),
    visit_time: str = Form(...),
    end_time: str = Form(""),
    client_id: int = Form(...),
    address: str = Form(""),
    memo: str = Form(""),
    service_type: str = Form("看護"),
    is_day_off: str = Form("")
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT name, address
        FROM clients
        WHERE id = ?
    """, (client_id,))

    client = cur.fetchone()

    if client is None:

        conn.close()

        return HTMLResponse("""
        <h2>利用者が見つかりません。</h2>
        <a href="/admin/calendar">戻る</a>
        """)

    conflict = visit_conflict(conn, staff_id, visit_date, visit_time, end_time, exclude_id=visit_id)
    if conflict:
        conn.close()
        return HTMLResponse(f"<meta charset='utf-8'><h2>保存できません</h2><p>{html.escape(conflict)}</p><a href='/admin/visits/{visit_id}/edit'>編集画面に戻る</a>", status_code=409)

    patient_name = client["name"]

    if not address:
        address = client["address"] or ""

    cur.execute("""
        UPDATE visits
        SET
            staff_id = ?,
            visit_date = ?,
            visit_time = ?,
            end_time = ?,
            patient_name = ?,
            address = ?,
            memo = ?,
            client_id = ?,
            service_type = ?,
            is_day_off = ?
        WHERE id = ?
    """, (
        staff_id,
        visit_date,
        visit_time,
        end_time,
        patient_name,
        address,
        memo,
        client_id,
        service_type if service_type in ("看護", "リハビリ") else "看護",
        1 if is_day_off == "1" else 0,
        visit_id
    ))

    conn.commit()
    conn.close()

    return RedirectResponse(
        "/admin/calendar",
        status_code=303
    )


@app.post("/admin/visits/{visit_id}/delete")
def delete_visit(visit_id: int):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        DELETE FROM visits
        WHERE id = ?
    """, (visit_id,))

    conn.commit()
    conn.close()

    return RedirectResponse(
        "/admin/calendar",
        status_code=303
    )


# =========================================================
# 管理者：今週の訪問予定を来週へコピー／来週分を一括削除
# =========================================================

def get_current_and_next_week():
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    next_monday = this_monday + timedelta(days=7)
    next_sunday = next_monday + timedelta(days=6)
    return this_monday, next_monday, next_sunday


@app.post("/admin/calendar/copy-this-week")
def copy_this_week():
    this_monday, next_monday, next_sunday = get_current_and_next_week()
    this_sunday = this_monday + timedelta(days=6)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT staff_id, visit_date, visit_time, end_time, patient_name,
               address, memo, client_id, service_type, is_day_off
        FROM visits
        WHERE visit_date >= ? AND visit_date <= ?
        ORDER BY visit_date, visit_time, id
    """, (this_monday.isoformat(), this_sunday.isoformat()))
    source_visits = cur.fetchall()

    copied = 0
    skipped = 0
    try:
        for visit in source_visits:
            source_date = date.fromisoformat(visit["visit_date"])
            target_date = source_date + timedelta(days=7)

            if visit["client_id"] is not None:
                cur.execute("""
                    SELECT 1 FROM visits
                    WHERE staff_id = ? AND visit_date = ? AND visit_time = ?
                      AND client_id = ?
                    LIMIT 1
                """, (visit["staff_id"], target_date.isoformat(),
                      visit["visit_time"], visit["client_id"]))
            else:
                cur.execute("""
                    SELECT 1 FROM visits
                    WHERE staff_id = ? AND visit_date = ? AND visit_time = ?
                      AND client_id IS NULL AND patient_name = ?
                    LIMIT 1
                """, (visit["staff_id"], target_date.isoformat(),
                      visit["visit_time"], visit["patient_name"]))

            if cur.fetchone():
                skipped += 1
                continue

            cur.execute("""
                INSERT INTO visits
                    (staff_id, visit_date, visit_time, end_time, patient_name,
                     address, memo, client_id, service_type, is_day_off)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                visit["staff_id"], target_date.isoformat(),
                visit["visit_time"], visit["end_time"] or "",
                visit["patient_name"], visit["address"] or "",
                visit["memo"] or "", visit["client_id"],
                visit["service_type"] or "看護", visit["is_day_off"] or 0
            ))
            copied += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return RedirectResponse(
        f"/admin/calendar?copy_result={copied}&copy_skipped={skipped}",
        status_code=303
    )


@app.post("/admin/calendar/delete-next-week")
def delete_next_week():
    _, next_monday, next_sunday = get_current_and_next_week()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM visits
        WHERE visit_date >= ? AND visit_date <= ?
    """, (next_monday.isoformat(), next_sunday.isoformat()))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return RedirectResponse(
        f"/admin/calendar?deleted_next_week={deleted}",
        status_code=303
    )



# =========================================================
# 管理者：休暇申請（管理者自身の申請）
# =========================================================

@app.get("/admin/leave/apply", response_class=HTMLResponse)
def admin_leave_apply_page():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM staff WHERE role = 'admin' ORDER BY name")
    admins = cur.fetchall()
    conn.close()
    options = "".join(
        f'<option value="{st["id"]}">{html.escape(st["name"])}</option>'
        for st in admins
    )
    if not options:
        options = '<option value="">管理者アカウントがありません</option>'
    return HTMLResponse(f"""<!doctype html><html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>管理者休暇申請</title>{CSS}</head><body>
<header><h1>管理者休暇申請</h1></header><div class="container">{admin_nav()}
<div class="card"><h2>管理者の休暇を申請</h2>
<p class="small">申請する管理者アカウントを選択してください。有給休暇は承認後に残日数へ反映されます。</p>
<form method="post" action="/admin/leave/apply">
<label>申請する管理者</label><select name="staff_id" required>{options}</select>
<label>休暇の種類</label><select name="leave_type"><option value="普通の休み">普通の休み</option><option value="有給休暇">有給休暇</option></select>
<label>開始日</label><input type="date" name="start_date" required>
<label>終了日</label><input type="date" name="end_date" required>
<label>申請理由</label><select name="reason_choice"><option>私用のため</option><option>体調不良のため</option><option>通院のため</option><option>家庭の事情のため</option><option>その他</option></select>
<label>その他の場合の理由</label><input type="text" name="reason_other" maxlength="200">
<button type="submit">休暇を申請する</button></form></div></div></body></html>""")


@app.post("/admin/leave/apply")
def admin_leave_apply_submit(
    staff_id: int = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    leave_type: str = Form("普通の休み"),
    reason_choice: str = Form("私用のため"),
    reason_other: str = Form("")
):
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if end < start:
            raise ValueError
    except ValueError:
        return HTMLResponse("<meta charset='utf-8'><h2>日付が正しくありません。</h2><a href='/admin/leave/apply'>戻る</a>", status_code=400)
    if leave_type not in {"普通の休み", "有給休暇"}:
        leave_type = "普通の休み"
    allowed = {"私用のため", "体調不良のため", "通院のため", "家庭の事情のため", "その他"}
    if reason_choice not in allowed:
        reason_choice = "私用のため"
    reason = reason_other.strip() if reason_choice == "その他" else reason_choice
    if not reason:
        return HTMLResponse("<meta charset='utf-8'><h2>理由を入力してください。</h2><a href='/admin/leave/apply'>戻る</a>", status_code=400)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM staff WHERE id = ? AND role = 'admin'", (staff_id,))
    if cur.fetchone() is None:
        conn.close()
        return HTMLResponse("管理者アカウントを確認できません。", status_code=404)
    cur.execute("""
        INSERT INTO leave_requests
        (staff_id, start_date, end_date, reason, status, created_at, leave_type)
        VALUES (?, ?, ?, ?, '申請中', ?, ?)
    """, (staff_id, start_date, end_date, reason,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S"), leave_type))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin", status_code=303)


# =========================================================
# 管理者：有給付与・残日数管理
# =========================================================

@app.get("/admin/paid-leave", response_class=HTMLResponse)
def admin_paid_leave(staff_id: int = 0):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM staff ORDER BY name")
    staff_list = cur.fetchall()
    cur.execute("""
        SELECT paid_leave_grants.*, staff.name AS staff_name
        FROM paid_leave_grants
        LEFT JOIN staff ON staff.id = paid_leave_grants.staff_id
        WHERE (? = 0 OR paid_leave_grants.staff_id = ?)
        ORDER BY COALESCE(NULLIF(paid_leave_grants.grant_date, ''),
                          paid_leave_grants.planned_date) DESC, paid_leave_grants.id DESC
    """, (staff_id, staff_id))
    grants = cur.fetchall()
    cur.execute("""
        SELECT staff_id, SUM(granted_days) AS total
        FROM paid_leave_grants
        WHERE grant_date != '' AND grant_date <= date('now','localtime')
        GROUP BY staff_id
    """)
    granted_map = {r["staff_id"]: float(r["total"] or 0) for r in cur.fetchall()}
    cur.execute("""
        SELECT staff_id, start_date, end_date
        FROM leave_requests
        WHERE status = '承認' AND leave_type = '有給休暇'
    """)
    used_map = {}
    for r in cur.fetchall():
        try:
            n = (date.fromisoformat(r["end_date"]) - date.fromisoformat(r["start_date"])).days + 1
            used_map[r["staff_id"]] = used_map.get(r["staff_id"], 0) + n
        except (ValueError, TypeError):
            pass
    conn.close()

    selected_name = "全スタッフ"
    for st in staff_list:
        if st["id"] == staff_id:
            selected_name = st["name"]
    options = '<option value="0">全スタッフ</option>' + "".join(
        f'<option value="{st["id"]}" {"selected" if staff_id == st["id"] else ""}>{html.escape(st["name"])}</option>'
        for st in staff_list
    )
    summary_rows = ""
    target_staff = [st for st in staff_list if staff_id == 0 or st["id"] == staff_id]
    for st in target_staff:
        granted = granted_map.get(st["id"], 0)
        used = used_map.get(st["id"], 0)
        remaining = granted - used
        summary_rows += f'<tr><td>{html.escape(st["name"])}</td><td>{granted:g}日</td><td>{used:g}日</td><td><strong>{remaining:g}日</strong></td></tr>'
    if not summary_rows:
        summary_rows = '<tr><td colspan="4">スタッフが登録されていません。</td></tr>'

    grant_rows = ""
    for g in grants:
        grant_rows += f"""<tr><td>{html.escape(g["staff_name"] or "削除済み")}</td>
<td>{html.escape(format_wareki(g["planned_date"])) or "—"}</td><td>{float(g["planned_days"] or 0):g}日</td>
<td>{html.escape(format_wareki(g["grant_date"])) or "未付与"}</td><td>{float(g["granted_days"] or 0):g}日</td>
<td>{html.escape(g["notes"] or "")}</td><td><form method="post" action="/admin/paid-leave/{g['id']}/delete" onsubmit="return confirm('この付与記録を削除しますか？')"><button class="danger">削除</button></form></td></tr>"""
    if not grant_rows:
        grant_rows = '<tr><td colspan="7">付与記録はありません。</td></tr>'

    return HTMLResponse(f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>有給管理</title>{CSS}</head><body>
<header><h1>有給休暇管理</h1></header><div class="container">{admin_nav()}
<div class="card"><h2>スタッフ別の有給残日数</h2>
<form method="get" class="filter-row"><div><label>スタッフ</label><select name="staff_id">{options}</select></div><button>表示</button></form>
<table><tr><th>スタッフ</th><th>付与済み日数</th><th>承認済み取得日数</th><th>残日数</th></tr>{summary_rows}</table>
<p class="small">残日数＝実際に付与した日数の合計－承認済みの有給休暇日数。申請中・却下・普通の休みは差し引きません。</p></div>
<div class="card"><h2>有給の付与予定・付与実績を登録</h2>
<form method="post" action="/admin/paid-leave/add">
<label>スタッフ</label><select name="staff_id" required>{"".join(f'<option value="{st["id"]}">{html.escape(st["name"])}</option>' for st in staff_list)}</select>
<label>付与予定日</label><input type="date" name="planned_date">
<label>付与予定日数</label><input type="number" name="planned_days" min="0" step="0.5" value="0">
<label>実際の付与日（付与済みの場合）</label><input type="date" name="grant_date">
<label>実際の付与日数</label><input type="number" name="granted_days" min="0" step="0.5" value="0">
<label>メモ</label><input type="text" name="notes" maxlength="200">
<button type="submit">付与情報を登録</button></form></div>
<div class="card"><h2>{html.escape(selected_name)} の付与履歴</h2>
<table><tr><th>スタッフ</th><th>付与予定日</th><th>予定日数</th><th>実際の付与日</th><th>付与日数</th><th>メモ</th><th>操作</th></tr>{grant_rows}</table>
</div></div></body></html>""")


@app.post("/admin/paid-leave/add")
def admin_paid_leave_add(
    staff_id: int = Form(...),
    planned_date: str = Form(""),
    planned_days: float = Form(0),
    grant_date: str = Form(""),
    granted_days: float = Form(0),
    notes: str = Form("")
):
    for value in (planned_date, grant_date):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                return HTMLResponse("日付が正しくありません。<a href='/admin/paid-leave'>戻る</a>", status_code=400)
    if planned_days < 0 or granted_days < 0:
        return HTMLResponse("日数は0以上で入力してください。", status_code=400)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM staff WHERE id = ?", (staff_id,))
    if cur.fetchone() is None:
        conn.close()
        return HTMLResponse("スタッフが見つかりません。", status_code=404)
    cur.execute("""
        INSERT INTO paid_leave_grants
        (staff_id, planned_date, planned_days, grant_date, granted_days, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (staff_id, planned_date, planned_days, grant_date, granted_days, notes.strip()))
    conn.commit()
    conn.close()
    return RedirectResponse(f"/admin/paid-leave?staff_id={staff_id}", status_code=303)


@app.post("/admin/paid-leave/{grant_id}/delete")
def admin_paid_leave_delete(grant_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM paid_leave_grants WHERE id = ?", (grant_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/paid-leave", status_code=303)


# =========================================================
# 管理者：基本スケジュール（毎週のひな形）
# =========================================================

@app.get("/admin/schedule-base", response_class=HTMLResponse)
def admin_schedule_base(copied: int = None, skipped: int = 0):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, furigana, staff_number FROM staff
        ORDER BY CASE WHEN staff_number IS NULL THEN 1 ELSE 0 END, staff_number, name
    """)
    staff_list = cur.fetchall()
    cur.execute("SELECT id, name, furigana, address FROM clients ORDER BY name")
    clients = cur.fetchall()
    cur.execute("""
        SELECT schedule_templates.*, staff.name AS staff_name, staff.staff_number,
               COALESCE(clients.name, schedule_templates.patient_name) AS client_name,
               COALESCE(NULLIF(clients.address, ''), schedule_templates.address, '') AS client_address
        FROM schedule_templates
        LEFT JOIN staff ON staff.id = schedule_templates.staff_id
        LEFT JOIN clients ON clients.id = schedule_templates.client_id
        ORDER BY weekday, visit_time, staff_name
    """)
    templates = cur.fetchall()
    conn.close()
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    grouped = {i: [] for i in range(7)}
    for t in templates:
        grouped[int(t["weekday"])].append(t)
    day_sections = ""
    for wd, label in enumerate(weekdays):
        rows = ""
        for t in grouped[wd]:
            staff_label = ((str(t["staff_number"]) + "番　") if t["staff_number"] else "") + (t["staff_name"] or "削除済み")
            rows += f"""<tr><td>{html.escape(t["visit_time"])}{("〜" + html.escape(t["end_time"])) if t["end_time"] else ""}</td><td>{html.escape(staff_label)}</td>
<td>{html.escape(t["client_name"] or "")}</td><td>{html.escape(t["service_type"] or "看護")}</td><td>{html.escape(t["client_address"] or "")}</td>
<td><form method="post" action="/admin/schedule-base/{t['id']}/delete" onsubmit="return confirm('この基本予定を削除しますか？')"><button class="danger">削除</button></form></td></tr>"""
        if not rows:
            rows = '<tr><td colspan="6">登録なし</td></tr>'
        day_sections += f'<h3>{label}曜日</h3><div class="table-wrap"><table><tr><th>時間</th><th>担当</th><th>利用者</th><th>区分</th><th>住所</th><th>操作</th></tr>{rows}</table></div>'
    staff_options = "".join(
        f'<option value="{st["id"]}" data-search="{html.escape((st["name"] or "") + " " + (st["furigana"] or "") + " " + str(st["staff_number"] or ""), quote=True)}">{html.escape(((str(st["staff_number"]) + "番　") if st["staff_number"] else "") + st["name"])}</option>'
        for st in staff_list)
    client_options = '<option value="">利用者を選択（任意）</option>' + "".join(
        f'<option value="{cl["id"]}" data-search="{html.escape((cl["name"] or "") + " " + (cl["furigana"] or ""), quote=True)}" data-name="{html.escape(cl["name"] or "", quote=True)}" data-address="{html.escape(cl["address"] or "", quote=True)}">{html.escape(cl["name"])}{("（" + html.escape(cl["furigana"]) + "）") if cl["furigana"] else ""}</option>'
        for cl in clients)
    copied_msg = f'<div class="info-box">基本スケジュールをコピーしました：{copied}件追加、{skipped}件スキップ</div>' if copied is not None else ""
    return HTMLResponse(f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>基本スケジュール</title>{CSS}
<style>
.search-line{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.search-line>div{{min-width:0}}.hint{{font-size:12px;color:#64748b;margin:4px 0 8px}}.table-wrap{{overflow-x:auto}}.table-wrap table{{min-width:650px}}
@media(max-width:600px){{.search-line{{grid-template-columns:1fr}}}}
</style></head><body>
<header><h1>基本スケジュール</h1></header><div class="container">{admin_nav()}
{copied_msg}
<div class="card"><h2>毎週のコピー元になる予定を登録</h2>
<p>ここで登録した予定は、登録しただけでは実際の週間予定には入りません。下の「この週にコピー」を押すと、指定した週の訪問予定に反映されます。</p>
<form method="post" action="/admin/schedule-base/add" id="baseScheduleForm">
<label>曜日</label><select name="weekday">{"".join(f'<option value="{i}">{d}曜日</option>' for i,d in enumerate(weekdays))}</select>
<label>担当スタッフを検索（名前・ふりがな・スタッフ番号）</label><input type="search" id="staffSearch" placeholder="例：松永、マツナガ、35"><p class="hint">スタッフ番号だけを入力しても検索できます。</p>
<label>担当スタッフ</label><select name="staff_id" id="baseStaffSelect" required>{staff_options}</select>
<label>利用者を検索（名前・ふりがな）</label><input type="search" id="clientSearch" placeholder="例：山田、ヤマダ">
<label>利用者</label><select name="client_id" id="baseClientSelect">{client_options}</select>
<label>利用者名（利用者一覧にない場合）</label><input name="patient_name" id="basePatientName" maxlength="100" placeholder="利用者一覧から選ぶと自動入力されます">
<label>開始時刻</label><input type="time" name="visit_time" required>
<label>終了時刻</label><input type="time" name="end_time">
<label>業務区分</label><select name="service_type"><option>看護</option><option>リハビリ</option></select>
<label>住所</label><input name="address" id="baseAddress" placeholder="利用者を選ぶと住所が自動入力されます">
<label>メモ</label><input name="memo">
<button type="submit">基本予定を追加</button></form></div>
<div class="card"><h2>基本スケジュールを指定週へ反映</h2>
<p>登録した基本予定を、実際の訪問予定にコピーします。コピー後は週間予定画面で、その週だけの変更・調整ができます。</p>
<form method="post" action="/admin/schedule-base/copy" onsubmit="return confirm('基本スケジュールを指定した週へコピーします。既存予定は削除しません。続けますか？')">
<label>コピー先の週の月曜日</label><input type="date" name="target_monday" required>
<button class="success" type="submit">この週のスケジュールに反映する</button></form>
<p class="small">同じ担当・日付・開始時刻・利用者の予定は重複登録せず、時間が重なる予定もスキップします。反映結果は週間予定画面にも表示されます。</p>
<p><a href="/admin/calendar/week">週間予定を確認する</a></p></div>
<div class="card"><h2>基本スケジュール一覧</h2>{day_sections}</div>
<div class="card"><h2>実際の週予定から基本スケジュールを作成</h2>
<form method="post" action="/admin/schedule-base/save-week" onsubmit="return confirm('選択した週の予定で、現在の基本スケジュールをすべて置き換えます。よろしいですか？')">
<label>元にする週の月曜日</label><input type="date" name="source_monday" required>
<button type="submit" class="gray">この週を基本スケジュールとして保存</button></form></div>
</div>
<script>
(function(){{
 const staffSearch=document.getElementById('staffSearch'), staffSelect=document.getElementById('baseStaffSelect');
 const clientSearch=document.getElementById('clientSearch'), clientSelect=document.getElementById('baseClientSelect');
 function filterOptions(input,select){{const q=(input.value||'').toLowerCase().replace(/[\\s　]/g,''); for(const opt of select.options){{if(!opt.value){{opt.hidden=false;continue;}} const hay=(opt.dataset.search||opt.textContent||'').toLowerCase().replace(/[\\s　]/g,''); opt.hidden=!!q&&!hay.includes(q);}} if(select.selectedOptions.length&&select.selectedOptions[0].hidden)select.value='';}}
 staffSearch.addEventListener('input',()=>filterOptions(staffSearch,staffSelect));
 clientSearch.addEventListener('input',()=>filterOptions(clientSearch,clientSelect));
 clientSelect.addEventListener('change',()=>{{const opt=clientSelect.selectedOptions[0]; if(!opt||!opt.value)return; document.getElementById('basePatientName').value=opt.dataset.name||''; document.getElementById('baseAddress').value=opt.dataset.address||'';}});
}})();
</script></body></html>""")


@app.post("/admin/schedule-base/add")
def admin_schedule_base_add(
    weekday: int = Form(...),
    staff_id: int = Form(...),
    visit_time: str = Form(...),
    end_time: str = Form(""),
    client_id: str = Form(""),
    patient_name: str = Form(""),
    service_type: str = Form("看護"),
    address: str = Form(""),
    memo: str = Form("")
):
    if weekday not in range(7):
        return HTMLResponse("曜日が正しくありません。", status_code=400)
    try:
        start = datetime.strptime(visit_time, "%H:%M")
        if end_time:
            end = datetime.strptime(end_time, "%H:%M")
            if end <= start:
                raise ValueError
    except ValueError:
        return HTMLResponse("時刻が正しくありません。", status_code=400)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM staff WHERE id = ?", (staff_id,))
    if not cur.fetchone():
        conn.close()
        return HTMLResponse("スタッフが見つかりません。", status_code=404)
    cid = int(client_id) if client_id.strip().isdigit() else None
    if cid:
        cur.execute("SELECT name, address FROM clients WHERE id = ?", (cid,))
        c = cur.fetchone()
        if not c:
            conn.close()
            return HTMLResponse("利用者が見つかりません。", status_code=404)
        patient_name = c["name"]
        # 利用者に登録された住所を優先し、空欄の場合だけ手入力住所を使う
        address = c["address"] or address
    if not patient_name.strip():
        conn.close()
        return HTMLResponse("利用者名を入力するか、利用者を選択してください。", status_code=400)
    cur.execute("""
        INSERT INTO schedule_templates
        (weekday, staff_id, visit_time, end_time, patient_name, address, memo, client_id, service_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (weekday, staff_id, visit_time, end_time, patient_name.strip(), address.strip(),
          memo.strip(), cid, service_type if service_type in {"看護", "リハビリ"} else "看護"))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/schedule-base", status_code=303)


@app.post("/admin/schedule-base/{template_id}/delete")
def admin_schedule_base_delete(template_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM schedule_templates WHERE id = ?", (template_id,))
    conn.commit()
    conn.close()
    return RedirectResponse("/admin/schedule-base", status_code=303)


@app.post("/admin/schedule-base/copy")
def admin_schedule_base_copy(target_monday: str = Form(...)):
    try:
        monday = date.fromisoformat(target_monday)
        if monday.weekday() != 0:
            return HTMLResponse("コピー先は月曜日を指定してください。<a href='/admin/schedule-base'>戻る</a>", status_code=400)
    except ValueError:
        return HTMLResponse("日付が正しくありません。", status_code=400)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT schedule_templates.*,
               COALESCE(clients.name, schedule_templates.patient_name) AS current_client_name,
               COALESCE(NULLIF(clients.address, ''), schedule_templates.address, '') AS current_client_address
        FROM schedule_templates LEFT JOIN clients ON clients.id = schedule_templates.client_id
        ORDER BY schedule_templates.weekday, schedule_templates.visit_time, schedule_templates.id
    """)
    templates = cur.fetchall()
    copied = skipped = 0
    try:
        for t in templates:
            target_date = monday + timedelta(days=int(t["weekday"]))
            if t["client_id"] is not None:
                cur.execute("SELECT 1 FROM visits WHERE staff_id=? AND visit_date=? AND visit_time=? AND client_id=? LIMIT 1",
                            (t["staff_id"], target_date.isoformat(), t["visit_time"], t["client_id"]))
            else:
                cur.execute("SELECT 1 FROM visits WHERE staff_id=? AND visit_date=? AND visit_time=? AND client_id IS NULL AND patient_name=? LIMIT 1",
                            (t["staff_id"], target_date.isoformat(), t["visit_time"], t["patient_name"]))
            if cur.fetchone():
                skipped += 1
                continue
            conflict = visit_conflict(conn, t["staff_id"], target_date.isoformat(), t["visit_time"], t["end_time"] or "")
            if conflict:
                skipped += 1
                continue
            cur.execute("""
                INSERT INTO visits
                (staff_id, visit_date, visit_time, end_time, patient_name, address, memo, client_id, service_type, is_day_off)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (t["staff_id"], target_date.isoformat(), t["visit_time"], t["end_time"] or "",
                  t["current_client_name"] or t["patient_name"], t["current_client_address"] or "", t["memo"] or "", t["client_id"],
                  t["service_type"] or "看護", t["is_day_off"] or 0))
            copied += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return RedirectResponse(f"/admin/calendar/week?start_date={monday.isoformat()}&copied={copied}&skipped={skipped}", status_code=303)


@app.post("/admin/schedule-base/save-week")
def admin_schedule_base_save_week(source_monday: str = Form(...)):
    try:
        monday = date.fromisoformat(source_monday)
        if monday.weekday() != 0:
            return HTMLResponse("元にする週は月曜日を指定してください。", status_code=400)
    except ValueError:
        return HTMLResponse("日付が正しくありません。", status_code=400)
    sunday = monday + timedelta(days=6)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM visits WHERE visit_date >= ? AND visit_date <= ? ORDER BY visit_date, visit_time",
                (monday.isoformat(), sunday.isoformat()))
    source = cur.fetchall()
    try:
        cur.execute("DELETE FROM schedule_templates")
        for v in source:
            weekday = date.fromisoformat(v["visit_date"]).weekday()
            cur.execute("""
                INSERT INTO schedule_templates
                (weekday, staff_id, visit_time, end_time, patient_name, address, memo, client_id, service_type, is_day_off)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (weekday, v["staff_id"], v["visit_time"], v["end_time"] or "",
                  v["patient_name"], v["address"] or "", v["memo"] or "", v["client_id"],
                  v["service_type"] or "看護", v["is_day_off"] or 0))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return RedirectResponse("/admin/schedule-base", status_code=303)


# =========================================================
# 管理者：週単位カレンダー・印刷
# =========================================================

@app.get("/admin/calendar/week", response_class=HTMLResponse)
def admin_calendar_week(start_date: str = "", staff_id: int = 0,
                        service_type: str = "all", copied: int = None, skipped: int = 0):
    try:
        start = date.fromisoformat(start_date) if start_date else date.today() - timedelta(days=date.today().weekday())
        start = start - timedelta(days=start.weekday())
    except ValueError:
        start = date.today() - timedelta(days=date.today().weekday())
    end = start + timedelta(days=6)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, staff_number, calendar_color FROM staff
        ORDER BY CASE WHEN staff_number IS NULL THEN 1 ELSE 0 END, staff_number, name
    """)
    staff_list = cur.fetchall()
    cur.execute("""
        SELECT visits.*, staff.name AS staff_name, staff.staff_number, staff.calendar_color,
               COALESCE(clients.name, visits.patient_name) AS client_name
        FROM visits JOIN staff ON staff.id = visits.staff_id
        LEFT JOIN clients ON clients.id = visits.client_id
        WHERE visits.visit_date >= ? AND visits.visit_date <= ?
          AND (? = 0 OR visits.staff_id = ?)
          AND (? = 'all' OR COALESCE(visits.service_type, '看護') = ?)
        ORDER BY visits.visit_date, visits.visit_time, staff.staff_number, staff.name
    """, (start.isoformat(), end.isoformat(), staff_id, staff_id, service_type, service_type))
    visits = cur.fetchall()
    conn.close()
    by_day = {start + timedelta(days=i): [] for i in range(7)}
    for v in visits:
        try:
            by_day[date.fromisoformat(v["visit_date"])].append(v)
        except (ValueError, KeyError):
            pass
    display_staff_list = [st for st in staff_list if staff_id == 0 or st["id"] == staff_id]
    weekday_names = ["月", "火", "水", "木", "金", "土", "日"]
    day_html = ""
    for i in range(7):
        d = start + timedelta(days=i)
        day_visits = by_day[d]
        times = sorted({v["visit_time"] for v in day_visits})
        if not times:
            day_html += f'<section class="day-sheet"><h3>{d.month}/{d.day}（{weekday_names[i]}）</h3><p class="empty-day">予定なし</p></section>'
            continue
        cells = {}
        for v in day_visits:
            cells.setdefault((v["visit_time"], v["staff_id"]), []).append(v)
        def safe_staff_color(value):
            value = value or "#2563eb"
            return value if len(value) == 7 and value.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in value[1:]) else "#2563eb"
        head = "".join(f'<th class="staff-head" style="--staff-color:{safe_staff_color(st["calendar_color"])}">{html.escape(((str(st["staff_number"]) + "番　") if st["staff_number"] else "") + st["name"])}</th>' for st in display_staff_list)
        body = ""
        for tm in times:
            row = f'<th class="time-head">{html.escape(tm)}</th>'
            for st in display_staff_list:
                matches = cells.get((tm, st["id"]), [])
                content = ""
                for v in matches:
                    kind = v["service_type"] or "看護"
                    off = bool(v["is_day_off"])
                    title = ("【休み】" if off else "") + (v["client_name"] or "")
                    content += f'<div class="visit-cell"><strong>{html.escape(title)}</strong><span class="kind">{html.escape(kind)}</span>'
                    if v["end_time"]:
                        content += f'<small>{html.escape(v["visit_time"])}〜{html.escape(v["end_time"])}</small>'
                    if v["address"]:
                        content += f'<small>{html.escape(v["address"])}</small>'
                    if v["memo"]:
                        content += f'<small>{html.escape(v["memo"])}</small>'
                    content += '</div>'
                row += f'<td>{content or "<span class=\'empty-cell\'>—</span>"}</td>'
            body += f'<tr>{row}</tr>'
        day_html += f'<section class="day-sheet"><h3>{d.month}/{d.day}（{weekday_names[i]}）</h3><div class="week-grid-wrap"><table class="week-grid"><thead><tr><th class="time-head">時間</th>{head}</tr></thead><tbody>{body}</tbody></table></div></section>'
    options = '<option value="0">全スタッフ</option>' + "".join(
        f'<option value="{st["id"]}" {"selected" if staff_id == st["id"] else ""}>{html.escape(((str(st["staff_number"]) + "番　") if st["staff_number"] else "") + st["name"])}</option>' for st in staff_list)
    prev = start - timedelta(days=7)
    nxt = start + timedelta(days=7)
    msg = f'<div class="info-box">基本スケジュールのコピー：{copied}件追加、{skipped}件スキップ</div>' if copied is not None else ""
    return HTMLResponse(f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>週間訪問予定</title>{CSS}
<style>
.week-grid-wrap{{overflow-x:auto}}.week-grid{{border-collapse:collapse;table-layout:fixed;min-width:850px;width:100%;margin:0 0 16px}}.week-grid th,.week-grid td{{border:1px solid #cbd5e1;padding:7px;vertical-align:top;font-size:12px;min-width:115px}}.week-grid .time-head{{min-width:65px;width:72px;background:#eaf0f6;text-align:center;white-space:nowrap}}.week-grid .staff-head{{background:#eaf0f6;border-top:4px solid var(--staff-color);text-align:center}}.visit-cell{{border-left:3px solid #2563eb;background:#f1f6fc;border-radius:5px;padding:6px;margin:2px 0;display:flex;flex-direction:column;gap:3px;overflow-wrap:anywhere}}.visit-cell .kind{{font-size:10px;color:#1d4ed8;font-weight:bold}}.visit-cell small{{color:#475569;font-size:10px}}.empty-cell,.empty-day{{color:#94a3b8}}.day-sheet{{margin-bottom:22px;break-inside:avoid}}.day-sheet h3{{background:#eaf0f6;padding:8px 10px;border-left:4px solid #2563eb;margin-bottom:8px}}
@media print{{@page{{size:A4 landscape;margin:8mm}}body{{background:white;font-size:10px}}header,.no-print,nav,.nav{{display:none!important}}.container{{max-width:none!important;margin:0!important;padding:0!important}}.card{{box-shadow:none!important;border:0!important;padding:0!important;margin:0!important}}.day-sheet{{break-inside:avoid;page-break-inside:avoid;margin-bottom:8mm}}.week-grid{{min-width:0!important;width:100%!important}}.week-grid th,.week-grid td{{font-size:8px;padding:4px;min-width:0}}.visit-cell{{padding:3px}}.visit-cell small{{font-size:7px}}.day-sheet h3{{font-size:12px;padding:5px}}}}
</style></head><body><header><h1>週間訪問予定</h1></header><div class="container">{admin_nav()}
<div class="card no-print"><form method="get" class="filter-row"><div><label>週の基準日</label><input type="date" name="start_date" value="{start.isoformat()}"></div>
<div><label>スタッフ</label><select name="staff_id">{options}</select></div>
<div><label>業務区分</label><select name="service_type"><option value="all">すべて</option><option value="看護" {"selected" if service_type=="看護" else ""}>看護のみ</option><option value="リハビリ" {"selected" if service_type=="リハビリ" else ""}>リハビリのみ</option></select></div><button>表示</button><button type="button" class="print-button" onclick="window.print()">週間を印刷／PDF</button></form>
<div class="calendar-nav"><a href="/admin/calendar/week?start_date={prev.isoformat()}&staff_id={staff_id}&service_type={quote(service_type)}">← 前週</a><strong>{start.strftime("%Y/%m/%d")} 〜 {end.strftime("%Y/%m/%d")}</strong><a href="/admin/calendar/week?start_date={nxt.isoformat()}&staff_id={staff_id}&service_type={quote(service_type)}">次週 →</a></div>
{msg}<p><a href="/admin/calendar">月カレンダーへ戻る</a> ／ <a href="/admin/schedule-base">基本スケジュールへ</a></p></div>
<div class="card"><h2>{start.strftime("%Y年%m月%d日")}〜{end.strftime("%Y年%m月%d日")} の訪問予定</h2><p class="small">日付ごとに、縦が時間・横が担当スタッフです。</p>{day_html}</div>
</div></body></html>""")


# =========================================================
# 管理者カレンダー
# =========================================================

@app.post("/admin/visits/{visit_id}/move")
def move_visit_date(visit_id: int, new_date: str = Form(...)):
    try:
        new_date = date.fromisoformat(new_date).isoformat()
    except ValueError:
        return JSONResponse({"ok": False, "message": "日付が正しくありません。"}, status_code=400)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT staff_id, visit_time, end_time FROM visits WHERE id = ?", (visit_id,))
    visit = cur.fetchone()
    if not visit:
        conn.close()
        return JSONResponse({"ok": False, "message": "予定が見つかりません。"}, status_code=404)
    conflict = visit_conflict(conn, visit["staff_id"], new_date, visit["visit_time"], visit["end_time"], exclude_id=visit_id)
    if conflict:
        conn.close()
        return JSONResponse({"ok": False, "message": conflict}, status_code=409)
    cur.execute("UPDATE visits SET visit_date = ? WHERE id = ?", (new_date, visit_id))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True, "date": new_date})


@app.get(
    "/admin/calendar",
    response_class=HTMLResponse
)
def admin_calendar(
    year: int = None,
    month: int = None,
    copy_result: int = None,
    copy_skipped: int = 0,
    deleted_next_week: int = None,
    staff_id: int = 0,
    service_type: str = "all"
):

    today = date.today()

    year = year or today.year
    month = month or today.month

    first_day = date(year, month, 1)

    if month == 12:
        next_month_date = date(year + 1, 1, 1)
    else:
        next_month_date = date(year, month + 1, 1)

    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1

    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM staff ORDER BY name")
    staff_filter_list = cur.fetchall()
    staff_filter_options = "".join(f'<option value="{st["id"]}" {"selected" if staff_id == st["id"] else ""}>{html.escape(st["name"])}</option>' for st in staff_filter_list)

    cur.execute("""
        SELECT
            visits.*,
            staff.name AS staff_name,
            staff.calendar_color AS staff_color,
            clients.name AS client_name
        FROM visits
        JOIN staff
        ON visits.staff_id = staff.id
        LEFT JOIN clients
        ON visits.client_id = clients.id
        WHERE visits.visit_date >= ?
        AND visits.visit_date < ?
        AND (? = 0 OR visits.staff_id = ?)
        AND (? = 'all' OR COALESCE(visits.service_type, '看護') = ?)
        ORDER BY visits.visit_date, visits.visit_time
    """, (
        first_day.isoformat(),
        next_month_date.isoformat(),
        staff_id, staff_id, service_type, service_type
    ))

    visits = cur.fetchall()

    conn.close()

    visit_by_date = {}

    for visit in visits:

        visit_by_date.setdefault(
            visit["visit_date"],
            []
        ).append(visit)

    cal = calendar.Calendar(firstweekday=0)

    calendar_html = ""

    for week in cal.monthdayscalendar(year, month):

        calendar_html += "<tr>"

        for day in week:

            if day == 0:

                calendar_html += """
                <td class="empty"></td>
                """

                continue

            current_date = date(
                year,
                month,
                day
            ).isoformat()

            today_class = ""

            if current_date == today.isoformat():
                today_class = "today-cell"

            events = ""

            for visit in visit_by_date.get(
                current_date,
                []
            ):

                client_name = (
                    visit["client_name"]
                    or visit["patient_name"]
                )

                is_off = bool(visit["is_day_off"])
                event_style = "border-left-color:#dc2626;background:#fee2e2;color:#991b1b" if is_off else f"border-left-color:{html.escape(visit['staff_color'] or '#2563eb')};background:{html.escape(visit['staff_color'] or '#2563eb')}18"
                events += f"""
                <a
                    href="/admin/visits/{visit["id"]}/edit"
                    class="calendar-event {"day-off" if is_off else ""}"
                    draggable="true" data-visit-id="{visit['id']}"
                    style="{event_style}"
                >

                    <strong>
                        {html.escape(visit["visit_time"])}{('〜' + html.escape(visit['end_time'])) if visit['end_time'] else ''}
                    </strong>

                    <span>
                        {html.escape(visit["staff_name"])}
                    </span>

                    <span>
                        {html.escape(client_name)} {"【休み】" if is_off else ""}
                    </span>
                    <span>{html.escape(visit["service_type"] or "看護")}</span>

                </a>
                """

            calendar_html += f"""
            <td class="{today_class}">

                <a
                    href="/admin/visits/add?date={current_date}"
                    style="
                        display:block;
                        text-decoration:none;
                        color:inherit;
                    "
                >

                    <div class="day-number">
                        {day}
                    </div>

                </a>

                {events}

            </td>
            """

        calendar_html += "</tr>"

    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html lang="ja">

    <head>

        <meta charset="UTF-8">

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >

        <title>訪問予定カレンダー</title>

        {CSS}

    </head>

    <body>

    <header>
        <h1>訪問予定カレンダー</h1>
    </header>

    <div class="container">

        {admin_nav()}

        <div class="card">

            <form action="/admin/calendar/copy-this-week" method="post"
                  onsubmit="return confirm('今週（月〜日）の訪問予定を来週の同じ曜日にコピーします。来週に同じ予定がある場合は重複登録しません。続けますか？');"
                  style="display:inline-block; margin-right:10px;">
                <button type="submit" class="success">
                    今週分を来週へコピー
                </button>
            </form>

            <form action="/admin/calendar/delete-next-week" method="post"
                  onsubmit="return confirm('来週（月〜日）の訪問予定をすべて削除します。本当に実行しますか？この操作は取り消せません。');"
                  style="display:inline-block; margin-right:10px;">
                <button type="submit" class="danger">
                    来週分を一括削除
                </button>
            </form>

            {f'<div class="info-box">コピー完了：{copy_result}件を追加しました。重複などでスキップ：{copy_skipped}件。</div>' if copy_result is not None else ''}
            {f'<div class="info-box">来週分を{deleted_next_week}件削除しました。</div>' if deleted_next_week is not None else ''}

            <a href="/admin/calendar/day?date={today.isoformat()}" class="add-link" style="margin-right:8px;">今日のスタッフ別時間割</a>
            <a href="/admin/calendar/week?start_date={(today - timedelta(days=today.weekday())).isoformat()}" class="add-link" style="margin-right:8px;">週間予定・週印刷</a>
            <a
                href="/admin/visits/add"
                class="add-link"
            >
                ＋ 訪問予定を追加
            </a>

            <form method="get" class="filter-row no-print">
                <input type="hidden" name="year" value="{year}"><input type="hidden" name="month" value="{month}">
                <div><label>スタッフ</label><select name="staff_id"><option value="0">全スタッフ</option>{staff_filter_options}</select></div>
                <div><label>業務区分</label><select name="service_type"><option value="all">すべて</option><option value="看護" {"selected" if service_type == "看護" else ""}>看護のみ</option><option value="リハビリ" {"selected" if service_type == "リハビリ" else ""}>リハビリのみ</option></select></div>
                <button type="submit">絞り込む</button><button type="button" class="print-button" onclick="window.print()">印刷／PDF</button>
            </form>

            <div class="calendar-nav">

                <a
                    href="/admin/calendar?year={prev_year}&month={prev_month}&staff_id={staff_id}&service_type={quote(service_type)}"
                >
                    ← 前月
                </a>

                <h2>
                    {year}年{month}月
                </h2>

                <a
                    href="/admin/calendar?year={next_year}&month={next_month}&staff_id={staff_id}&service_type={quote(service_type)}"
                >
                    次月 →
                </a>

            </div>

            <table class="calendar">

                <tr>
                    <th>月</th>
                    <th>火</th>
                    <th>水</th>
                    <th>木</th>
                    <th>金</th>
                    <th>土</th>
                    <th>日</th>
                </tr>

                {calendar_html}

            </table>

            <p class="small">
                日付をクリックすると、その日の訪問予定を追加できます。
                <br>
                登録済みの予定をクリックすると編集できます。
            </p>

        </div>

    </div>
    <script>
    let draggedVisitId = null;
    document.querySelectorAll('.calendar-event[draggable="true"]').forEach(el => {{
      el.addEventListener('dragstart', e => {{ draggedVisitId = el.dataset.visitId; e.dataTransfer.setData('text/plain', draggedVisitId); }});
    }});
    document.querySelectorAll('.calendar td:not(.empty)').forEach(cell => {{
      cell.addEventListener('dragover', e => {{ e.preventDefault(); cell.classList.add('drop-target'); }});
      cell.addEventListener('dragleave', () => cell.classList.remove('drop-target'));
      cell.addEventListener('drop', async e => {{
        e.preventDefault(); cell.classList.remove('drop-target');
        const id = e.dataTransfer.getData('text/plain') || draggedVisitId;
        const dateLink = cell.querySelector('a[href*="/admin/visits/add?date="]');
        if (!id || !dateLink) return;
        const newDate = new URL(dateLink.href).searchParams.get('date');
        const body = new URLSearchParams({{new_date:newDate}});
        const res = await fetch('/admin/visits/' + id + '/move', {{method:'POST', headers:{{'Content-Type':'application/x-www-form-urlencoded'}}, body}});
        const data = await res.json();
        if (data.ok) location.reload(); else alert(data.message || '移動できませんでした');
      }});
    }});
    </script>
    </body>
    </html>
    """)



@app.get("/admin/calendar/day", response_class=HTMLResponse)
def admin_calendar_day(date: str = "", service_type: str = "all"):
    """スタッフを横軸、20分刻みの時刻を縦軸にした日別時間割。"""
    selected_date = date or datetime.now().date().isoformat()
    try:
        selected_date = datetime.strptime(selected_date, "%Y-%m-%d").date().isoformat()
    except ValueError:
        selected_date = datetime.now().date().isoformat()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, calendar_color, staff_number
        FROM staff
        WHERE COALESCE(show_in_schedule, 1) = 1
        ORDER BY CASE WHEN staff_number IS NULL THEN 1 ELSE 0 END,
                 staff_number, name
    """)
    staff_list = cur.fetchall()
    cur.execute("""
        SELECT visits.*, staff.name AS staff_name,
               COALESCE(clients.name, visits.patient_name) AS client_name
        FROM visits
        JOIN staff ON staff.id = visits.staff_id
        LEFT JOIN clients ON clients.id = visits.client_id
        WHERE visits.visit_date = ?
          AND (? = 'all' OR COALESCE(visits.service_type, '看護') = ?)
        ORDER BY visits.visit_time, visits.end_time
    """, (selected_date, service_type, service_type))
    visits = cur.fetchall()
    conn.close()

    by_staff_and_time = {}
    for visit in visits:
        try:
            start_time = datetime.strptime(visit["visit_time"][:5], "%H:%M")
            slot = (start_time.hour * 60 + start_time.minute - 7 * 60) // 20
        except (ValueError, TypeError):
            continue
        if 0 <= slot < 36:
            by_staff_and_time.setdefault((visit["staff_id"], slot), []).append(visit)

    rows = []
    for slot in range(36):
        total_minutes = 7 * 60 + slot * 20
        label = f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"
        cells = [f'<th class="time-label">{label}</th>']
        for staff in staff_list:
            color = html.escape(staff["calendar_color"] or "#2563eb")
            entries = by_staff_and_time.get((staff["id"], slot), [])
            cards = []
            for visit in entries:
                end = ("〜" + html.escape(visit["end_time"]) if visit["end_time"] else "")
                off = bool(visit["is_day_off"])
                card_color = "#dc2626" if off else color
                card_bg = "#fee2e2" if off else color + "18"
                cards.append(
                    f'<a class="timeline-event {"day-off" if off else ""}" href="/admin/visits/{visit["id"]}/edit" '
                    f'style="border-left:4px solid {card_color};background:{card_bg}">'
                    f'<strong>{html.escape(visit["visit_time"])}{end}</strong>'
                    f'<span>{html.escape(visit["client_name"] or "利用者名未登録")} {"【休み】" if off else ""}</span>'
                    f'<small>{html.escape(visit["service_type"] or "看護")} / {html.escape(visit["address"] or "")}</small></a>'
                )
            cells.append(f'<td>{"".join(cards)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")

    staff_headers = "".join(
        f'<th style="border-top:5px solid {html.escape(staff["calendar_color"] or "#2563eb")}">{html.escape(staff["name"])}</th>'
        for staff in staff_list
    )
    if not staff_list:
        staff_headers = '<th>スタッフが登録されていません</th>'

    return HTMLResponse(f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>スタッフ別時間割</title>{CSS}
<style>
.timeline-wrap{{overflow:auto;max-width:100%;background:white;border:1px solid #d1d5db;border-radius:10px}}
.timeline{{border-collapse:collapse;table-layout:fixed;min-width:max-content;width:100%}}
.timeline th,.timeline td{{border:1px solid #d1d5db;padding:4px;vertical-align:top;min-width:150px}}
.timeline thead th{{position:sticky;top:0;background:#f3f4f6;z-index:2;text-align:center}}
.timeline .time-label{{position:sticky;left:0;z-index:1;min-width:62px;width:62px;background:#f9fafb;text-align:center;font-size:12px;font-weight:500}}
.timeline td{{height:42px;min-width:170px}}
.timeline-event{{display:flex;flex-direction:column;gap:3px;text-decoration:none;color:#172033;border-radius:5px;padding:5px;margin:2px 0;font-size:12px;overflow-wrap:anywhere}}
.timeline-event small{{color:#4b5563}}
@media(max-width:700px){{.timeline th,.timeline td{{min-width:140px}}.timeline .time-label{{min-width:52px;width:52px}}}}
</style></head><body>
<header><h1>スタッフ別・時間割</h1></header>
<div class="container">{admin_nav()}
<div class="card"><form method="get" class="filter-row"><div><label>日付</label><input type="date" name="date" value="{selected_date}"></div><div><label>業務区分</label><select name="service_type"><option value="all">すべて</option><option value="看護" {"selected" if service_type == "看護" else ""}>看護のみ</option><option value="リハビリ" {"selected" if service_type == "リハビリ" else ""}>リハビリのみ</option></select></div><button type="submit">表示</button><button type="button" class="print-button" onclick="window.print()">印刷／PDF</button></form>
<p class="no-print"><a href="/admin/calendar">← 月カレンダーへ戻る</a></p>
<p class="small">時間は7:00〜19:00、20分刻みです。予定をタップすると編集できます。</p></div>
<div class="timeline-wrap"><table class="timeline"><thead><tr><th class="time-label">時刻</th>{staff_headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
</div></body></html>""")

# =========================================================
# アプリ起動
# =========================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000
    )
