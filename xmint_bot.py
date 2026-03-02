import logging
import asyncio
import re
import time
import httpx
from datetime import datetime
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# =============================================
#              CONFIG
# =============================================
BOT_TOKEN = "8609781731:AAEZzctHzmLndplCWf0XhuY9RyJvRoTLAfk"
ADMIN_ID = 1984916365
CHANNEL_USERNAME = "@alwaysrvice24hours"
CHANNEL_LINK = "https://t.me/alwaysrvice24hours"

# x.mint credentials
XMINT_EMAIL = "aboos7008@gmail.com"
XMINT_PASSWORD = "Siam12345678@"
XMINT_BASE = "https://x.mnitnetwork.com/mapi/v1"

logging.basicConfig(level=logging.INFO)

# =============================================
#         DATA STORE
# =============================================
number_pool = {}
user_data = {}
_token_cache = {"token": None, "session": None, "time": 0}

# =============================================
#         X.MINT API (stexsms same)
# =============================================

async def xmint_login():
    global _token_cache
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                f"{XMINT_BASE}/mauth/login",
                json={"email": XMINT_EMAIL, "password": XMINT_PASSWORD}
            )
        data = res.json()
        if data.get("meta", {}).get("code") == 200:
            token = data["data"]["token"]
            session = data["data"]["session_token"]
            _token_cache = {"token": token, "session": session, "time": time.time()}
            logging.info("✅ x.mint login সফল!")
            return token, session
        logging.error(f"x.mint login failed: {data}")
        return None, None
    except Exception as e:
        logging.error(f"x.mint login error: {e}")
        return None, None

async def get_token():
    if _token_cache["token"] and (time.time() - _token_cache["time"]) < 1500:
        return _token_cache["token"], _token_cache["session"]
    return await xmint_login()

def get_headers(token, session):
    return {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "mauthtoken": token,
        "Cookie": f"mauthtoken={token}; session_token={session}"
    }

async def get_console_ranges():
    """x.mint থেকে Facebook ranges নাও"""
    try:
        token, session = await get_token()
        if not token:
            return []
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{XMINT_BASE}/mdashboard/console/info",
                headers=get_headers(token, session)
            )
        data = res.json()
        if data.get("meta", {}).get("code") == 200:
            logs = data["data"].get("logs", [])
            seen = set()
            ranges = []
            for log in logs:
                app = log.get("app_name", "").replace("*", "").strip().upper()
                if app == "FACEBOOK":
                    r = log.get("range", "").strip()
                    if r and r not in seen:
                        seen.add(r)
                        ranges.append(r)
            return ranges
        return []
    except Exception as e:
        logging.error(f"Range fetch error: {e}")
        return []

async def get_number_from_range(range_val):
    """x.mint থেকে number নাও"""
    try:
        clean_range = ''.join(c for c in range_val.upper() if c.isdigit() or c == 'X')
        if not clean_range:
            return None
        if len(clean_range) - len(clean_range.rstrip('X')) < 3:
            clean_range = clean_range.rstrip('X') + 'XXX'
        token, session = await get_token()
        if not token:
            return None
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(
                f"{XMINT_BASE}/mdashboard/getnum/number",
                json={"range": clean_range, "is_national": False, "remove_plus": False, "app": "FACEBOOK"},
                headers=get_headers(token, session)
            )
        data = res.json()
        if data.get("meta", {}).get("code") == 200:
            num = data["data"]
            number = num.get("number") or num.get("num")
            if number:
                return str(number).replace("+", "").strip()
        return None
    except Exception as e:
        logging.error(f"Get number error: {e}")
        return None

async def check_otp(number, wait=120):
    """x.mint থেকে OTP check করো"""
    clean = str(number).replace("+", "").strip()
    start = time.time()
    while (time.time() - start) < wait:
        try:
            token, session = await get_token()
            if not token:
                await asyncio.sleep(5)
                continue
            today = datetime.now().strftime("%Y-%m-%d")
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(
                    f"{XMINT_BASE}/mdashboard/getnum/info",
                    params={"date": today, "page": 1, "search": clean, "status": "success"},
                    headers=get_headers(token, session)
                )
            data = res.json()
            if data.get("meta", {}).get("code") == 200:
                nums = data["data"].get("numbers") or []
                for n in nums:
                    api_num = str(n.get("number", "")).replace("+", "").strip()
                    if clean in api_num or api_num in clean:
                        raw = (n.get("otp") or n.get("message") or "").strip()
                        match = re.search(r'\b(\d{5,8})\b', raw)
                        if match:
                            return match.group(1)
        except Exception as e:
            logging.error(f"OTP check error: {e}")
        await asyncio.sleep(5)
    return None

# =============================================
#         HELPERS
# =============================================

def init_user(user_id):
    if user_id not in user_data:
        user_data[user_id] = {
            "name": "User",
            "current_number": None,
            "waiting_for": None,
            "range_index": 0,
        }

async def check_joined(user_id, bot):
    now = time.time()
    cached = user_data.get(user_id, {}).get("join_cache")
    if cached and (now - cached["time"]) < 600:
        return cached["joined"]
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        joined = member.status in ["member", "administrator", "creator"]
        if user_id not in user_data:
            init_user(user_id)
        user_data[user_id]["join_cache"] = {"joined": joined, "time": now}
        return joined
    except:
        return True

# Ranges cache
_ranges_cache = {"ranges": [], "time": 0}

async def get_ranges():
    global _ranges_cache
    if _ranges_cache["ranges"] and (time.time() - _ranges_cache["time"]) < 300:
        return _ranges_cache["ranges"]
    ranges = await get_console_ranges()
    if ranges:
        _ranges_cache = {"ranges": ranges, "time": time.time()}
    return ranges

# =============================================
#         KEYBOARDS
# =============================================

def main_keyboard(user_id=None):
    buttons = [
        [KeyboardButton("🏠 Home"), KeyboardButton("📞 Get Number")],
        [KeyboardButton("👁️ Check OTP"), KeyboardButton("📋 My Number")],
    ]
    if user_id and user_id == ADMIN_ID:
        buttons.append([KeyboardButton("👑 Admin Panel")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def after_number_keyboard(number):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ Check OTP", callback_data=f"checkotp_{number}")],
        [InlineKeyboardButton("🔄 New Number", callback_data="get_number"),
         InlineKeyboardButton("🏠 Home", callback_data="go_home")],
    ])

# =============================================
#         HANDLERS
# =============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    init_user(user_id)
    user_data[user_id]["name"] = user.first_name or "User"

    joined = await check_joined(user_id, context.bot)
    if not joined:
        await update.message.reply_text(
            "⚠️ Channel Join করুন!\n\nBot ব্যবহার করতে channel join করতে হবে।",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Channel Join করুন", url=CHANNEL_LINK)
            ]])
        )
        return

    ranges = await get_ranges()

    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👋 Welcome, {user.first_name}!\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📞 X.MINT OTP BOT\n\n"
        f"📡 Active Ranges: {len(ranges)}\n\n"
        f"👇 নিচের button চাপুন:\n"
        f"━━━━━━━━━━━━━━━━━━",
        reply_markup=main_keyboard(user_id)
    )

async def cmd_get_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    init_user(user_id)

    joined = await check_joined(user_id, context.bot)
    if not joined:
        await update.message.reply_text(
            "⚠️ Channel Join করুন!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Join", url=CHANNEL_LINK)
            ]])
        )
        return

    # আগের number আছে?
    current = user_data[user_id].get("current_number")
    if current:
        await update.message.reply_text(
            f"⚠️ তোমার কাছে আগের number আছে!\n\n📞 `{current}`",
            parse_mode="Markdown",
            reply_markup=after_number_keyboard(current)
        )
        return

    await update.message.reply_text("⏳ Number নেওয়া হচ্ছে...")

    ranges = await get_ranges()
    if not ranges:
        await update.message.reply_text(
            "❌ কোনো range পাওয়া যায়নি!",
            reply_markup=main_keyboard(user_id)
        )
        return

    # Range থেকে number নাও
    range_idx = user_data[user_id].get("range_index", 0)
    number = None

    for i in range(len(ranges)):
        idx = (range_idx + i) % len(ranges)
        number = await get_number_from_range(ranges[idx])
        if number:
            user_data[user_id]["range_index"] = (idx + 1) % len(ranges)
            break

    if not number:
        await update.message.reply_text(
            "❌ Number পাওয়া যায়নি! কিছুক্ষণ পর try করুন।",
            reply_markup=main_keyboard(user_id)
        )
        return

    user_data[user_id]["current_number"] = number

    await update.message.reply_text(
        f"✅ Number পাওয়া গেছে!\n\n"
        f"📞 `{number}`\n\n"
        f"🔍 OTP আসার অপেক্ষায়...",
        parse_mode="Markdown",
        reply_markup=after_number_keyboard(number)
    )

    asyncio.create_task(auto_otp_check(update.message, number, user_id))

async def auto_otp_check(message, number, user_id):
    otp = await check_otp(number, wait=120)

    if user_data.get(user_id, {}).get("current_number") != number:
        return

    if otp:
        await message.reply_text(
            f"🔑 OTP পাওয়া গেছে!\n\n"
            f"📞 Number: `{number}`\n"
            f"🔑 OTP: `{otp}`",
            parse_mode="Markdown",
            reply_markup=main_keyboard(user_id)
        )
        user_data[user_id]["current_number"] = None
    else:
        await message.reply_text(
            f"⏳ OTP আসেনি!\n\n📞 `{number}`\n\nআবার try করুন।",
            parse_mode="Markdown",
            reply_markup=after_number_keyboard(number)
        )

# =============================================
#         ADMIN COMMANDS
# =============================================

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    token, _ = await get_token()
    xmint_status = "✅ Connected" if token else "❌ Disconnected"
    ranges = await get_ranges()
    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 BOT STATS\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Users: {len(user_data)}\n"
        f"📡 Ranges: {len(ranges)}\n"
        f"🔗 x.mint: {xmint_status}\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    global _ranges_cache, _token_cache
    _ranges_cache = {"ranges": [], "time": 0}
    _token_cache = {"token": None, "session": None, "time": 0}
    token, _ = await get_token()
    ranges = await get_ranges()
    await update.message.reply_text(
        f"✅ Refresh হয়েছে!\n\n"
        f"🔗 x.mint: {'✅' if token else '❌'}\n"
        f"📡 Ranges: {len(ranges)}"
    )

# =============================================
#         CALLBACK HANDLER
# =============================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    init_user(user_id)
    data = query.data

    if data == "go_home":
        ranges = await get_ranges()
        await query.message.reply_text(
            f"🏠 Home\n\n📡 Active Ranges: {len(ranges)}",
            reply_markup=main_keyboard(user_id)
        )

    elif data == "get_number":
        user_data[user_id]["current_number"] = None
        await cmd_get_number_callback(query, user_id)

    elif data.startswith("checkotp_"):
        number = data.replace("checkotp_", "")
        await query.message.reply_text("⏳ OTP check হচ্ছে...")
        otp = await check_otp(number, wait=30)
        if otp:
            await query.message.reply_text(
                f"🔑 OTP পাওয়া গেছে!\n\n"
                f"📞 Number: `{number}`\n"
                f"🔑 OTP: `{otp}`",
                parse_mode="Markdown",
                reply_markup=main_keyboard(user_id)
            )
            user_data[user_id]["current_number"] = None
        else:
            await query.message.reply_text(
                "⏳ OTP এখনো আসেনি।",
                reply_markup=after_number_keyboard(number)
            )

async def cmd_get_number_callback(query, user_id):
    await query.message.reply_text("⏳ Number নেওয়া হচ্ছে...")
    ranges = await get_ranges()
    if not ranges:
        await query.message.reply_text("❌ কোনো range নেই!")
        return

    range_idx = user_data[user_id].get("range_index", 0)
    number = None

    for i in range(len(ranges)):
        idx = (range_idx + i) % len(ranges)
        number = await get_number_from_range(ranges[idx])
        if number:
            user_data[user_id]["range_index"] = (idx + 1) % len(ranges)
            break

    if not number:
        await query.message.reply_text("❌ Number পাওয়া যায়নি!")
        return

    user_data[user_id]["current_number"] = number

    await query.message.reply_text(
        f"✅ Number পাওয়া গেছে!\n\n"
        f"📞 `{number}`\n\n"
        f"🔍 OTP আসার অপেক্ষায়...",
        parse_mode="Markdown",
        reply_markup=after_number_keyboard(number)
    )
    asyncio.create_task(auto_otp_check(query.message, number, user_id))

# =============================================
#         MESSAGE HANDLER
# =============================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if update.message.text else ""
    user = update.effective_user
    user_id = user.id
    init_user(user_id)
    user_data[user_id]["name"] = user.first_name or "User"

    joined = await check_joined(user_id, context.bot)
    if not joined:
        await update.message.reply_text(
            "⚠️ Channel Join করুন!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Join", url=CHANNEL_LINK)
            ]])
        )
        return

    if text == "🏠 Home":
        await start(update, context)
    elif text == "📞 Get Number":
        await cmd_get_number(update, context)
    elif text == "👁️ Check OTP":
        number = user_data[user_id].get("current_number")
        if not number:
            await update.message.reply_text(
                "❌ তোমার কাছে কোনো number নেই!",
                reply_markup=main_keyboard(user_id)
            )
            return
        await update.message.reply_text("⏳ OTP check হচ্ছে...")
        otp = await check_otp(number, wait=30)
        if otp:
            await update.message.reply_text(
                f"🔑 OTP পাওয়া গেছে!\n\n"
                f"📞 Number: `{number}`\n"
                f"🔑 OTP: `{otp}`",
                parse_mode="Markdown",
                reply_markup=main_keyboard(user_id)
            )
            user_data[user_id]["current_number"] = None
        else:
            await update.message.reply_text(
                "⏳ OTP এখনো আসেনি।",
                reply_markup=after_number_keyboard(number)
            )
    elif text == "📋 My Number":
        number = user_data[user_id].get("current_number")
        if number:
            await update.message.reply_text(
                f"📞 তোমার current number:\n\n`{number}`",
                parse_mode="Markdown",
                reply_markup=after_number_keyboard(number)
            )
        else:
            await update.message.reply_text(
                "❌ তোমার কাছে কোনো number নেই!",
                reply_markup=main_keyboard(user_id)
            )
    elif text == "👑 Admin Panel":
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ Admin access নেই!")
            return
        ranges = await get_ranges()
        await update.message.reply_text(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👑 ADMIN PANEL\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 /stats — bot stats\n"
            f"🔄 /refresh — ranges refresh\n\n"
            f"📡 Active Ranges: {len(ranges)}\n\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

# =============================================
#              MAIN
# =============================================

async def post_init(application):
    token, _ = await xmint_login()
    if token:
        ranges = await get_ranges()
        logging.info(f"✅ x.mint ready! Ranges: {len(ranges)}")
    else:
        logging.warning("⚠️ x.mint login failed!")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).read_timeout(30).write_timeout(30).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ x.mint OTP Bot running...")
    app.run_polling(drop_pending_updates=True)
