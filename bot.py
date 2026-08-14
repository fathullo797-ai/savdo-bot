# Savdo-Xarajat Kundaligi — Telegram bot (v2)
# Yangi imkoniyatlar: ovozli xabar, buyruqsiz raqam, oylik hisobot
#
# O'rnatish:
#   pip3 install -r requirements.txt
#   (Mac uchun): brew install ffmpeg
# Ishga tushirish:
#   python3 bot.py

import re
import sqlite3
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    MessageHandler, CallbackQueryHandler, filters
)

import os

# 1) Token endi environment variable orqali olinadi (xavfsizroq)
TOKEN = os.environ.get("BOT_TOKEN", "8848747787:AAHnRzcJbMR85yrj4dF6Kpzh9Wvb2vBCWc8")

DB_NAME = "kundalik.db"

# Ovozli xabarni matnga aylantirish uchun (birinchi ishga tushirishda
# model avtomatik yuklab olinadi, ~500 MB, internet kerak bo'ladi)
WHISPER_MODEL_SIZE = "base"  # tezroq bo'lishi uchun "base" ga o'zgartirsangiz bo'ladi
_whisper_model = None

SALES_WORDS = [
    "sotdim", "sotildi", "savdo", "tushum", "sotuv", "kirim", "keldi",
    "продал", "выручка", "поступление", "доход", "приход",
]
EXPENSE_WORDS = [
    "xarajat", "sarfladim", "to'ladim", "berdim", "chiqim", "harajat", "sarflandi",
    "потратил", "расход", "заплатил", "оплатил", "купил",
]

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        print("Whisper modeli yuklanmoqda (birinchi marta biroz vaqt oladi)...")
        _whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    return _whisper_model


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            entry_date TEXT NOT NULL,
            sales REAL NOT NULL DEFAULT 0,
            expense REAL NOT NULL DEFAULT 0,
            note TEXT
        )
    """)
    conn.commit()
    conn.close()


def add_entry(user_id: int, sales: float, expense: float, note: str = ""):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO entries (user_id, entry_date, sales, expense, note) VALUES (?, ?, ?, ?, ?)",
        (user_id, str(date.today()), sales, expense, note),
    )
    conn.commit()
    conn.close()


def get_summary_between(user_id: int, start: str, end: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "SELECT SUM(sales), SUM(expense) FROM entries WHERE user_id=? AND entry_date>=? AND entry_date<?",
        (user_id, start, end),
    )
    row = cur.fetchone()
    conn.close()
    return (row[0] or 0), (row[1] or 0)


def get_summary(user_id: int, days: int = None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if days:
        since = str(date.today() - timedelta(days=days))
        cur.execute(
            "SELECT SUM(sales), SUM(expense) FROM entries WHERE user_id=? AND entry_date>=?",
            (user_id, since),
        )
    else:
        cur.execute("SELECT SUM(sales), SUM(expense) FROM entries WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return (row[0] or 0), (row[1] or 0)


def get_recent(user_id: int, limit: int = 10):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "SELECT entry_date, sales, expense, note FROM entries WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def fmt(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def extract_amount(text: str):
    """Matndan birinchi raqamni topadi. '150 000', '150.000', '150000' kabi formatlarni tushunadi."""
    match = re.search(r'\d[\d\s.,]*\d|\d+', text)
    if not match:
        return None
    digits = re.sub(r'[^\d]', '', match.group())
    if not digits:
        return None
    return float(digits)


def guess_type(text: str):
    """Matnda savdo yoki xarajat so'zlari bormi, tekshiradi. Ikkalasi ham topilmasa None qaytaradi."""
    lowered = text.lower()
    if any(w in lowered for w in EXPENSE_WORDS):
        return "expense"
    if any(w in lowered for w in SALES_WORDS):
        return "sales"
    return None


async def process_text_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    amount = extract_amount(text)
    if amount is None:
        await update.message.reply_text(
            "Raqamni topa olmadim. Masalan: \"150000 sotdim\" yoki \"30000 ijaraga to'ladim\" deb yozing."
        )
        return

    entry_type = guess_type(text)
    note = text.strip()

    if entry_type == "sales":
        add_entry(update.effective_user.id, amount, 0, note)
        await update.message.reply_text(f"✅ Savdo sifatida yozildi: {fmt(amount)} so'm")
    elif entry_type == "expense":
        add_entry(update.effective_user.id, 0, amount, note)
        await update.message.reply_text(f"✅ Xarajat sifatida yozildi: {fmt(amount)} so'm")
    else:
        # Turi aniq emas — foydalanuvchidan so'raymiz
        context.user_data["pending_amount"] = amount
        context.user_data["pending_note"] = note
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💰 Savdo", callback_data="type:sales"),
                InlineKeyboardButton("💸 Xarajat", callback_data="type:expense"),
            ]
        ])
        await update.message.reply_text(
            f"{fmt(amount)} so'm — bu savdo yoki xarajatmi?", reply_markup=keyboard
        )


async def handle_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    amount = context.user_data.pop("pending_amount", None)
    note = context.user_data.pop("pending_note", "")
    if amount is None:
        await query.edit_message_text("Bu so'rov muddati o'tgan, qaytadan yuboring.")
        return
    if query.data == "type:sales":
        add_entry(query.from_user.id, amount, 0, note)
        await query.edit_message_text(f"✅ Savdo sifatida yozildi: {fmt(amount)} so'm")
    else:
        add_entry(query.from_user.id, 0, amount, note)
        await query.edit_message_text(f"✅ Xarajat sifatida yozildi: {fmt(amount)} so'm")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_text_entry(update, context, update.message.text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙 Ovozli xabar eshitilyapti...")
    voice = update.message.voice or update.message.audio
    file = await context.bot.get_file(voice.file_id)
    ogg_path = f"voice_{update.effective_user.id}.ogg"
    await file.download_to_drive(ogg_path)

    try:
        model = get_whisper_model()
        _, detect_info = model.transcribe(ogg_path, language=None)
        detected_lang = detect_info.language if detect_info.language in ("uz", "ru") else "uz"
        segments, _ = model.transcribe(ogg_path, language=detected_lang)
        text = " ".join(seg.text for seg in segments).strip()
    except Exception as e:
        await update.message.reply_text(f"Ovozni tanib bo'lmadi: {e}")
        return

    if not text:
        await update.message.reply_text("Ovozdan matn chiqmadi, qayta urinib ko'ring.")
        return

    await update.message.reply_text(f"Eshitdim: \u201c{text}\u201d")
    await process_text_entry(update, context, text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Assalomu alaykum! Men sizning kunlik savdo-xarajat kundaligingizman.\n\n"
        "Buyruqlar:\n"
        "/savdo 150000 - bugungi savdoni yozish\n"
        "/xarajat 30000 ijara - bugungi xarajatni yozish\n"
        "/hisobot - umumiy hisobot\n"
        "/oylik - shu oylik hisobot\n"
        "/royxat - oxirgi yozuvlar\n\n"
        "Yoki shunchaki yozing: \"150000 sotdim\"\n"
        "Yoki ovozli xabar yuboring — men tinglayman 🎙"
    )
    await update.message.reply_text(text)


async def savdo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Miqdorni kiriting. Masalan: /savdo 150000")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Miqdor raqam bo'lishi kerak.")
        return
    note = " ".join(context.args[1:])
    add_entry(update.effective_user.id, amount, 0, note)
    await update.message.reply_text(f"✅ Savdo yozildi: {fmt(amount)} so'm")


async def xarajat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Miqdorni kiriting. Masalan: /xarajat 30000 ijara")
        return
    try:
        amount = float(context.args[0])
    except ValueError:
        await update.message.reply_text("Miqdor raqam bo'lishi kerak.")
        return
    note = " ".join(context.args[1:])
    add_entry(update.effective_user.id, 0, amount, note)
    await update.message.reply_text(f"✅ Xarajat yozildi: {fmt(amount)} so'm")


async def hisobot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    s7, e7 = get_summary(uid, days=7)
    s_all, e_all = get_summary(uid, days=None)

    def block(title, s, e):
        p = s - e
        stamp = "FOYDA" if p >= 0 else "ZARAR"
        return f"{title}\nSavdo: {fmt(s)}\nXarajat: {fmt(e)}\n{stamp}: {fmt(abs(p))}\n"

    text = block("📅 Oxirgi 7 kun", s7, e7) + "\n" + block("📊 Umumiy", s_all, e_all)
    await update.message.reply_text(text)


async def oylik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    today = date.today()
    this_month_start = today.replace(day=1)

    if this_month_start.month == 1:
        prev_month_start = this_month_start.replace(year=this_month_start.year - 1, month=12)
    else:
        prev_month_start = this_month_start.replace(month=this_month_start.month - 1)

    s_this, e_this = get_summary_between(uid, str(this_month_start), str(today + timedelta(days=1)))
    s_prev, e_prev = get_summary_between(uid, str(prev_month_start), str(this_month_start))

    p_this = s_this - e_this
    p_prev = s_prev - e_prev

    if p_prev != 0:
        change_pct = ((p_this - p_prev) / abs(p_prev)) * 100
        if change_pct >= 0:
            trend = f"📈 O'tgan oyga nisbatan +{change_pct:.0f}%"
        else:
            trend = f"📉 O'tgan oyga nisbatan {change_pct:.0f}%"
    else:
        trend = "O'tgan oy uchun ma'lumot yo'q"

    stamp = "FOYDA" if p_this >= 0 else "ZARAR"
    text = (
        f"📆 Shu oy ({this_month_start.strftime('%B')})\n"
        f"Savdo: {fmt(s_this)}\n"
        f"Xarajat: {fmt(e_this)}\n"
        f"{stamp}: {fmt(abs(p_this))}\n\n"
        f"{trend}"
    )
    await update.message.reply_text(text)


async def royxat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_recent(update.effective_user.id, 10)
    if not rows:
        await update.message.reply_text("Hali yozuv yo'q.")
        return
    lines = ["Oxirgi yozuvlar:\n"]
    for entry_date, sales, expense, note in rows:
        p = sales - expense
        line = f"{entry_date}: savdo {fmt(sales)} / xarajat {fmt(expense)} / foyda {fmt(p)}"
        if note:
            line += f" ({note})"
        lines.append(line)
    await update.message.reply_text("\n".join(lines))


def main():
    init_db()
    app = (
        Application.builder()
        .token(TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )


if __name__ == "__main__":
    main()
