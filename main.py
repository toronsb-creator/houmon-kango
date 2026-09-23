from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
import sqlite3
from datetime import date, datetime
import calendar
import html
import os
from urllib.parse import quote

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get(
        "VISIT_NURSING_SESSION_SECRET",
        "CHANGE_THIS_SESSION_SECRET"
    ),
    max_age=60 * 60 * 24 * 7,
    https_only=False,
    same_site="lax"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "database.db")

def hash_password(password):
    import hashlib
    return hashlib.sha256(
        password.encode("utf-8")
    ).hexdigest()

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
    if not column_exists(conn, "staff", "phone"):
        cur.execute("""
            ALTER TABLE staff
            ADD COLUMN phone TEXT DEFAULT ''
        """)
        if not column_exists(conn, "staff", "role"):
            cur.execute("""
                ALTER TABLE staff
                ADD COLUMN role TEXT DEFAULT 'staff'
    """)

    if not column_exists(conn, "staff", "address"):
        cur.execute("""
            ALTER TABLE staff
            ADD COLUMN address TEXT DEFAULT ''
        """)


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

    # -----------------------------------------------------
    # 初期スタッフ
    # -----------------------------------------------------

    cur.execute("SELECT COUNT(*) FROM staff")
    count = cur.fetchone()[0]

    if count == 0:
        cur.execute("""
            INSERT INTO staff
            (name, email, password, phone, address)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "テストスタッフ",
            "staff@example.com",
            "1234",
            "",
            ""
        ))

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

            <hr>

            <p class="small">
                テスト用<br>
                staff@example.com / 1234
            </p>

            <a href="/admin">
                管理者画面へ
            </a>

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
        SELECT id
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

        events += f"""
        <div class="event">
            <strong>{html.escape(visit["visit_time"])}</strong><br>
            {html.escape(client_name)}<br>
            {html.escape(visit["address"] or "")}
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
            clients.name AS client_name
        FROM visits
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
                <div class="event">
                    <strong>
                        {html.escape(visit["visit_time"])}
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

        rows += f"""
        <tr>
            <td>{html.escape(visit["visit_date"])}</td>
            <td>{html.escape(visit["visit_time"])}</td>
            <td>{html.escape(client_name)}</td>
            <td>{html.escape(current_address)}</td>
            <td>{html.escape(visit["memo"] or "")}</td>
            <td>{route_buttons or '<span class="small">住所が登録されていません</span>'}</td>
        </tr>
        """

    if not rows:
        rows = """
        <tr>
            <td colspan="6">
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
                    <th>日付</th><th>時間</th><th>利用者</th>
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
                </tr>

                {rows}

            </table>

        </div>

    </div>

    </body>
    </html>
    """)


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

            <td>{html.escape(client["phone"] or "")}</td>

            <td>{html.escape(client["address"] or "")}</td>

            <td>{html.escape(client["birth_date"] or "")}</td>

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
                >

                    <button
                        type="submit"
                        class="danger"
                    >
                        削除
                    </button>

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

                <label>電話番号</label>
                <input type="tel" name="phone">

                <label>住所</label>
                <input type="text" name="address">

                <label>生年月日</label>
                <input type="date" name="birth_date">

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
    memo: str = Form("")
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO clients
        (name, phone, address, birth_date, memo)
        VALUES (?, ?, ?, ?, ?)
    """, (
        name,
        phone,
        address,
        birth_date,
        memo
    ))

    conn.commit()
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

                <label>生年月日</label>

                <input
                    type="date"
                    name="birth_date"
                    value="{html.escape(client["birth_date"] or "")}"
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
    memo: str = Form("")
):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE clients
        SET
            name = ?,
            phone = ?,
            address = ?,
            birth_date = ?,
            memo = ?
        WHERE id = ?
    """, (
        name,
        phone,
        address,
        birth_date,
        memo,
        client_id
    ))

    conn.commit()
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
                >

                    <button
                        type="submit"
                        class="danger"
                    >
                        削除
                    </button>

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
        SELECT id, name, phone, address
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

                <input
                    type="time"
                    name="visit_time"
                    required
                >

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
            client_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        staff_id,
        visit_date,
        visit_time,
        patient_name,
        address,
        memo,
        client_id
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
        SELECT id, name, phone, address
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

                <input
                    type="time"
                    name="visit_time"
                    value="{html.escape(visit["visit_time"])}"
                    required
                >

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
            patient_name = ?,
            address = ?,
            memo = ?,
            client_id = ?
        WHERE id = ?
    """, (
        staff_id,
        visit_date,
        visit_time,
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
# 管理者カレンダー
# =========================================================

@app.get(
    "/admin/calendar",
    response_class=HTMLResponse
)
def admin_calendar(
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
                >

                    <strong>
                        {html.escape(visit["visit_time"])}
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



# =========================================================
# スマホアプリ用 API
# =========================================================
# iPhone / Android アプリから利用するためのJSON APIです。
# 本番公開前にHTTPSで運用してください。

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
import jwt
import secrets

JWT_SECRET = os.environ.get("VISIT_NURSING_JWT_SECRET", "CHANGE_THIS_SECRET_BEFORE_PRODUCTION")
JWT_ALGORITHM = "HS256"
api_bearer = HTTPBearer(auto_error=False)

class LoginBody(BaseModel):
    email: str
    password: str

class LeaveBody(BaseModel):
    start_date: str
    end_date: str
    reason: str = ""

class StaffCreateBody(BaseModel):
    name: str
    email: str
    password: str
    phone: str = ""
    address: str = ""
    role: str = "staff"

class ClientBody(BaseModel):
    name: str
    phone: str = ""
    address: str = ""
    birth_date: str = ""
    memo: str = ""

class VisitBody(BaseModel):
    staff_id: int
    visit_date: str
    visit_time: str
    client_id: int
    address: str = ""
    memo: str = ""

def make_token(staff_id: int, role: str):
    return jwt.encode(
        {"sub": str(staff_id), "role": role},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )

def current_user(credentials: HTTPAuthorizationCredentials = Depends(api_bearer)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="ログインが必要です")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        staff_id = int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="認証トークンが無効です")

    conn = get_db()
    staff = conn.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
    conn.close()
    if not staff:
        raise HTTPException(status_code=401, detail="スタッフが見つかりません")
    return staff

def require_admin(staff=Depends(current_user)):
    if staff["role"] != "admin":
        raise HTTPException(status_code=403, detail="管理者権限が必要です")
    return staff

@app.get("/api/health")
def api_health():
    return {"ok": True, "service": "訪問看護システム"}

@app.post("/api/login")
def api_login(body: LoginBody):
    conn = get_db()
    staff = conn.execute("SELECT * FROM staff WHERE email=?", (body.email,)).fetchone()
    conn.close()
    if not staff:
        raise HTTPException(status_code=401, detail="メールアドレスまたはパスワードが違います")

    # 既存DBの平文パスワードにも対応し、ログイン成功時にハッシュ化します。
    stored = staff["password"] or ""
    if stored != body.password and stored != hash_password(body.password):
        raise HTTPException(status_code=401, detail="メールアドレスまたはパスワードが違います")

    if stored == body.password:
        conn = get_db()
        conn.execute("UPDATE staff SET password=? WHERE id=?", (hash_password(body.password), staff["id"]))
        conn.commit()
        conn.close()

    role = staff["role"] if "role" in staff.keys() and staff["role"] else "staff"
    token = make_token(staff["id"], role)
    return {
        "ok": True,
        "token": token,
        "staff": {
            "id": staff["id"],
            "name": staff["name"],
            "email": staff["email"],
            "phone": staff["phone"] or "",
            "address": staff["address"] or "",
            "role": role
        }
    }

@app.get("/api/me")
def api_me(staff=Depends(current_user)):
    return {
        "ok": True,
        "staff": {
            "id": staff["id"], "name": staff["name"], "email": staff["email"],
            "phone": staff["phone"] or "", "address": staff["address"] or "",
            "role": staff["role"] if "role" in staff.keys() and staff["role"] else "staff"
        }
    }

@app.get("/api/my/visits")
def api_my_visits(staff=Depends(current_user)):
    conn = get_db()
    rows = conn.execute("""
        SELECT visits.*, clients.name AS client_name, clients.phone AS client_phone,
               clients.address AS client_address
        FROM visits
        LEFT JOIN clients ON visits.client_id=clients.id
        WHERE visits.staff_id=?
        ORDER BY visit_date, visit_time
    """, (staff["id"],)).fetchall()
    conn.close()

    visits = []
    for i, v in enumerate(rows):
        address = v["address"] or v["client_address"] or ""
        maps_url = ""
        if address:
            maps_url = "https://www.google.com/maps/dir/?api=1&destination=" + quote(address) + "&travelmode=driving"
        next_url = ""
        if i + 1 < len(rows) and rows[i + 1]["visit_date"] == v["visit_date"]:
            next_address = rows[i + 1]["address"] or rows[i + 1]["client_address"] or ""
            if address and next_address:
                next_url = "https://www.google.com/maps/dir/?api=1&origin=" + quote(address) + "&destination=" + quote(next_address) + "&travelmode=driving"
        visits.append({
            "id": v["id"], "date": v["visit_date"], "time": v["visit_time"],
            "client_name": v["client_name"] or v["patient_name"],
            "phone": v["client_phone"] or "", "address": address,
            "memo": v["memo"] or "", "google_maps_url": maps_url,
            "next_google_maps_url": next_url
        })
    return {"ok": True, "visits": visits}

@app.get("/api/my/leave")
def api_my_leave(staff=Depends(current_user)):
    conn = get_db()
    rows = conn.execute("""
        SELECT id,start_date,end_date,reason,status,created_at,reject_reason
        FROM leave_requests WHERE staff_id=? ORDER BY id DESC
    """, (staff["id"],)).fetchall()
    conn.close()
    return {"ok": True, "requests": [dict(r) for r in rows]}

@app.post("/api/my/leave")
def api_my_leave_post(body: LeaveBody, staff=Depends(current_user)):
    if body.end_date < body.start_date:
        raise HTTPException(status_code=400, detail="終了日は開始日以降にしてください")
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO leave_requests(staff_id,start_date,end_date,reason,status,created_at)
        VALUES(?,?,?,?,?,?)
    """, (staff["id"], body.start_date, body.end_date, body.reason, "申請中", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return {"ok": True, "id": rid}

@app.get("/api/clients")
def api_clients(staff=Depends(current_user)):
    conn = get_db()
    rows = conn.execute("SELECT * FROM clients ORDER BY name").fetchall()
    conn.close()
    return {"ok": True, "clients": [dict(r) for r in rows]}

@app.get("/api/clients/{client_id}")
def api_client(client_id: int, staff=Depends(current_user)):
    conn = get_db()
    row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="利用者が見つかりません")
    return {"ok": True, "client": dict(row)}

@app.post("/api/admin/clients")
def api_add_client(body: ClientBody, admin=Depends(require_admin)):
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO clients(name,phone,address,birth_date,memo) VALUES(?,?,?,?,?)
    """, (body.name,body.phone,body.address,body.birth_date,body.memo))
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return {"ok": True, "id": cid}

@app.put("/api/admin/clients/{client_id}")
def api_edit_client(client_id: int, body: ClientBody, admin=Depends(require_admin)):
    conn = get_db()
    cur = conn.execute("""
        UPDATE clients SET name=?,phone=?,address=?,birth_date=?,memo=? WHERE id=?
    """, (body.name,body.phone,body.address,body.birth_date,body.memo,client_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="利用者が見つかりません")
    return {"ok": True}

@app.delete("/api/admin/clients/{client_id}")
def api_delete_client(client_id: int, admin=Depends(require_admin)):
    conn = get_db()
    conn.execute("UPDATE visits SET client_id=NULL WHERE client_id=?", (client_id,))
    cur = conn.execute("DELETE FROM clients WHERE id=?", (client_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="利用者が見つかりません")
    return {"ok": True}

@app.get("/api/admin/staff")
def api_admin_staff(admin=Depends(require_admin)):
    conn = get_db()
    rows = conn.execute("SELECT id,name,email,phone,address,role FROM staff ORDER BY name").fetchall()
    conn.close()
    return {"ok": True, "staff": [dict(r) for r in rows]}

@app.post("/api/admin/staff")
def api_admin_staff_add(body: StaffCreateBody, admin=Depends(require_admin)):
    if body.role not in ("staff", "admin"):
        raise HTTPException(status_code=400, detail="権限が不正です")
    conn = get_db()
    try:
        cur = conn.execute("""
            INSERT INTO staff(name,email,password,phone,address,role)
            VALUES(?,?,?,?,?,?)
        """, (body.name,body.email,hash_password(body.password),body.phone,body.address,body.role))
        conn.commit()
        sid = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="そのメールアドレスはすでに登録されています")
    conn.close()
    return {"ok": True, "id": sid}

@app.get("/api/admin/visits")
def api_admin_visits(admin=Depends(require_admin)):
    conn = get_db()
    rows = conn.execute("""
        SELECT visits.*, staff.name AS staff_name, clients.name AS client_name
        FROM visits JOIN staff ON visits.staff_id=staff.id
        LEFT JOIN clients ON visits.client_id=clients.id
        ORDER BY visit_date,visit_time
    """).fetchall()
    conn.close()
    return {"ok": True, "visits": [dict(r) for r in rows]}

@app.post("/api/admin/visits")
def api_admin_visit_add(body: VisitBody, admin=Depends(require_admin)):
    conn = get_db()
    client = conn.execute("SELECT name,address FROM clients WHERE id=?", (body.client_id,)).fetchone()
    if not client:
        conn.close()
        raise HTTPException(status_code=404, detail="利用者が見つかりません")
    address = body.address or client["address"] or ""
    cur = conn.execute("""
        INSERT INTO visits(staff_id,visit_date,visit_time,patient_name,address,memo,client_id)
        VALUES(?,?,?,?,?,?,?)
    """, (body.staff_id,body.visit_date,body.visit_time,client["name"],address,body.memo,body.client_id))
    conn.commit()
    vid = cur.lastrowid
    conn.close()
    return {"ok": True, "id": vid}

@app.put("/api/admin/visits/{visit_id}")
def api_admin_visit_edit(visit_id: int, body: VisitBody, admin=Depends(require_admin)):
    conn = get_db()
    client = conn.execute("SELECT name,address FROM clients WHERE id=?", (body.client_id,)).fetchone()
    if not client:
        conn.close()
        raise HTTPException(status_code=404, detail="利用者が見つかりません")
    address = body.address or client["address"] or ""
    cur = conn.execute("""
        UPDATE visits SET staff_id=?,visit_date=?,visit_time=?,patient_name=?,address=?,memo=?,client_id=?
        WHERE id=?
    """, (body.staff_id,body.visit_date,body.visit_time,client["name"],address,body.memo,body.client_id,visit_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="訪問予定が見つかりません")
    return {"ok": True}

@app.delete("/api/admin/visits/{visit_id}")
def api_admin_visit_delete(visit_id: int, admin=Depends(require_admin)):
    conn = get_db()
    cur = conn.execute("DELETE FROM visits WHERE id=?", (visit_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="訪問予定が見つかりません")
    return {"ok": True}

@app.get("/api/admin/leave")
def api_admin_leave(admin=Depends(require_admin)):
    conn = get_db()
    rows = conn.execute("""
        SELECT leave_requests.*,staff.name AS staff_name
        FROM leave_requests JOIN staff ON leave_requests.staff_id=staff.id
        ORDER BY leave_requests.id DESC
    """).fetchall()
    conn.close()
    return {"ok": True, "requests": [dict(r) for r in rows]}

@app.post("/api/admin/leave/{request_id}/approve")
def api_admin_leave_approve(request_id: int, admin=Depends(require_admin)):
    conn = get_db()
    cur = conn.execute("UPDATE leave_requests SET status='承認',reject_reason='' WHERE id=?", (request_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="申請が見つかりません")
    return {"ok": True}

class RejectLeaveBody(BaseModel):
    reject_reason: str

@app.post("/api/admin/leave/{request_id}/reject")
def api_admin_leave_reject(request_id: int, body: RejectLeaveBody, admin=Depends(require_admin)):
    if not body.reject_reason.strip():
        raise HTTPException(status_code=400, detail="却下理由を入力してください")
    conn = get_db()
    cur = conn.execute("""
        UPDATE leave_requests SET status='却下',reject_reason=? WHERE id=?
    """, (body.reject_reason.strip(),request_id))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="申請が見つかりません")
    return {"ok": True}

# =========================================================
# アプリ起動
# =========================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000))
    )