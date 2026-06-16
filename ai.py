"""AI layer:
  - transcribe_voice : OpenAI (gpt-4o-transcribe) seda -> matn
  - parse_text       : Claude Opus 4.8 matn-e shologh -> radif-haye sakhtyafte
"""
import json
import re
import os
import subprocess
import tempfile
from typing import Optional, List
from pydantic import BaseModel, Field, ValidationError
from anthropic import Anthropic
from openai import OpenAI
import config
import db

_anthropic = Anthropic(api_key=config.ANTHROPIC_API_KEY)
_openai = OpenAI(api_key=config.OPENAI_API_KEY)


class Row(BaseModel):
    employee_name: Optional[str] = Field(None, description="نام کارمند")
    date: Optional[str] = Field(None, description="تاریخ (هرچه کاربر گفت، همان)")
    deposit_rial: Optional[str] = Field(None, description="واریزی ریالی / تومانی")
    tether: Optional[str] = Field(None, description="مقدار تتر / USDT")
    player_name: Optional[str] = Field(None, description="اسم پلیر")
    expenses: Optional[str] = Field(None, description="هزینه‌ها")
    invoice: Optional[str] = Field(None, description="فاکتور")
    food: Optional[str] = Field(None, description="غذا")
    lunch: Optional[str] = Field(None, description="ناهار")
    dinner: Optional[str] = Field(None, description="شام")
    hotel: Optional[str] = Field(None, description="هتل")


class ParseResult(BaseModel):
    rows: List[Row] = Field(default_factory=list, description="هر تراکنش یک ردیف")


SYSTEM_HEAD = """تو دستیار ثبت داده‌های یک کازینو هستی. کارمندها به فارسی یا فینگلیش
(فارسیِ با حروف انگلیسی) و گاهی شلوغ و محاوره‌ای پیام می‌دهند. وظیفه‌ات این است
که از متن، تراکنش‌ها را استخراج کنی و در ستون‌های جدول بچینی.

خروجی را **فقط** به صورت JSON بده، دقیقاً این شکل (بدون هیچ متن اضافه، بدون ```):
{"rows": [{ ... فیلدها ... }]}

فیلدهای مجاز هر ردیف (هر کدام نبود را null بگذار) — حتماً همین کلیدها را استفاده کن:
"""

SYSTEM_TAIL = """
قواعد:
- هر تراکنش/ردیفِ مجزا را یک آیتم در rows بگذار. اگر پیام چند نفر/چند تراکنش دارد، چند ردیف بساز.
- اگر مقداری در متن نبود، آن فیلد را null بگذار (از خودت نساز).
- اعداد فارسی را به انگلیسی تبدیل کن. واحد را اگر گفته شد نگه دار (مثلاً «۵ میلیون»).
- «واریزی ریالی» یعنی پول ریالی/تومانی؛ «تتر» یعنی USDT/تتر.
- متن را تمیز و خلاصه در هر سلول بنویس، نه عین جمله‌ی خام.
- فقط داده‌ی واقعیِ گفته‌شده را ثبت کن. فقط JSON خالص خروجی بده.

⛔ محدودیت سخت: تو فقط و فقط ابزار استخراج دادهٔ کازینو هستی. هیچ نقش دیگری نداری.
- به هیچ سؤال، گفتگو، جوک، درخواست کد، ترجمه، یا هر چیزِ بی‌ربط به ثبت داده پاسخ نده.
- اگر پیام دادهٔ تراکنشِ کازینو نیست (سؤال، حرفِ عادی، چرت‌وپرت)، فقط {"rows": []} برگردان.
- هیچ‌وقت متنِ توضیحی یا مکالمه‌ای تولید نکن — خروجی همیشه فقط JSON است."""


def _build_system() -> str:
    """field-list ro پویا (fixed + custom) misaze."""
    lines = [f'  - "{k}": {fa}' for k, fa in db.COLUMNS
             if k not in ("recorder", "editor")]
    for key, label in db.list_custom_fields():
        lines.append(f'  - "{key}": {label}')
    return SYSTEM_HEAD + "\n".join(lines) + SYSTEM_TAIL


def _to_mp3(src: str) -> str:
    """Telegram voice (.oga/opus) ro ba ffmpeg be mp3 tabdil kon —
    OpenAI پسوند oga ro qabul nemikone."""
    fd, dst = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ac", "1", "-ar", "16000", dst],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return dst


def transcribe_voice(path: str) -> str:
    """Voice file -> matn-e farsi (aval be mp3 tabdil mishe)."""
    mp3 = _to_mp3(path)
    try:
        with open(mp3, "rb") as f:
            resp = _openai.audio.transcriptions.create(
                model=config.OPENAI_STT_MODEL,
                file=f,
                language="fa",
            )
        return (resp.text or "").strip()
    finally:
        if os.path.exists(mp3):
            os.remove(mp3)


def _extract_json(raw: str) -> dict:
    """Az matn-e kham, JSON ro daربیار (agar ``` ya matn-e ezafe bud)."""
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {"rows": []}
    return json.loads(m.group(0))


def _build_edit_system() -> str:
    lines = [f'  - "{k}": {fa}' for k, fa in db.COLUMNS
             if k not in ("recorder", "editor")]
    for key, label in db.list_custom_fields():
        lines.append(f'  - "{key}": {label}')
    fields = "\n".join(lines)
    return (
        "کاربرِ کازینو می‌خواهد یک ردیفِ موجود در جدول را اصلاح/ویرایش کند.\n"
        "از متن فقط فیلدهایی را که باید عوض شوند و مقدار جدیدشان را دربیاور.\n"
        'خروجی فقط JSON خالص: {"changes": {"<کلید>": "<مقدار جدید>", ...}}\n'
        "شمارهٔ ردیف («ردیف ۳» و ...) را نادیده بگیر، فقط مقادیر را بده.\n"
        "کلیدهای مجاز:\n" + fields + "\n"
        "اعداد فارسی را به انگلیسی تبدیل کن. اگر هیچ تغییری مشخص نبود، "
        '{"changes": {}} بده. فقط JSON.'
    )


def parse_edit(text: str, employee_name: Optional[str] = None) -> dict:
    """Matn/voice-e ویرایش -> dict-e field-haye taghir-yafte."""
    resp = _anthropic.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=_build_edit_system(),
        messages=[{"role": "user", "content": text}],
    )
    out = "".join(b.text for b in resp.content if b.type == "text")
    try:
        data = _extract_json(out)
        changes = data.get("changes", data)
        return {k: v for k, v in changes.items() if v not in (None, "")}
    except json.JSONDecodeError:
        return {}


def parse_text(text: str, employee_name: Optional[str] = None) -> List[dict]:
    """Matn -> list-e radif (dict). har radif kelid-haye fixed + custom dare.
    JSON khaam migirim va khodemun parse mikonim (bدون grammar-e strict)."""
    hint = f"\n\n(پیام از طرف کارمند: {employee_name})" if employee_name else ""
    resp = _anthropic.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=_build_system(),
        messages=[{"role": "user", "content": text + hint}],
    )
    out = "".join(b.text for b in resp.content if b.type == "text")
    try:
        data = _extract_json(out)
        rows = data.get("rows", [])
        return [r for r in rows if isinstance(r, dict)]
    except json.JSONDecodeError:
        return []
