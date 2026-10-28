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
    </div>
    """


def staff_nav(staff_id):
    return f"""
    <div class="nav">
        <a href="/staff/{staff_id}">ホーム</a>
        <a href="/staff/{staff_id}/calendar">カレンダー</a>
        <a href="/staff/{staff_id}/visits">訪問予定</a>
        <a href="/staff/{staff_id}/leave">休暇申請</a>
        <a href="/staff/{staff_id}/requests">申請状況</a>
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
            {html.escape(visit["address"] or "")}<br>
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
    month: int = None
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
        ORDER BY visits.visit_date, visits.visit_time
    """, (
        staff_id,
        first_day.isoformat(),
        next_month_date.isoformat()
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

                events += f"""
                <div class="event" style="border-left-color:{html.escape(visit['staff_color'] or '#2563eb')};background:{html.escape(visit['staff_color'] or '#2563eb')}18">
                    <strong>
                        {html.escape(visit["visit_time"])}{('〜' + html.escape(visit['end_time'])) if visit['end_time'] else ''}
                    </strong>
                    <br>
                    {html.escape(client_name)}
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

                <a href="/staff/{staff_id}/calendar?year={prev_year}&month={prev_month}">
                    ← 前月
                </a>

                <h2>
                    {year}年{month}月
                </h2>

                <a href="/staff/{staff_id}/calendar?year={next_year}&month={next_month}">
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

    rows = ""

    for i, visit in enumerate(visits):

        client_name = visit["client_name"] or visit["patient_name"]
        current_address = visit["address"] or visit["client_address"] or ""

        destination_url = (
            "https://www.google.com/maps/dir/?api=1"
            f"&destination={quote(current_address)}"
            "&travelmode=driving"
        ) if current_address else ""

        next_visit = None
        if i + 1 < len(visits):
            candidate = visits[i + 1]
            if candidate["visit_date"] == visit["visit_date"]:
                next_visit = candidate

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

        phone_html = make_tel_link(visit["client_phone"] or "", "📞 " + (visit["client_phone"] or "電話番号未登録"))
        rows += f"""
        <tr>
            <td>{html.escape(visit["visit_date"])}</td>
            <td>{html.escape(visit["visit_time"])}</td>
            <td>{html.escape(client_name)}</td>
            <td>{phone_html}</td>
            <td>{html.escape(current_address)}</td>
            <td>{html.escape(visit["memo"] or "")}</td>
            <td>{route_buttons or '<span class="small">住所が登録されていません</span>'}</td>
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
        <style>
            .route-button {{
                display: inline-block; margin: 3px; padding: 8px 12px;
                background: #1677c8; color: white; text-decoration: none;
                border-radius: 7px; font-weight: 600; font-size: 13px;
            }}
            .route-button:hover {{ opacity: 0.85; }}
            .next-route-button {{ background: #16a34a; }}
        </style>
    </head>
    <body>
    <header><h1>自分の訪問予定</h1></header>
    <div class="container">
        {staff_nav(staff_id)}
        <div class="card">
            <p class="small">
                「ここへ行く」は現在地から訪問先まで、「次の患者へ」は現在の訪問先から同日の次の訪問先までのルートをGoogleマップで開きます。
            </p>
            <table>
                <tr>
                    <th>日付</th><th>時間</th><th>利用者</th><th>電話</th>
                    <th>訪問先</th><th>メモ</th><th>ルート</th>
                </tr>
                {rows}
            </table>
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

                <label>理由</label>
                <textarea name="reason" rows="4"></textarea>

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
    reason: str = Form("")
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO leave_requests
        (staff_id, start_date, end_date, reason, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        staff_id,
        start_date,
        end_date,
        reason,
        "申請中",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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

    cur.execute("""
        SELECT *
        FROM leave_requests
        WHERE staff_id = ?
        ORDER BY id DESC
    """, (staff_id,))

    requests = cur.fetchall()

    conn.close()

    rows = ""

    for request in requests:

        rows += f"""
        <tr>
            <td>{html.escape(request["start_date"])}</td>
            <td>{html.escape(request["end_date"])}</td>
            <td>{html.escape(request["reason"] or "")}</td>
            <td>{html.escape(request["status"])}</td>
            <td>{html.escape(request["reject_reason"] or "")}</td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="5">
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
        <title>申請状況</title>
        {CSS}
    </head>

    <body>

    <header>
        <h1>申請状況</h1>
    </header>

    <div class="container">

        {staff_nav(staff_id)}

        <div class="card">

            <table>

                <tr>
                    <th>開始日</th>
                    <th>終了日</th>
                    <th>理由</th>
                    <th>状態</th>
                    <th>却下理由</th>
                </tr>

                {rows}

            </table>

        </div>

    </div>

    </body>
    </html>
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
            <td colspan="8">
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

            <table>

                <tr>
                    <th>ID</th>
                    <th>スタッフ</th>
                    <th>開始日</th>
                    <th>終了日</th>
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
        ORDER BY id DESC
    """)

    staff_list = cur.fetchall()

    conn.close()

    rows = ""

    for staff in staff_list:

        rows += f"""
        <tr>

            <td>{staff["id"]}</td>

            <td>{html.escape(staff["name"])}</td>

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

                <label>名前</label>
                <input type="text" name="name" required>

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
                    <th>ID</th>
                    <th>名前</th>
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
                    <label>名前</label>
                    <input type="text" name="name" value="{html.escape(staff['name'] or '', quote=True)}" required>

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
    calendar_color: str = Form("#2563eb")
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
                UPDATE staff SET name = ?, email = ?, password = ?, phone = ?, address = ?, calendar_color = ?
                WHERE id = ?
            """, (name.strip(), email.strip(), password, phone.strip(), address.strip(), calendar_color, staff_id))
        else:
            cur.execute("""
                UPDATE staff SET name = ?, email = ?, phone = ?, address = ?, calendar_color = ?
                WHERE id = ?
            """, (name.strip(), email.strip(), phone.strip(), address.strip(), calendar_color, staff_id))
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
    address: str = Form("")
):

    conn = get_db()
    cur = conn.cursor()

    try:

        cur.execute("""
            INSERT INTO staff
            (name, email, password, phone, address)
            VALUES (?, ?, ?, ?, ?)
        """, (
            name,
            email,
            password,
            phone,
            address
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
        <tr>

            <td>{client["id"]}</td>

            <td>{html.escape(client["name"])}</td>

            <td>{make_tel_link(client["phone"] or "")}</td>

            <td>{html.escape(client["address"] or "")}</td>

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

                <label>電話番号</label>
                <input type="tel" name="phone">

                <label>住所</label>
                <input type="text" name="address">

                <label>生年月日（和暦）</label>
                <input type="text" name="birth_date" placeholder="例：平成10年4月1日 または 1998-04-01">
                <small>和暦・西暦どちらでも入力できます。</small>

                <label>メモ</label>
                <textarea name="memo" rows="4"></textarea>

                <button type="submit">
                    利用者を登録
                </button>

            </form>

        </div>

        <div class="card">

            <h2>登録済み利用者</h2>

            <table>

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

                <label>電話番号</label>

                <input
                    type="tel"
                    name="phone"
                    value="{html.escape(client["phone"] or "")}"
                >

                <label>住所</label>

                <input
                    type="text"
                    name="address"
                    value="{html.escape(client["address"] or "")}"
                >

                <label>生年月日（和暦）</label>
                <input type="text" name="birth_date" value="{html.escape(format_wareki(client["birth_date"] or ""), quote=True)}" placeholder="例：平成10年4月1日 または 1998-04-01">
                <small>和暦・西暦どちらでも入力できます。</small>

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

            <td>{html.escape(client_name)}</td>

            <td>{html.escape(visit["address"] or "")}</td>

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

            <table>

                <tr>
                    <th>日付</th>
                    <th>時間</th>
                    <th>スタッフ</th>
                    <th>利用者</th>
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
        SELECT id, name
        FROM staff
        ORDER BY name
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

        staff_options += f"""
        <option value="{staff["id"]}">
            {html.escape(staff["name"])}
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

                <label>スタッフ</label>

                <select name="staff_id" required>
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
    memo: str = Form("")
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
            end_time
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        staff_id,
        visit_date,
        visit_time,
        patient_name,
        address,
        memo,
        client_id,
        end_time
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
        SELECT id, name
        FROM staff
        ORDER BY name
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

        staff_options += f"""
        <option
            value="{staff["id"]}"
            {selected}
        >
            {html.escape(staff["name"])}
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

                <label>スタッフ</label>

                <select name="staff_id" required>
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
    memo: str = Form("")
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
            client_id = ?
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
# 管理者：先週の訪問予定を今週へコピー
# =========================================================

@app.post("/admin/calendar/copy-last-week")
def copy_last_week():
    today = date.today()
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday - timedelta(days=1)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT staff_id, visit_date, visit_time, end_time, patient_name,
               address, memo, client_id
        FROM visits
        WHERE visit_date >= ? AND visit_date <= ?
        ORDER BY visit_date, visit_time, id
    """, (last_monday.isoformat(), last_sunday.isoformat()))
    previous_visits = cur.fetchall()

    copied = 0
    skipped = 0

    try:
        for visit in previous_visits:
            source_date = date.fromisoformat(visit["visit_date"])
            target_date = source_date + timedelta(days=7)

            # 同じスタッフ・日付・時間・利用者の予定があれば二重登録しない
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
                      AND (client_id IS NULL)
                      AND patient_name = ?
                    LIMIT 1
                """, (visit["staff_id"], target_date.isoformat(),
                      visit["visit_time"], visit["patient_name"]))

            if cur.fetchone():
                skipped += 1
                continue

            cur.execute("""
                INSERT INTO visits
                    (staff_id, visit_date, visit_time, end_time, patient_name,
                     address, memo, client_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                visit["staff_id"], target_date.isoformat(),
                visit["visit_time"], visit["end_time"] or "", visit["patient_name"],
                visit["address"] or "", visit["memo"] or "",
                visit["client_id"]
            ))
            copied += 1

        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return RedirectResponse(
        f"/admin/calendar?copy_result={copied}&copy_skipped={skipped}",
        status_code=303
    )


# =========================================================
# 管理者カレンダー
# =========================================================

@app.get(
    "/admin/calendar",
    response_class=HTMLResponse
)
def admin_calendar(
    year: int = None,
    month: int = None,
    copy_result: int = None,
    copy_skipped: int = 0
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
        ORDER BY visits.visit_date, visits.visit_time
    """, (
        first_day.isoformat(),
        next_month_date.isoformat()
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

                events += f"""
                <a
                    href="/admin/visits/{visit["id"]}/edit"
                    class="calendar-event"
                    style="border-left-color:{html.escape(visit['staff_color'] or '#2563eb')};background:{html.escape(visit['staff_color'] or '#2563eb')}18"
                >

                    <strong>
                        {html.escape(visit["visit_time"])}{('〜' + html.escape(visit['end_time'])) if visit['end_time'] else ''}
                    </strong>

                    <span>
                        {html.escape(visit["staff_name"])}
                    </span>

                    <span>
                        {html.escape(client_name)}
                    </span>

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

            <form action="/admin/calendar/copy-last-week" method="post"
                  onsubmit="return confirm('先週（月〜日）の訪問予定を今週の同じ曜日にコピーします。続けますか？');"
                  style="display:inline-block; margin-right:10px;">
                <button type="submit" class="success">
                    先週分を今週へコピー
                </button>
            </form>

            {f'<div class="info-box">コピー完了：{copy_result}件を追加しました。重複などでスキップ：{copy_skipped}件。</div>' if copy_result is not None else ''}

            <a href="/admin/calendar/day?date={today.isoformat()}" class="add-link" style="margin-right:8px;">今日のスタッフ別時間割</a>
            <a
                href="/admin/visits/add"
                class="add-link"
            >
                ＋ 訪問予定を追加
            </a>

            <div class="calendar-nav">

                <a
                    href="/admin/calendar?year={prev_year}&month={prev_month}"
                >
                    ← 前月
                </a>

                <h2>
                    {year}年{month}月
                </h2>

                <a
                    href="/admin/calendar?year={next_year}&month={next_month}"
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

    </body>
    </html>
    """)



@app.get("/admin/calendar/day", response_class=HTMLResponse)
def admin_calendar_day(date: str = ""):
    """スタッフを横軸、20分刻みの時刻を縦軸にした日別時間割。"""
    selected_date = date or datetime.now().date().isoformat()
    try:
        selected_date = datetime.strptime(selected_date, "%Y-%m-%d").date().isoformat()
    except ValueError:
        selected_date = datetime.now().date().isoformat()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name, calendar_color FROM staff ORDER BY name")
    staff_list = cur.fetchall()
    cur.execute("""
        SELECT visits.*, staff.name AS staff_name,
               COALESCE(clients.name, visits.patient_name) AS client_name
        FROM visits
        JOIN staff ON staff.id = visits.staff_id
        LEFT JOIN clients ON clients.id = visits.client_id
        WHERE visits.visit_date = ?
        ORDER BY visits.visit_time, visits.end_time
    """, (selected_date,))
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
                cards.append(
                    f'<a class="timeline-event" href="/admin/visits/{visit["id"]}/edit" '
                    f'style="border-left:4px solid {color};background:{color}18">'
                    f'<strong>{html.escape(visit["visit_time"])}{end}</strong>'
                    f'<span>{html.escape(visit["client_name"] or "利用者名未登録")}</span>'
                    f'<small>{html.escape(visit["address"] or "")}</small></a>'
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
<div class="card"><form method="get"><label>日付</label><input type="date" name="date" value="{selected_date}"><button type="submit">表示</button></form>
<p><a href="/admin/calendar">← 月カレンダーへ戻る</a></p>
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
