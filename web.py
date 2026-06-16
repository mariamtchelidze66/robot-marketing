"""Safhe web-e zende:
  - login ba ramz
  - jadval-e qabel-e VIRAYESH (har radif inline edit + zakhire/hazf)
  - taghir-e ramz-e admin az dakhel-e site
  - download Excel
"""
from flask import Flask, request, Response, send_file, redirect, url_for
import html
import db
import config
import exporter

app = Flask(__name__)

EDIT_KEYS = [(k, fa) for k, fa in db.COLUMNS if k not in ("recorder", "editor")]


def _authed() -> bool:
    pw = db.get_web_password()
    return request.cookies.get("auth") == pw or \
        request.values.get("pw") == pw


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


LOGIN_PAGE = """<!doctype html><html lang="fa" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ورود</title><style>
body{font-family:Tahoma,sans-serif;background:#0f1720;color:#eee;display:flex;
height:100vh;align-items:center;justify-content:center;margin:0}
form{background:#1b2735;padding:30px;border-radius:12px;min-width:280px}
input{width:100%;padding:10px;margin:8px 0;border-radius:8px;border:1px solid #345;
background:#0f1720;color:#eee;box-sizing:border-box}
button{width:100%;padding:10px;background:#1F4E78;color:#fff;border:0;border-radius:8px;
cursor:pointer;font-size:15px}h2{text-align:center}.err{color:#f77;text-align:center}
</style></head><body><form method="get" action="/">
<h2>🎰 داشبورد کازینو</h2>{err}
<input type="password" name="pw" placeholder="رمز را وارد کنید" autofocus>
<button>ورود</button></form></body></html>"""

STYLE = """<style>
body{font-family:Tahoma,sans-serif;background:#0f1720;color:#eee;margin:0;padding:16px}
h2{margin:0 0 12px}.bar{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
a.btn,button.btn{background:#1F7A3A;color:#fff;padding:8px 14px;border-radius:8px;
text-decoration:none;border:0;cursor:pointer;font-size:14px}
button.del{background:#a33}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #2a3a4d;padding:4px 6px;text-align:center;white-space:nowrap}
th{background:#1F4E78;position:sticky;top:0}
tr:nth-child(even){background:#16212e}.wrap{overflow:auto;max-height:70vh}
input.cell{width:90px;background:#0f1720;color:#eee;border:1px solid #345;border-radius:6px;
padding:4px}.count{color:#9bd}
.panel{background:#1b2735;padding:14px;border-radius:10px;margin-bottom:14px;max-width:420px}
.panel input{padding:8px;border-radius:8px;border:1px solid #345;background:#0f1720;
color:#eee;margin:4px 0;width:100%;box-sizing:border-box}
.ok{color:#7d7;margin:6px 0}.err{color:#f77;margin:6px 0}
details summary{cursor:pointer;color:#9bd;margin-bottom:8px}
.addp{max-width:100%}
.addform{display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end}
.addform label{display:flex;flex-direction:column;font-size:12px;color:#9bd;gap:2px}
.addform input{width:110px;padding:6px;border-radius:6px;border:1px solid #345;
background:#0f1720;color:#eee}
</style>"""


def _dashboard(msg_ok="", msg_err=""):
    pw = db.get_web_password()
    rows = db.all_records()
    custom = db.list_custom_fields()  # [(cfX, label)]
    edit_cols = EDIT_KEYS + custom
    headers = "".join(f"<th>{html.escape(fa)}</th>" for _, fa in edit_cols)
    body = []
    forms = []
    for i, rec in enumerate(rows, 1):
        rid = rec["id"]
        fid = f"f{rid}"
        extra = db.record_extra(rec)
        vals = {**{k: rec.get(k) for k, _ in EDIT_KEYS},
                **{k: extra.get(k) for k, _ in custom}}
        cells = "".join(
            f'<td><input class="cell" form="{fid}" name="{k}" value="{_esc(vals.get(k))}"></td>'
            for k, _ in edit_cols
        )
        meta = f'<td>{_esc(rec.get("recorder"))}</td><td>{_esc(rec.get("editor"))}</td>'
        body.append(
            f'<tr><td>{i}</td>{cells}{meta}'
            f'<td><button class="btn" form="{fid}" type="submit">💾</button></td>'
            f'<td><button class="btn del" form="{fid}" formaction="/delete/{rid}" '
            f'onclick="return confirm(\'حذف ردیف #{rid}؟\')">🗑</button></td></tr>'
        )
        # form-e voabaste be in radif (input-ha ba form= behesh vasl-an)
        forms.append(f'<form id="{fid}" method="post" action="/update/{rid}"></form>')
    table_rows = "".join(body) or '<tr><td colspan="20">هنوز رکوردی نیست</td></tr>'
    forms_html = "".join(forms)

    ok_html = f'<div class="ok">{html.escape(msg_ok)}</div>' if msg_ok else ""
    err_html = f'<div class="err">{html.escape(msg_err)}</div>' if msg_err else ""

    # form-e «افزودن ردیف جدید دستی»
    add_inputs = "".join(
        f'<label>{html.escape(fa)}<input name="{k}"></label>' for k, fa in edit_cols
    )

    page = f"""<!doctype html><html lang="fa" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>داشبورد کازینو</title>{STYLE}</head><body>
<div class="bar"><h2>🎰 داشبورد کازینو</h2>
<span class="count">({len(rows)} رکورد)</span>
<a class="btn" href="/">🔄 بروزرسانی</a>
<a class="btn" href="/export">⬇ دانلود Excel</a></div>
{ok_html}{err_html}
<details class="panel addp"><summary>➕ افزودن ردیف جدید (دستی)</summary>
<form method="post" action="/add" class="addform">{add_inputs}
<button class="btn" type="submit">افزودن ردیف</button></form></details>
<details class="panel"><summary>🔑 تغییر رمز داشبورد</summary>
<form method="post" action="/setpass">
<input type="password" name="cur" placeholder="رمز فعلی" required>
<input type="password" name="new" placeholder="رمز جدید" required>
<button class="btn" type="submit">تغییر رمز</button></form></details>
<div class="wrap"><table><thead><tr><th>ردیف</th>{headers}
<th>ثبت‌کننده</th><th>ویرایش‌کننده</th><th>ذخیره</th><th>حذف</th></tr></thead>
<tbody>{table_rows}</tbody></table></div>
{forms_html}</body></html>"""

    resp = Response(page)
    if request.values.get("pw") == pw:
        resp.set_cookie("auth", pw, max_age=86400)
    return resp


@app.route("/")
def index():
    if not _authed():
        err = '<p class="err">رمز اشتباه است</p>' if request.args.get("pw") else ""
        return LOGIN_PAGE.replace("{err}", err)
    return _dashboard()


@app.route("/update/<int:rid>", methods=["POST"])
def update(rid):
    if not _authed():
        return redirect(url_for("index"))
    data = {k: request.form.get(k, "") for k, _ in EDIT_KEYS}
    custom = db.list_custom_fields()
    extra = {k: request.form.get(k, "") for k, _ in custom}
    db.update_record(rid, data, editor="مدیر (وب)", extra=extra or None)
    return _dashboard(msg_ok=f"ردیف #{rid} ذخیره شد.")


@app.route("/add", methods=["POST"])
def add():
    if not _authed():
        return redirect(url_for("index"))
    data = {k: request.form.get(k, "").strip() for k, _ in EDIT_KEYS}
    custom = db.list_custom_fields()
    extra = {k: request.form.get(k, "").strip() for k, _ in custom}
    extra = {k: v for k, v in extra.items() if v}
    # agar hame khali bud, chizi sabt nakon
    if not any(data.values()) and not extra:
        return _dashboard(msg_err="حداقل یک فیلد را پر کن.")
    rid = db.insert_record(data, recorder="مدیر (وب)", extra=extra)
    return _dashboard(msg_ok=f"ردیف #{rid} دستی اضافه شد.")


@app.route("/delete/<int:rid>", methods=["POST"])
def delete(rid):
    if not _authed():
        return redirect(url_for("index"))
    db.delete_record(rid)
    return _dashboard(msg_ok=f"ردیف #{rid} حذف شد.")


@app.route("/setpass", methods=["POST"])
def setpass():
    if not _authed():
        return redirect(url_for("index"))
    cur = request.form.get("cur", "")
    new = request.form.get("new", "").strip()
    if cur != db.get_web_password():
        return _dashboard(msg_err="رمز فعلی اشتباه است.")
    if not new:
        return _dashboard(msg_err="رمز جدید خالی است.")
    db.set_web_password(new)
    resp = _dashboard(msg_ok="رمز عوض شد. دفعهٔ بعد با رمز جدید وارد شو.")
    resp.set_cookie("auth", new, max_age=86400)
    return resp


@app.route("/export")
def export():
    if not _authed():
        return redirect(url_for("index"))
    path = exporter.build_xlsx()
    return send_file(path, as_attachment=True, download_name="robot-marketing.xlsx")


def run():
    db.init_db()
    app.run(host=config.WEB_HOST, port=config.WEB_PORT)


if __name__ == "__main__":
    run()
