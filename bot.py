import os
import sqlite3
import secrets
import string
import logging
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def _safe_int(v, default=0):
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = _safe_int(os.getenv("ADMIN_ID", "0"))
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS serials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            activated_by INTEGER,
            activated_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def _now():
    return datetime.now(timezone.utc).isoformat()


def serial_exists(code):
    conn = get_conn()
    r = conn.execute("SELECT 1 FROM serials WHERE code = ?", (code,)).fetchone()
    conn.close()
    return r is not None


def gen_unique_serial():
    while True:
        raw = ''.join(secrets.choice(ALPHABET) for _ in range(16))
        code = '-'.join(raw[i:i + 4] for i in range(0, 16, 4))
        if not serial_exists(code):
            return code


def create_serial():
    code = gen_unique_serial()
    conn = get_conn()
    conn.execute(
        "INSERT INTO serials (code, status, created_at) VALUES (?, 'active', ?)",
        (code, _now()),
    )
    conn.commit()
    conn.close()
    return code


def get_serial(code):
    conn = get_conn()
    r = conn.execute("SELECT * FROM serials WHERE code = ?", (code,)).fetchone()
    conn.close()
    return r


def activate_serial(code, user_id):
    conn = get_conn()
    r = conn.execute("SELECT * FROM serials WHERE code = ?", (code,)).fetchone()
    if not r:
        conn.close(); return "not_found"
    if r["status"] != "active":
        conn.close(); return "revoked"
    if r["activated_by"] is not None:
        if r["activated_by"] == user_id:
            conn.close(); return "already_yours"
        conn.close(); return "used"
    conn.execute(
        "UPDATE serials SET activated_by = ?, activated_at = ? WHERE code = ?",
        (user_id, _now(), code),
    )
    conn.commit(); conn.close()
    return "ok"


def revoke_serial(code):
    conn = get_conn()
    c = conn.execute("UPDATE serials SET status = 'revoked' WHERE code = ?", (code,))
    n = c.rowcount
    conn.commit(); conn.close()
    return n > 0


def unrevoke_serial(code):
    conn = get_conn()
    c = conn.execute("UPDATE serials SET status = 'active' WHERE code = ? AND status = 'revoked'", (code,))
    n = c.rowcount
    conn.commit(); conn.close()
    return n > 0


def delete_serial(code):
    conn = get_conn()
    c = conn.execute("DELETE FROM serials WHERE code = ?", (code,))
    n = c.rowcount
    conn.commit(); conn.close()
    return n > 0


def get_user_serial(user_id):
    conn = get_conn()
    r = conn.execute(
        "SELECT * FROM serials WHERE activated_by = ? AND status = 'active' ORDER BY activated_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    conn.close()
    return r


def get_stats():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM serials").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM serials WHERE status = 'active'").fetchone()[0]
    revoked = conn.execute("SELECT COUNT(*) FROM serials WHERE status = 'revoked'").fetchone()[0]
    activated = conn.execute("SELECT COUNT(*) FROM serials WHERE activated_by IS NOT NULL").fetchone()[0]
    conn.close()
    return {"total": total, "active": active, "revoked": revoked, "activated": activated}


def list_serials(limit=30):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM serials ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows


# ============ مساعدات الواجهة ============
def is_admin(uid):
    return uid == ADMIN_ID and ADMIN_ID != 0


def admin_text():
    s = get_stats()
    return (
        "👑 <b>لوحة تحكم المدير</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 إجمالي: <b>{s['total']} / {MAX_SERIALS}</b>\n"
        f"✅ نشطة: <b>{s['active']}</b>\n"
        f"🚫 ملغاة: <b>{s['revoked']}</b>\n"
        f"🎯 مُفعّلة: <b>{s['activated']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "اختر من القائمة:"
    )


def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎫 توليد سيريال جديد", callback_data="gen")],
        [InlineKeyboardButton("📋 عرض السيريالات", callback_data="list")],
        [InlineKeyboardButton("📊 تحديث", callback_data="back")],
    ])


# ============ Handlers ============
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        await update.message.reply_text(admin_text(), reply_markup=admin_kb(), parse_mode=ParseMode.HTML)
    else:
        r = get_user_serial(uid)
        if r:
            await update.message.reply_text(
                f"✅ أنت مفعّل بالفعل!\n🔑 <code>{r['code']}</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                "👋 أهلاً بيك!\n\n"
                "🔐 ابعتلي <b>السيريال</b> بتاعك عشان تفعّل البوت.\n\n"
                "مثال: <code>ABCD-EFGH-IJKL-MNOP</code>",
                parse_mode=ParseMode.HTML,
            )


async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("⛔ مش مسموح", show_alert=True); return
    await q.answer()
    data = q.data

    if data == "gen":
        s = get_stats()
        if s["total"] >= MAX_SERIALS:
            await q.edit_message_text(
                f"⚠️ وصلت للحد ({MAX_SERIALS}). احذف سيريالات قديمة.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]),
            ); return
        code = create_serial()
        await q.edit_message_text(
            "🎫 <b>سيريال جديد:</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{code}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋 اضغط عليه للنسخ، وابعته للزبون.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎫 واحد كمان", callback_data="gen")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="back")],
            ]),
            parse_mode=ParseMode.HTML,
        )

    elif data in ("back", "stats"):
        await q.edit_message_text(admin_text(), reply_markup=admin_kb(), parse_mode=ParseMode.HTML)

    elif data == "list":
        rows = list_serials()
        if not rows:
            await q.edit_message_text(
                "📭 مفيش سيريالات.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]),
            ); return
        kb = []
        for r in rows:
            s = "✅" if r["status"] == "active" else "🚫"
            u = "🎯" if r["activated_by"] else "⚪"
            kb.append([InlineKeyboardButton(f"{s}{u} {r['code']}", callback_data=f"view:{r['code']}")])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
        await q.edit_message_text(
            "📋 <b>السيريالات (اضغط للتحكم):</b>",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("view:"):
        code = data.split(":", 1)[1]
        r = get_serial(code)
        if not r:
            await q.edit_message_text("❌ مش موجود."); return
        status = "✅ نشط" if r["status"] == "active" else "🚫 ملغي"
        act = "⚪ لم يُفعّل" if not r["activated_by"] else f"🎯 مُفعّل ({r['activated_by']})"
        kb = []
        if r["status"] == "active":
            kb.append([InlineKeyboardButton("🚫 إلغاء", callback_data=f"rev:{code}")])
        else:
            kb.append([InlineKeyboardButton("♻️ إعادة تفعيل", callback_data=f"unrev:{code}")])
        kb.append([InlineKeyboardButton("🗑 حذف نهائي", callback_data=f"del:{code}")])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="list")])
        await q.edit_message_text(
            f"🎫 <b>تفاصيل:</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"<code>{code}</code>\n"
            f"الحالة: {status}\n"
            f"التفعيل: {act}\n"
            f"أُنشئ: {r['created_at'][:19]}",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith(("rev:", "unrev:", "del:")):
        action, code = data.split(":", 1)
        msg = ""
        if action == "rev" and revoke_serial(code): msg = f"🚫 تم إلغاء: <code>{code}</code>"
        elif action == "unrev" and unrevoke_serial(code): msg = f"♻️ تم إعادة التفعيل: <code>{code}</code>"
        elif action == "del" and delete_serial(code): msg = f"🗑 تم الحذف: <code>{code}</code>"
        else: msg = "❌ فشلت العملية."
        await q.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع للقائمة", callback_data="list")]]),
            parse_mode=ParseMode.HTML,
        )


async def client_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_admin(uid):
        return
    if get_user_serial(uid):
        await update.message.reply_text("✅ أنت مفعّل بالفعل.")
        return
    text = (update.message.text or "").strip().upper()
    r = activate_serial(text, uid)
    replies = {
        "ok": f"✅ <b>تم التفعيل!</b>\n🔑 <code>{text}</code>\nمرحباً بيك، البوت مفتوح ليك. 🎉",
        "already_yours": "ℹ️ السيريال بتاعك ومفعّل بالفعل.",
        "used": "⚠️ السيريال مستخدم بالفعل.",
        "revoked": "🚫 السيريال ملغي.",
        "not_found": "❌ السيريال غلط أو مش موجود.",
    }
    await update.message.reply_text(replies.get(r, "❌ خطأ."), parse_mode=ParseMode.HTML)


async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text(admin_text(), reply_markup=admin_kb(), parse_mode=ParseMode.HTML)


async def revoke_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("استخدام: /revoke CODE"); return
    code = ctx.args[0].strip().upper()
    await update.message.reply_text(
        f"🚫 تم إلغاء: <code>{code}</code>" if revoke_serial(code) else "❌ مش موجود.",
        parse_mode=ParseMode.HTML,
    )


async def delete_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    if not ctx.args:
        await update.message.reply_text("استخدام: /delete CODE"); return
    code = ctx.args[0].strip().upper()
    await update.message.reply_text(
        f"🗑 تم الحذف: <code>{code}</code>" if delete_serial(code) else "❌ مش موجود.",
        parse_mode=ParseMode.HTML,
    )


# ============ main ============
def main():
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN مش موجود")
    if not ADMIN_ID:
        raise SystemExit("❌ ADMIN_ID مش موجود")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("revoke", revoke_cmd))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CallbackQueryHandler(admin_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, client_msg))
    logger.info("✅ البوت شغال")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
