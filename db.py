"""SQLite layer: employees + records (yek jadval-e vahed) + field-haye delkhah."""
import sqlite3
import json
from contextlib import contextmanager
import config

# Sotoon-haye jadval (kelid-e english -> onvan-e farsi baraye khorooji)
COLUMNS = [
    ("employee_name", "نام کارمند"),
    ("date", "تاریخ"),
    ("deposit_rial", "واریزی ریالی"),
    ("tether", "تتر"),
    ("player_name", "اسم پلیر"),
    ("expenses", "هزینه‌ها"),
    ("invoice", "فاکتور"),
    ("food", "غذا"),
    ("lunch", "ناهار"),
    ("dinner", "شام"),
    ("hotel", "هتل"),
    ("recorder", "ثبت‌کننده"),
    ("editor", "ویرایش‌کننده"),
]
DATA_KEYS = [k for k, _ in COLUMNS]


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS employees (
                telegram_id INTEGER PRIMARY KEY,
                name        TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_name TEXT,
                date          TEXT,
                deposit_rial  TEXT,
                tether        TEXT,
                player_name   TEXT,
                expenses      TEXT,
                invoice       TEXT,
                food          TEXT,
                lunch         TEXT,
                dinner        TEXT,
                hotel         TEXT,
                recorder      TEXT,
                editor        TEXT,
                extra         TEXT DEFAULT '{}',
                created_at    TEXT DEFAULT (datetime('now','localtime')),
                updated_at    TEXT
            )
            """
        )
        # field-haye delkhah ke robot-marketing khodش ezafe mikone (key=cf<id>)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_fields (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL
            )
            """
        )
        # migration: agar DB-ye qadimi sotoon-e extra nadasht, ezafe kon
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(records)").fetchall()]
        if "extra" not in cols:
            conn.execute("ALTER TABLE records ADD COLUMN extra TEXT DEFAULT '{}'")


# ---- settings (key/value) ----
def get_setting(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ---- web password (ghabel-e taghir tavasot-e moshtari) ----
def get_web_password() -> str:
    return get_setting("web_password", config.WEB_PASSWORD)


def set_web_password(new_pw: str):
    set_setting("web_password", new_pw)


# ---- context-e kari: akharin radif-e har karmand ----
def set_last_record(telegram_id: int, record_id: int):
    set_setting(f"last_{telegram_id}", str(record_id))


def get_last_record(telegram_id: int):
    v = get_setting(f"last_{telegram_id}")
    return int(v) if v and v.isdigit() else None


# ---- admin (owner-haye robot-marketing) ----
def get_admins() -> set:
    raw = get_setting("admin_ids", "")
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}


def add_admin(telegram_id: int):
    admins = get_admins()
    admins.add(telegram_id)
    set_setting("admin_ids", ",".join(str(x) for x in admins))


def is_admin(telegram_id: int) -> bool:
    return telegram_id in get_admins()


# ---- employees ----
def register_employee(telegram_id: int, name: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO employees (telegram_id, name) VALUES (?, ?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET name=excluded.name",
            (telegram_id, name),
        )


def get_employee(telegram_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM employees WHERE telegram_id=?", (telegram_id,)
        ).fetchone()
        return row["name"] if row else None


def count_employees() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) c FROM employees").fetchone()["c"]


def list_employees():
    with get_conn() as conn:
        return [(r["telegram_id"], r["name"]) for r in conn.execute(
            "SELECT telegram_id, name FROM employees ORDER BY name"
        ).fetchall()]


def remove_employee(arg: str) -> str | None:
    """Hazf-e karmand ba telegram_id ya esm. Esm-e hazf-shode bar mygardune."""
    with get_conn() as conn:
        if arg.isdigit():
            row = conn.execute(
                "SELECT name FROM employees WHERE telegram_id=?", (int(arg),)
            ).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM employees WHERE telegram_id=?", (int(arg),))
            return row["name"]
        row = conn.execute(
            "SELECT telegram_id, name FROM employees WHERE name=?", (arg,)
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM employees WHERE telegram_id=?", (row["telegram_id"],))
        return row["name"]


# ---- custom fields (robot-marketing khodش ezafe mikone) ----
def add_custom_field(label: str) -> str:
    label = label.strip()
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO custom_fields (label) VALUES (?)", (label,))
        return f"cf{cur.lastrowid}"


def list_custom_fields():
    """[(key, label)] — key = cf<id>."""
    with get_conn() as conn:
        return [(f"cf{r['id']}", r["label"]) for r in conn.execute(
            "SELECT id, label FROM custom_fields ORDER BY id"
        ).fetchall()]


def remove_custom_field(arg: str) -> str | None:
    """ba key (cf3) ya label hazf kon; label-e hazf-shده bar mygardune."""
    arg = arg.strip()
    fid = None
    if arg.startswith("cf") and arg[2:].isdigit():
        fid = int(arg[2:])
    with get_conn() as conn:
        if fid is not None:
            row = conn.execute("SELECT label FROM custom_fields WHERE id=?", (fid,)).fetchone()
        else:
            row = conn.execute("SELECT id, label FROM custom_fields WHERE label=?", (arg,)).fetchone()
            fid = row["id"] if row else None
        if not row:
            return None
        conn.execute("DELETE FROM custom_fields WHERE id=?", (fid,))
        return row["label"]


# ---- records ----
def insert_record(data: dict, recorder: str, extra: dict = None) -> int:
    payload = {k: data.get(k) for k in DATA_KEYS}
    payload["recorder"] = recorder
    if not payload.get("employee_name"):
        payload["employee_name"] = recorder
    payload["extra"] = json.dumps(extra or {}, ensure_ascii=False)
    cols = ", ".join(payload.keys())
    placeholders = ", ".join("?" for _ in payload)
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO records ({cols}) VALUES ({placeholders})",
            list(payload.values()),
        )
        return cur.lastrowid


def update_record(record_id: int, data: dict, editor: str, extra: dict = None) -> bool:
    fields = {k: v for k, v in data.items() if k in DATA_KEYS and v is not None}
    with get_conn() as conn:
        if extra is not None:
            row = conn.execute("SELECT extra FROM records WHERE id=?", (record_id,)).fetchone()
            if row is None:
                return False
            cur_extra = json.loads(row["extra"] or "{}")
            cur_extra.update(extra)
            fields["extra"] = json.dumps(cur_extra, ensure_ascii=False)
        if not fields:
            return False
        fields["editor"] = editor
        sets = ", ".join(f"{k}=?" for k in fields)
        cur = conn.execute(
            f"UPDATE records SET {sets}, updated_at=datetime('now','localtime') WHERE id=?",
            list(fields.values()) + [record_id],
        )
        return cur.rowcount > 0


def record_extra(rec: dict) -> dict:
    """JSON-e extra ye record ro be dict tabdil kon."""
    try:
        return json.loads(rec.get("extra") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def delete_record(record_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM records WHERE id=?", (record_id,))
        return cur.rowcount > 0


def all_records():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM records ORDER BY id DESC"
        ).fetchall()]


def recent_records(limit: int = 10):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM records ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()]
