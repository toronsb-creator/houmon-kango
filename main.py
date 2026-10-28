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
