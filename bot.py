import os
import sqlite3
import secrets
import string
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import solver  # استدعاء ملف الحلول

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MAX_SERIALS = 100
DB_FILE = os.getenv("DB_FILE") or "serials.db"
ALPHABET = string.ascii_uppercase + string.digits

# ============ قاعدة البيانات ============
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS serials (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, activated_by INTEGER, activated_at TEXT)""")
    conn.commit(); conn.close()

def _now():
    return datetime.now(timezone.utc).isoformat()

def serial_exists(code):
    conn = get_conn()
    r = conn.execute("SELECT 1 FROM serials WHERE code = ?", (code,)).fetchone()
    conn.close()
    return r is not None

def create_serial():
    while True:
        raw = ''.join(secrets.choice(ALPHABET) for _ in range(16))
        code = '-'.join(raw[i:i + 4] for i in range(0, 16, 4))
        if not serial_exists(code):
            conn = get_conn()
            conn.execute("INSERT INTO serials (code, status, created_at) VALUES (?, 'active', ?)", (code, _now()))
            conn.commit(); conn.close()
            return code

def get_serial(code):
    conn = get_conn()
    r = conn.execute("SELECT * FROM serials WHERE code = ?", (code,)).fetchone()
    conn.close(); return r

def activate_serial(code, user_id):
    conn = get_conn()
    r = conn.execute("SELECT * FROM serials WHERE code = ?", (code,)).fetchone()
    if not r: conn.close(); return "not_found"
    if r["status"] != "active": conn.close(); return "revoked"
    if r["activated_by"] is not None:
        res = "already_yours" if r["activated_by"] == user_id else "used"
        conn.close(); return res
    conn.execute("UPDATE serials SET activated_by = ?, activated_at = ? WHERE code = ?", (user_id, _now(), code))
    conn.commit(); conn.close(); return "ok"

def revoke_serial(code):
    conn = get_conn()
    c = conn.execute("UPDATE serials SET status = 'revoked' WHERE code = ?", (code,))
    n = c.rowcount
    conn.commit(); conn.close(); return n > 0

def delete_serial(code):
    conn = get_conn()
    c = conn.execute("DELETE FROM serials WHERE code = ?", (code,))
    n = c.rowcount
    conn.commit(); conn.close(); return n > 0

def get_user_serial(user_id):
    conn = get_conn()
    r = conn.execute("SELECT * FROM serials WHERE activated_by = ? AND status = 'active' ORDER BY activated_at DESC LIMIT 1", (user_id,)).fetchone()
    conn.close(); return r

def get_stats():
    conn = get_conn()
    t = conn.execute("SELECT COUNT(*) FROM serials").fetchone()[0]
    a = conn.execute("SELECT COUNT(*) FROM serials WHERE status = 'active'").fetchone()[0]
    r = conn.execute("SELECT COUNT(*) FROM serials WHERE status = 'revoked'").fetchone()[0]
    u = conn.execute("SELECT COUNT(*) FROM serials WHERE activated_by IS NOT NULL").fetchone()[0]
    conn.close(); return {"total": t, "active": a, "revoked": r, "activated": u}

def list_serials(limit=30):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM serials ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close(); return rows

# ============ الواجهة ============
def is_admin(uid): return uid == ADMIN_ID

def is_activated(uid):
    if is_admin(uid): return True
    return get_user_serial(uid) is not None

def admin_text():
    s = get_stats()
    return f"👑 <b>لوحة التحكم</b>\n📊 الإجمالي: {s['total']}/{MAX_SERIALS}\n✅ نشط: {s['active']}\n🚫 ملغي: {s['revoked']}\n🎯 مفعل: {s['activated']}"

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎫 توليد سيريال", callback_data="gen")],
        [InlineKeyboardButton("📋 عرض السيريالات", callback_data="list")],
    ])

def user_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐍 حل مسار بايثون", callback_data="solve_python")],
        [InlineKeyboardButton("🌐 حل مسار جافاسكريبت", callback_data="solve_js")],
        [InlineKeyboardButton("💼 حل الثقافة المالية", callback_data="solve_finance")],
    ])

# ============ الأوامر ============
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        await update.message.reply_text(admin_text(), reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
    elif is_activated(uid):
        await update.message.reply_text("👋 أهلاً بيك يا بطل! اختر القسم اللي عايز تحله:", reply_markup=user_menu_kb())
    else:
        await update.message.reply_text("🔐 ابعتلي السيريال بتاعك عشان تفعل البوت:")

async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id): await q.answer("⛔"); return
    await q.answer()
    data = q.data

    if data == "gen":
        if get_stats()["total"] >= MAX_SERIALS:
            await q.edit_message_text("⚠️ وصلت للحد الأقصى.")
        else:
            code = create_serial()
            await q.edit_message_text(f"🎫 سيريال جديد:\n<code>{code}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎫 واحد كمان", callback_data="gen")],[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]), parse_mode=ParseMode.HTML)
    elif data == "back":
        await q.edit_message_text(admin_text(), reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
    elif data == "list":
        rows = list_serials()
        kb = [[InlineKeyboardButton(f"{r['code']} {'✅' if r['status']=='active' else '🚫'}", callback_data=f"view:{r['code']}")] for r in rows]
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
        await q.edit_message_text("📋 السيريالات:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("view:"):
        code = data.split(":")[1]
        r = get_serial(code)
        kb = [[InlineKeyboardButton("🚫 إلغاء", callback_data=f"rev:{code}")],[InlineKeyboardButton("🗑 حذف", callback_data=f"del:{code}")],[InlineKeyboardButton("🔙 رجوع", callback_data="list")]]
        await q.edit_message_text(f"🎫 <code>{code}</code>\nالحالة: {r['status']}", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    elif data.startswith("rev:"):
        revoke_serial(data.split(":")[1])
        await q.edit_message_text("🚫 تم الإلغاء.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="list")]]))
    elif data.startswith("del:"):
        delete_serial(data.split(":")[1])
        await q.edit_message_text("🗑 تم الحذف.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="list")]]))

async def user_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_activated(q.from_user.id): await q.answer("⛔ ابعت السيريال الأول", show_alert=True); return
    await q.answer()
    data = q.data
    msg = "❌ نوع غير معروف."
    if data == "solve_python": msg = "🐍 <b>بايثون:</b> ابعتلي صورة السؤال أو الكود، وأنا هحلهولك فوراً."
    elif data == "solve_js": msg = "🌐 <b>جافاسكريبت:</b> ابعتلي صورة السؤال أو الكود، وأنا هحلهولك فوراً."
    elif data == "solve_finance": msg = "💼 <b>ثقافة مالية:</b> ابعتلي صورة السؤال وأنا هجاوبك."
    await q.edit_message_text(msg, parse_mode=ParseMode.HTML)

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid): return
    if not is_activated(uid):
        text = (update.message.text or "").strip().upper()
        res = activate_serial(text, uid)
        if res == "ok": await update.message.reply_text("✅ تم التفعيل! اختر القسم:", reply_markup=user_menu_kb())
        elif res == "used": await update.message.reply_text("⚠️ السيريال مستخدم.")
        elif res == "revoked": await update.message.reply_text("🚫 السيريال ملغي.")
        else: await update.message.reply_text("❌ سيريال غلط.")
    else:
        # هنا بيحول الصورة أو السؤال لمحرك الحل
        await update.message.reply_text("⏳ جاري الحل...")
        result = await solver.solve_question(update.message)
        await update.message.reply_text(result, parse_mode=ParseMode.HTML)

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^(gen|back|list|view:|rev:|del:)"))
    app.add_handler(CallbackQueryHandler(user_callback, pattern="^(solve_)"))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_msg))
    app.run_polling()
