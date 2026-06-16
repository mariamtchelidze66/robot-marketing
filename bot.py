"""Telegram bot: payam-e matn/voice -> parse -> sabt. Web dashboard ru thread-e joda."""
import logging
import tempfile
import os
import re
import threading

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

import config
import db
import ai
import exporter
import web

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO
)
log = logging.getLogger("robot-marketing")

COL_FA = dict(db.COLUMNS)

IDENTITY_REPLY = "من میلادم، دستیار هوشمند شما 🤖"
# عبارت‌هایی که یعنی «تو کی هستی» (فارسی/فینگلیش)
_IDENTITY_HINTS = [
    "کی هستی", "کی هستین", "کی هستید", "کیستی", "تو کی", "شما کی",
    "اسمت چیه", "اسمت چیست", "اسم تو", "نامت", "اسمت کیه",
    "تو چی هستی", "چی هستی", "خودتو معرفی", "معرفی کن",
    "ki hasti", "to ki", "shoma ki", "esmet", "esmat", "who are you",
    "what are you", "khodeto",
]


def _is_identity_question(text: str) -> bool:
    t = text.lower().strip()
    return any(h in t for h in _IDENTITY_HINTS)


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# «ردیف ۳» / «رکورد 3» / «سطر #۵» / «row 2» -> یعنی ویرایش همان ردیف
_EDIT_TARGET_RE = re.compile(r"(?:ردیف|رکورد|سطر|row)\s*#?\s*(\d+)")


def _detect_edit_target(text: str):
    """Agar payغام be ye ردیف eshare kone (baraye ویرایش)، shomare-ش ro bede."""
    m = _EDIT_TARGET_RE.search(text.translate(_FA_DIGITS))
    return int(m.group(1)) if m else None


# eshare be «آخرین ردیف» bدون-e shomare: «اینو ویرایش کن»، «همینو درست کن»، ...
_LAST_HINTS = [
    "اینو", "این رو", "این را", "همینو", "همین رو", "همین را", "همون", "همونو",
    "قبلی", "قبلیو", "آخری", "آخریو", "آخرین", "اصلاح", "ویرایش", "درستش",
    "عوضش", "غلط", "اشتباه",
    "ino", "in ro", "hamino", "hamin", "hamoon", "qabli", "akhari",
    "eslah", "virayesh", "edit", "ghalat", "eshtebah", "doros",
]


def _refers_to_last(text: str) -> bool:
    t = text.lower()
    return any(h in t for h in _LAST_HINTS)


def _fmt_row(rec_id: int, row: dict) -> str:
    lines = [f"✅ ردیف #{rec_id}:"]
    labels = [(k, fa) for k, fa in db.COLUMNS if k not in ("recorder", "editor")]
    labels += db.list_custom_fields()  # [(cfX, label)]
    for key, fa in labels:
        val = row.get(key)
        if val:
            lines.append(f"  • {fa}: {val}")
    return "\n".join(lines)


async def _process_text(update: Update, text: str):
    uid = update.effective_user.id
    # «تو کی هستی؟» -> javab-e sabet (bedun-e AI)
    if _is_identity_question(text):
        await update.message.reply_text(IDENTITY_REPLY)
        return
    name = db.get_employee(uid)
    if not name:
        await update.message.reply_text(
            "اول اسمت رو ثبت کن:\n/esm <اسم خودت>\nمثال: /esm علی"
        )
        return
    await update.message.chat.send_action("typing")
    custom_keys = [k for k, _ in db.list_custom_fields()]
    target = _detect_edit_target(text)  # «ردیف N» -> ویرایش همان ردیف
    # «اینو ویرایش کن» بدون شماره -> آخرین ردیفِ همین کارمند (ادامهٔ گفتگو)
    if target is None and _refers_to_last(text):
        target = db.get_last_record(uid)
        if target is None:
            await update.message.reply_text(
                "ردیف قبلی‌ای برای ویرایش نداری. اول یک داده ثبت کن."
            )
            return

    # --- حالت ویرایش (با متن یا ویس) ---
    if target is not None:
        try:
            changes = ai.parse_edit(text, employee_name=name)
        except Exception as e:
            log.exception("edit parse error")
            await update.message.reply_text(f"⚠️ خطا: {e}")
            return
        if not changes:
            await update.message.reply_text(
                f"می‌خواهی ردیف #{target} را ویرایش کنی؛ بگو چه چیزی عوض شود "
                "(مثلاً: «ردیف ۳ تتر را ۲۰ کن»)."
            )
            return
        fixed = {k: v for k, v in changes.items() if k in db.DATA_KEYS}
        extra = {k: v for k, v in changes.items() if k in custom_keys}
        if db.update_record(target, fixed, editor=name, extra=extra or None):
            db.set_last_record(uid, target)  # context-e kari
            parts = _fmt_row(target, changes).split("\n", 1)
            detail = parts[1] if len(parts) > 1 else "  (به‌روزرسانی شد)"
            await update.message.reply_text(
                f"✏️ ردیف #{target} ویرایش شد (توسط {name}):\n{detail}"
            )
        else:
            await update.message.reply_text(f"ردیف #{target} پیدا نشد.")
        return

    # --- حالت ثبت جدید ---
    try:
        rows = ai.parse_text(text, employee_name=name)
    except Exception as e:
        log.exception("parse error")
        await update.message.reply_text(f"⚠️ خطا در پردازش: {e}")
        return
    if not rows:
        await update.message.reply_text(
            "⛔ این ربات فقط برای ثبت داده‌های کازینوست؛ به سؤال یا گفتگو پاسخ نمی‌دهد.\n"
            "لطفاً فقط اطلاعات تراکنش بفرست (مثلاً: نام، واریزی، تتر، پلیر، هزینه‌ها)."
        )
        return
    replies = []
    rec_id = None
    for row in rows:
        fixed = {k: row.get(k) for k, _ in db.COLUMNS}
        extra = {k: row.get(k) for k in custom_keys if row.get(k)}
        rec_id = db.insert_record(fixed, recorder=name, extra=extra)
        replies.append(_fmt_row(rec_id, row))
    if rec_id is not None:
        db.set_last_record(uid, rec_id)  # context-e kari: akharin radif
    await update.message.reply_text(
        "\n\n".join(replies) + "\n\n📊 داشبورد: /web"
    )


# ---------------- commands ----------------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # bootstrap: avalin kasi ke /start mizane (vaqti hanuz admin nist) -> admin mishe
    extra = ""
    if not db.get_admins():
        db.add_admin(uid)
        extra = "\n\n👑 شما به‌عنوان مدیر ثبت شدید (اولین کاربر)."
    is_admin = db.is_admin(uid)
    admin_help = (
        "\n/ramz <رمز جدید> — تغییر رمز داشبورد (مدیر)"
        "\n/karmandan — لیست کارمندها (مدیر)"
        "\n/hazf <آیدی/اسم> — حذف کارمند (مدیر)"
    ) if is_admin else ""
    await update.message.reply_text(
        "سلام 🎰 ربات ثبت داده‌های کازینو.\n\n"
        "۱) اول اسمت رو ثبت کن: /esm <اسم>\n"
        "۲) بعد متن یا ویس بفرست؛ خودم داده‌ها رو در جدول می‌چینم.\n\n"
        "دستورها:\n"
        "/esm <اسم> — ثبت نام شما\n"
        "/field <اسم> — اضافه‌کردن ستون/فیلد جدید\n"
        "/fields — لیست فیلدهای دلخواه\n"
        "/edit <شماره ردیف> <متن> — ویرایش یک ردیف\n"
        "/export — گرفتن فایل اکسل\n"
        "/web — لینک و رمز داشبورد آنلاین\n"
        "/id — آیدی تلگرام شما" + admin_help + extra
    )


async def cmd_ramz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not db.is_admin(uid):
        await update.message.reply_text("⛔ فقط مدیر می‌تواند رمز را عوض کند.")
        return
    if not ctx.args:
        await update.message.reply_text(
            "رمز جدید را بنویس: /ramz <رمز جدید>\n"
            f"رمز فعلی: {db.get_web_password()}"
        )
        return
    new_pw = " ".join(ctx.args).strip()
    db.set_web_password(new_pw)
    await update.message.reply_text(f"✅ رمز داشبورد عوض شد. رمز جدید: {new_pw}")


async def cmd_esm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("اسمت رو بنویس: /esm علی")
        return
    name = " ".join(ctx.args).strip()
    already = db.get_employee(uid) is not None
    # cap: faqat MAX_EMPLOYEES karmand. Karmand-e فعلی mitune esmشو avaz kone.
    if not already and db.count_employees() >= config.MAX_EMPLOYEES:
        await update.message.reply_text(
            f"⛔ ظرفیت {config.MAX_EMPLOYEES} کارمند پر است. "
            "برای اضافه‌شدن، مدیر باید یک نفر را حذف کند (/karmandan)."
        )
        return
    db.register_employee(uid, name)
    await update.message.reply_text(f"ثبت شد ✅ از این به بعد ثبت‌کننده: {name}")


async def cmd_karmandan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ فقط مدیر.")
        return
    emps = db.list_employees()
    if not emps:
        await update.message.reply_text("هیچ کارمندی ثبت نشده.")
        return
    lines = [f"👥 کارمندها ({len(emps)}/{config.MAX_EMPLOYEES}):"]
    for tid, name in emps:
        lines.append(f"  • {name} — {tid}")
    lines.append("\nحذف: /hazf <آیدی یا اسم>")
    await update.message.reply_text("\n".join(lines))


async def cmd_hazf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ فقط مدیر.")
        return
    if not ctx.args:
        await update.message.reply_text("روش: /hazf <آیدی یا اسم کارمند>")
        return
    arg = " ".join(ctx.args).strip()
    removed = db.remove_employee(arg)
    if removed:
        await update.message.reply_text(
            f"✅ «{removed}» حذف شد. حالا یک جای خالی هست "
            f"({db.count_employees()}/{config.MAX_EMPLOYEES})."
        )
    else:
        await update.message.reply_text("کارمندی با این آیدی/اسم پیدا نشد.")


async def cmd_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ezafe kardan-e field-e delkhah (karmand-e ثبت‌شده)."""
    uid = update.effective_user.id
    if not db.get_employee(uid):
        await update.message.reply_text("اول /esm <اسم>.")
        return
    if not ctx.args:
        await update.message.reply_text(
            "اسم فیلد جدید را بنویس: /field <اسم>\n"
            "مثال: /field دیپازیت   یا   /field وین/لوس"
        )
        return
    label = " ".join(ctx.args).strip()
    existing = {fa for _, fa in db.list_custom_fields()}
    if label in existing:
        await update.message.reply_text("این فیلد از قبل هست.")
        return
    key = db.add_custom_field(label)
    await update.message.reply_text(
        f"✅ فیلد «{label}» اضافه شد. از این به بعد توی پیام‌ها هم ثبت می‌شود "
        "و در سایت/اکسل می‌آید."
    )


async def cmd_fields(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cfs = db.list_custom_fields()
    if not cfs:
        await update.message.reply_text(
            "هیچ فیلد دلخواهی اضافه نشده.\nاضافه‌کردن: /field <اسم>"
        )
        return
    lines = ["🧩 فیلدهای دلخواه:"]
    for key, label in cfs:
        lines.append(f"  • {label}  ({key})")
    lines.append("\nحذف (مدیر): /field_del <اسم یا کد>")
    await update.message.reply_text("\n".join(lines))


async def cmd_field_del(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ فقط مدیر می‌تواند فیلد را حذف کند.")
        return
    if not ctx.args:
        await update.message.reply_text("روش: /field_del <اسم فیلد یا کد cfX>")
        return
    removed = db.remove_custom_field(" ".join(ctx.args))
    if removed:
        await update.message.reply_text(f"✅ فیلد «{removed}» حذف شد.")
    else:
        await update.message.reply_text("فیلدی با این اسم/کد پیدا نشد.")


async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"آیدی تلگرام شما: {update.effective_user.id}")


async def cmd_web(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 داشبورد آنلاین (با رمز):\nرمز فعلی: {db.get_web_password()}\n"
        f"پورت: {config.WEB_PORT}\n"
        "تغییر رمز: /ramz <رمز جدید> (فقط مدیر)"
    )


async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    path = exporter.build_xlsx()
    with open(path, "rb") as f:
        await update.message.reply_document(f, filename="robot-marketing.xlsx")


async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    name = db.get_employee(uid)
    if not name:
        await update.message.reply_text("اول /esm <اسم>.")
        return
    if len(ctx.args) < 2 or not ctx.args[0].isdigit():
        await update.message.reply_text("روش: /edit <شماره ردیف> <متن اصلاحی>")
        return
    rec_id = int(ctx.args[0])
    text = " ".join(ctx.args[1:])
    try:
        rows = ai.parse_text(text, employee_name=name)
    except Exception as e:
        await update.message.reply_text(f"⚠️ خطا: {e}")
        return
    if not rows:
        await update.message.reply_text("چیزی برای ویرایش پیدا نکردم.")
        return
    row = rows[0]
    fixed = {k: v for k, v in row.items() if k in db.DATA_KEYS and v is not None}
    custom_keys = [k for k, _ in db.list_custom_fields()]
    extra = {k: row.get(k) for k in custom_keys if row.get(k)}
    if db.update_record(rec_id, fixed, editor=name, extra=extra or None):
        await update.message.reply_text(f"ردیف #{rec_id} ویرایش شد ✅ (توسط {name})")
    else:
        await update.message.reply_text(f"ردیف #{rec_id} پیدا نشد یا تغییری نبود.")


# ---------------- messages ----------------
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _process_text(update, update.message.text)


async def on_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    voice = update.message.voice or update.message.audio
    await update.message.chat.send_action("typing")
    tg_file = await ctx.bot.get_file(voice.file_id)
    fd, path = tempfile.mkstemp(suffix=".oga")
    os.close(fd)
    try:
        await tg_file.download_to_drive(path)
        text = ai.transcribe_voice(path)
    except Exception as e:
        log.exception("voice error")
        await update.message.reply_text(f"⚠️ خطا در ویس: {e}")
        return
    finally:
        if os.path.exists(path):
            os.remove(path)
    if not text:
        await update.message.reply_text("صدا رو نفهمیدم، دوباره بفرست.")
        return
    await update.message.reply_text(f"🎙 متن ویس:\n«{text}»")
    await _process_text(update, text)


def main():
    db.init_db()
    # web dashboard ru thread-e joda
    threading.Thread(target=web.app.run, kwargs={
        "host": config.WEB_HOST, "port": config.WEB_PORT, "use_reloader": False,
    }, daemon=True).start()
    log.info("Web dashboard ru port %s", config.WEB_PORT)

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("esm", cmd_esm))
    app.add_handler(CommandHandler("register", cmd_esm))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("web", cmd_web))
    app.add_handler(CommandHandler("ramz", cmd_ramz))
    app.add_handler(CommandHandler("karmandan", cmd_karmandan))
    app.add_handler(CommandHandler("hazf", cmd_hazf))
    app.add_handler(CommandHandler("field", cmd_field))
    app.add_handler(CommandHandler("fields", cmd_fields))
    app.add_handler(CommandHandler("field_del", cmd_field_del))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Bot shoru shod (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
