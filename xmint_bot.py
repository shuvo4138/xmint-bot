import logging
import asyncio
import re
import random
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
BOT_TOKEN = "8324318903:AAGdRDJdrASCk1JF8iK60fhv8rHazm3Jt4A"

# X.MINT (S2)
XMINT_EMAIL = "Pxerosltd@gmail.com"
XMINT_PASSWORD = "Pass@@22@@"
XMINT_BASE_URL = "https://x.mnitnetwork.com/mapi/v1"

ADMIN_ID = 7308940812
MAIN_CHANNEL_ID = -1002660970725
CHANNEL_LINK = " "  # ← আপনার main channel invite link দিন

# OTP Forward Channel
OTP_CHANNEL_ID = -1002656998895

# Get 100 access control
GET100_ENABLED = False
GET100_USERS = set()

logging.basicConfig(level=logging.INFO)

user_data = {}
user_locks = {}
user_msg = {}
user_range_msg = {}

# Console cache
_xmint_console_cache = {"logs": [], "time": 0}

# =============================================
#         APP EMOJIS
# =============================================

APP_EMOJIS = {
    "FACEBOOK": "📘", "INSTAGRAM": "📸", "TIKTOK": "🎵",
    "SNAPCHAT": "👻", "TWITTER": "🐦", "GOOGLE": "🔍",
    "WHATSAPP": "💬", "TELEGRAM": "✈️", "CHATGPT": "🤖",
}

# =============================================
#         X.MINT SESSION POOL (S2)
# =============================================

class XMintSessionPool:
    def __init__(self):
        self.number_sessions = asyncio.Queue()
        self.otp_sessions = asyncio.Queue()
        self.all_sessions = []
        self.initialized = False
        self.lock = asyncio.Lock()

    async def initialize(self):
        async with self.lock:
            if self.initialized:
                return
            logging.info("🔄 S2 (X.Mint) Session pool initialize হচ্ছে...")
            results = []
            for i in range(50):  # 25 number + 25 OTP
                r = await self._login_once()
                results.append(r)
                await asyncio.sleep(3)

            number_count = 0
            otp_count = 0
            for r in results:
                if isinstance(r, dict) and r.get("token"):
                    self.all_sessions.append(r)
                    if number_count < 25:
                        await self.number_sessions.put(r)
                        number_count += 1
                    elif otp_count < 25:
                        await self.otp_sessions.put(r)
                        otp_count += 1

            self.initialized = True
            logging.info(f"✅ S2 (X.Mint) Session pool ready! Number: {number_count}, OTP: {otp_count}")

    async def _login_once(self):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.post(
                    f"{XMINT_BASE_URL}/mauth/login",
                    json={"email": XMINT_EMAIL, "password": XMINT_PASSWORD}
                )
            if res.status_code == 403:
                logging.error("X.Mint: 403 Forbidden")
                return {}
            if res.status_code != 200:
                logging.warning(f"X.Mint: HTTP {res.status_code}")
                return {}
            try:
                data = res.json()
            except Exception as e:
                logging.error(f"X.Mint: Invalid JSON - {e}")
                return {}
            if data.get("meta", {}).get("code") == 200:
                token = data["data"].get("token")
                if token:
                    return {
                        "token": token,
                        "session": "",
                        "time": time.time()
                    }
        except Exception as e:
            logging.error(f"❌ X.Mint Login error: {e}")
        return {}

    async def get_number_session(self):
        try:
            session = await asyncio.wait_for(self.number_sessions.get(), timeout=30)
            if time.time() - session.get("time", 0) > 1500:
                new_session = await self._login_once()
                if new_session.get("token"):
                    return new_session
                session["time"] = time.time()
            return session
        except asyncio.TimeoutError:
            new_session = await self._login_once()
            if new_session.get("token"):
                return new_session
            if self.all_sessions:
                return self.all_sessions[0]
            return {}

    async def get_otp_session(self):
        try:
            session = await asyncio.wait_for(self.otp_sessions.get(), timeout=30)
            if time.time() - session.get("time", 0) > 1500:
                new_session = await self._login_once()
                if new_session.get("token"):
                    return new_session
                session["time"] = time.time()
            return session
        except asyncio.TimeoutError:
            new_session = await self._login_once()
            if new_session.get("token"):
                return new_session
            if self.all_sessions:
                return self.all_sessions[0]
            return {}

    async def return_number_session(self, session):
        if session and session.get("token"):
            await self.number_sessions.put(session)

    async def return_otp_session(self, session):
        if session and session.get("token"):
            await self.otp_sessions.put(session)

    async def refresh_all(self):
        logging.info("🔄 X.Mint Session pool refresh হচ্ছে...")
        async with self.lock:
            self.initialized = False
            while not self.number_sessions.empty():
                try:
                    self.number_sessions.get_nowait()
                except asyncio.QueueEmpty:
                    break
            while not self.otp_sessions.empty():
                try:
                    self.otp_sessions.get_nowait()
                except asyncio.QueueEmpty:
                    break
            self.all_sessions.clear()
        await self.initialize()

xmint_pool = XMintSessionPool()

# =============================================
#         X.MINT API FUNCTIONS
# =============================================

async def api_get_number_s2(range_val, app_name="FACEBOOK"):
    logging.info(f"🔵 X.Mint: Getting number for {app_name}, range: {range_val}")

    clean_range = ''.join(c for c in range_val.upper() if c.isdigit() or c == 'X')
    if not clean_range:
        return {"error": "Invalid range"}, None
    x_count = len(clean_range) - len(clean_range.rstrip('X'))
    if x_count < 3:
        clean_range = clean_range.rstrip('X') + 'XXX'

    session = await xmint_pool.get_number_session()
    try:
        token = session.get("token")
        if not token:
            return {"error": "No session available"}, None

        payload = {
            "range": clean_range,
            "is_national": False,
            "remove_plus": True,
            "app": app_name
        }

        headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
            'Accept': "application/json",
            'Content-Type': "application/json",
            'mauthtoken': token,
            'Cookie': f"mautToken={token}"
        }

        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(
                f"{XMINT_BASE_URL}/mdashboard/getnum/number",
                json=payload,
                headers=headers
            )

        if res.status_code == 403:
            logging.warning("⚠️ S2 number: 403 — relogin")
            await xmint_pool.return_number_session(session)
            new_session = await xmint_pool._login_once()
            return {"error": "session_expired"}, new_session if new_session.get("token") else None

        result = res.json()
        return result, session
    except Exception as e:
        logging.error(f"❌ api_get_number_s2 error: {e}")
        await xmint_pool.return_number_session(session)
        return {"error": str(e)}, None

async def api_get_info_s2(search="", status="", saved_session=None):
    session = saved_session if saved_session and saved_session.get("token") else await xmint_pool.get_otp_session()
    _from_pool = not (saved_session and saved_session.get("token"))
    try:
        token = session.get("token")
        if not token:
            return {"error": "No session available"}
        clean_search = search.replace("+", "").strip()
        today = datetime.now().strftime("%Y-%m-%d")
        params = {"date": today, "page": 1, "search": clean_search, "status": status}
        headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10)",
            'Accept': "application/json",
            'Content-Type': "application/json",
            'mauthtoken': token,
            'Cookie': f"mautToken={token}"
        }
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{XMINT_BASE_URL}/mdashboard/getnum/info",
                params=params,
                headers=headers
            )
        return res.json()
    except Exception as e:
        logging.error(f"api_get_info_s2 error: {e}")
        return {"error": str(e)}
    finally:
        if _from_pool:
            await xmint_pool.return_otp_session(session)

ALL_APPS = [
    "FACEBOOK"
]

# =============================================
#         COUNTRY FLAGS & NAMES
# =============================================

COUNTRY_FLAGS = {
    "CM": "🇨🇲", "VN": "🇻🇳", "PK": "🇵🇰", "TZ": "🇹🇿",
    "TJ": "🇹🇯", "TG": "🇹🇬", "NG": "🇳🇬", "GH": "🇬🇭",
    "KE": "🇰🇪", "BD": "🇧🇩", "IN": "🇮🇳", "PH": "🇵🇭",
    "ID": "🇮🇩", "MM": "🇲🇲", "KH": "🇰🇭", "ET": "🇪🇹",
    "CD": "🇨🇩", "MZ": "🇲🇿", "MG": "🇲🇬", "CI": "🇨🇮",
    "SN": "🇸🇳", "ML": "🇲🇱", "BF": "🇧🇫", "GN": "🇬🇳",
    "ZM": "🇿🇲", "ZW": "🇿🇼", "RW": "🇷🇼", "UG": "🇺🇬",
    "AO": "🇦🇴", "SD": "🇸🇩", "MR": "🇲🇷", "NE": "🇳🇪",
    "TD": "🇹🇩", "SO": "🇸🇴", "BI": "🇧🇮", "BJ": "🇧🇯",
    "MW": "🇲🇼", "SL": "🇸🇱", "LR": "🇱🇷", "CF": "🇨🇫",
    "GQ": "🇬🇶", "GA": "🇬🇦", "CG": "🇨🇬", "DJ": "🇩🇯",
    "ER": "🇪🇷", "GM": "🇬🇲", "GW": "🇬🇼", "CV": "🇨🇻",
    "ST": "🇸🇹", "KM": "🇰🇲", "SC": "🇸🇨", "MU": "🇲🇺",
    "ZA": "🇿🇦", "NA": "🇳🇦", "BW": "🇧🇼", "LS": "🇱🇸",
    "SZ": "🇸🇿", "EG": "🇪🇬", "LY": "🇱🇾", "TN": "🇹🇳",
    "DZ": "🇩🇿", "MA": "🇲🇦", "MX": "🇲🇽", "BR": "🇧🇷",
    "CO": "🇨🇴", "PE": "🇵🇪", "VE": "🇻🇪", "AR": "🇦🇷",
    "CL": "🇨🇱", "EC": "🇪🇨", "BO": "🇧🇴", "PY": "🇵🇾",
    "UY": "🇺🇾", "GY": "🇬🇾", "SR": "🇸🇷", "GT": "🇬🇹",
    "HN": "🇭🇳", "SV": "🇸🇻", "NI": "🇳🇮", "CR": "🇨🇷",
    "PA": "🇵🇦", "CU": "🇨🇺", "DO": "🇩🇴", "HT": "🇭🇹",
    "TH": "🇹🇭", "LA": "🇱🇦", "MY": "🇲🇾", "SG": "🇸🇬",
    "TL": "🇹🇱", "NP": "🇳🇵", "LK": "🇱🇰", "AF": "🇦🇫",
    "IR": "🇮🇷", "IQ": "🇮🇶", "SY": "🇸🇾", "YE": "🇾🇪",
    "SA": "🇸🇦", "AE": "🇦🇪", "QA": "🇶🇦", "KW": "🇰🇼",
    "BH": "🇧🇭", "OM": "🇴🇲", "JO": "🇯🇴", "LB": "🇱🇧",
    "PS": "🇵🇸", "AM": "🇦🇲", "AZ": "🇦🇿", "GE": "🇬🇪",
    "KZ": "🇰🇿", "UZ": "🇺🇿", "TM": "🇹🇲", "KG": "🇰🇬",
    "MN": "🇲🇳", "RU": "🇷🇺", "UA": "🇺🇦", "BY": "🇧🇾",
    "MD": "🇲🇩", "RO": "🇷🇴", "BG": "🇧🇬", "RS": "🇷🇸",
    "HR": "🇭🇷", "BA": "🇧🇦", "MK": "🇲🇰", "AL": "🇦🇱",
    "ME": "🇲🇪", "SI": "🇸🇮", "SK": "🇸🇰", "CZ": "🇨🇿",
    "PL": "🇵🇱", "HU": "🇭🇺", "AT": "🇦🇹", "CH": "🇨🇭",
    "DE": "🇩🇪", "FR": "🇫🇷", "ES": "🇪🇸", "IT": "🇮🇹",
    "PT": "🇵🇹", "GB": "🇬🇧", "IE": "🇮🇪", "NL": "🇳🇱",
    "BE": "🇧🇪", "LU": "🇱🇺", "DK": "🇩🇰", "SE": "🇸🇪",
    "NO": "🇳🇴", "FI": "🇫🇮", "IS": "🇮🇸", "US": "🇺🇸",
    "CA": "🇨🇦", "AU": "🇦🇺", "NZ": "🇳🇿", "JP": "🇯🇵",
    "KR": "🇰🇷", "CN": "🇨🇳", "TW": "🇹🇼", "HK": "🇭🇰",
    "SS": "🇸🇸", "XK": "🇽🇰",
}

COUNTRY_NAME_TO_CODE = {
    "cameroon": "CM", "vietnam": "VN", "pakistan": "PK", "tanzania": "TZ",
    "tajikistan": "TJ", "togo": "TG", "nigeria": "NG", "ghana": "GH",
    "kenya": "KE", "bangladesh": "BD", "india": "IN", "philippines": "PH",
    "indonesia": "ID", "myanmar": "MM", "cambodia": "KH", "ethiopia": "ET",
    "congo": "CD", "dr congo": "CD", "mozambique": "MZ", "madagascar": "MG",
    "ivory coast": "CI", "senegal": "SN", "mali": "ML", "burkina faso": "BF",
    "guinea": "GN", "zambia": "ZM", "zimbabwe": "ZW", "rwanda": "RW",
    "uganda": "UG", "angola": "AO", "sudan": "SD", "south sudan": "SS",
    "mauritania": "MR", "niger": "NE", "chad": "TD", "somalia": "SO",
    "burundi": "BI", "benin": "BJ", "malawi": "MW", "sierra leone": "SL",
    "liberia": "LR", "central african republic": "CF", "gabon": "GA",
    "djibouti": "DJ", "eritrea": "ER", "gambia": "GM", "cape verde": "CV",
    "south africa": "ZA", "namibia": "NA", "botswana": "BW", "lesotho": "LS",
    "egypt": "EG", "libya": "LY", "tunisia": "TN", "algeria": "DZ",
    "morocco": "MA", "mexico": "MX", "brazil": "BR", "colombia": "CO",
    "peru": "PE", "venezuela": "VE", "argentina": "AR", "chile": "CL",
    "ecuador": "EC", "bolivia": "BO", "paraguay": "PY", "uruguay": "UY",
    "usa": "US", "united states": "US", "canada": "CA",
    "thailand": "TH", "laos": "LA", "malaysia": "MY", "singapore": "SG",
    "nepal": "NP", "sri lanka": "LK", "afghanistan": "AF", "iran": "IR",
    "iraq": "IQ", "syria": "SY", "yemen": "YE", "saudi arabia": "SA",
    "uae": "AE", "united arab emirates": "AE", "qatar": "QA",
    "kuwait": "KW", "bahrain": "BH", "oman": "OM", "jordan": "JO",
    "lebanon": "LB", "palestine": "PS", "armenia": "AM", "azerbaijan": "AZ",
    "georgia": "GE", "kazakhstan": "KZ", "uzbekistan": "UZ",
    "russia": "RU", "ukraine": "UA", "belarus": "BY", "moldova": "MD",
    "romania": "RO", "bulgaria": "BG", "serbia": "RS", "croatia": "HR",
    "germany": "DE", "france": "FR", "spain": "ES", "italy": "IT",
    "portugal": "PT", "uk": "GB", "united kingdom": "GB", "ireland": "IE",
    "netherlands": "NL", "belgium": "BE", "denmark": "DK", "sweden": "SE",
    "norway": "NO", "finland": "FI", "australia": "AU", "new zealand": "NZ",
    "japan": "JP", "south korea": "KR", "china": "CN", "taiwan": "TW",
    "hong kong": "HK",
}

def get_flag(code):
    if not code:
        return "🌍"
    name_key = code.lower().strip()
    if name_key in COUNTRY_NAME_TO_CODE:
        return COUNTRY_FLAGS.get(COUNTRY_NAME_TO_CODE[name_key], "🌍")
    short = code.upper().strip()[:2]
    return COUNTRY_FLAGS.get(short, "🌍")

def extract_otp(message):
    if not message:
        return None
    match = re.search(r'\b(\d{8}|\d{6}|\d{5}|\d{4})\b', message)
    return match.group(1) if match else None

def detect_app_from_message(message, default_app=""):
    if not message:
        return default_app
    msg_lower = message.lower()
    for kw, app in [("facebook","FACEBOOK"),("whatsapp","WHATSAPP"),
                    ("telegram","TELEGRAM"),("instagram","INSTAGRAM"),
                    ("google","GOOGLE"),("twitter","TWITTER"),
                    ("tiktok","TIKTOK"),("snapchat","SNAPCHAT")]:
        if kw in msg_lower:
            return app
    return default_app

def has_get100_access(user_id):
    return GET100_ENABLED or user_id in GET100_USERS or user_id == ADMIN_ID

# =============================================
#         OTP CHANNEL FORWARD
# =============================================

def escape_mdv2(text):
    special = r'\_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in special else c for c in str(text))

async def send_otp_to_channel(bot, number, otp, app, country, flag, raw_sms=""):
    try:
        app_cap = app.capitalize()
        clean_num = str(number).replace("+", "").strip()
        hidden_num = "+" + clean_num[:5] + "xxxx" + clean_num[-3:] if len(clean_num) > 8 else clean_num

        country_code = ""
        if country and country.lower() not in ["postpaid", "post paid", "other"]:
            name_key = country.lower().strip()
            if name_key in COUNTRY_NAME_TO_CODE:
                country_code = COUNTRY_NAME_TO_CODE[name_key]
            elif len(country) == 2:
                country_code = country.upper()
        country_flag = COUNTRY_FLAGS.get(country_code, flag or "??")
        country_display = f"{escape_mdv2(country)} • {country_flag}" if country and country.lower() not in ["postpaid", "post paid", "other", "unknown", ""] else country_flag

        msg = (
            f"{country_display}\n\n"
            f"📞 `{escape_mdv2(hidden_num)}`\n"
            f"🔐 `{otp}`\n"
            f"💬 Service: {escape_mdv2(app_cap)}\n"
            f"{escape_mdv2('────────────')}\n"
            f"📩"
        )

        if raw_sms:
            quoted_lines = "\n".join(
                f">{escape_mdv2(line)}" for line in raw_sms.splitlines() if line.strip()
            )
            msg += f"\n{quoted_lines}"

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Main Channel", url=CHANNEL_LINK),
        ]])

        await bot.send_message(
            chat_id=OTP_CHANNEL_ID,
            text=msg,
            parse_mode="MarkdownV2",
            reply_markup=keyboard
        )
        logging.info(f"✅ Channel OTP - {app_cap} ({country})")
    except Exception as e:
        logging.error(f"❌ Channel error: {e}")

# =============================================
#         CONSOLE & HELPER FUNCTIONS
# =============================================

_join_cache = {}

async def check_joined(user_id, bot):
    now = time.time()
    cached = _join_cache.get(user_id)
    if cached and (now - cached["time"]) < 600:
        return cached["joined"]
    try:
        member = await bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        joined = member.status in ["member", "administrator", "creator"]
        _join_cache[user_id] = {"joined": joined, "time": now}
        return joined
    except:
        return True

async def get_xmint_console_logs(force=False):
    global _xmint_console_cache
    if not force and _xmint_console_cache["logs"] and (time.time() - _xmint_console_cache["time"]) < 15:
        return _xmint_console_cache["logs"]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            login_res = await client.post(
                f"{XMINT_BASE_URL}/mauth/login",
                json={"email": XMINT_EMAIL, "password": XMINT_PASSWORD}
            )
        login_data = login_res.json()
        if login_data.get("meta", {}).get("code") != 200:
            return _xmint_console_cache["logs"]
        token = login_data["data"].get("token")
        if not token:
            return _xmint_console_cache["logs"]
        headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
            'Accept': "application/json",
            'Content-Type': "application/json",
            'mauthtoken': token,
            'Cookie': f"mautToken={token}"
        }
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{XMINT_BASE_URL}/mdashboard/console/info",
                headers=headers
            )
        if res.status_code != 200 or not res.text.strip():
            return _xmint_console_cache["logs"]
        try:
            data = res.json()
        except Exception:
            return _xmint_console_cache["logs"]
        if data.get("meta", {}).get("code") == 200:
            logs = data["data"].get("logs", [])
            _xmint_console_cache = {"logs": logs, "time": time.time()}
            return logs
        return _xmint_console_cache["logs"]
    except Exception as e:
        logging.error(f"X.Mint Console error: {e}")
        return _xmint_console_cache["logs"]

async def get_countries_for_app(app_name):
    logs = await get_xmint_console_logs()
    seen = set()
    countries = []
    for log in logs:
        log_app = log.get("app_name", "").replace("*", "").strip().upper()
        if log_app == app_name.upper():
            country = log.get("country", "").strip()
            if country and country not in seen:
                seen.add(country)
                countries.append(country)
    return countries

async def get_ranges_for_country(app_name, country):
    logs = await get_xmint_console_logs()
    seen = set()
    ranges = []
    for log in logs:
        log_app = log.get("app_name", "").replace("*", "").strip().upper()
        log_country = log.get("country", "").strip()
        if log_app == app_name.upper() and log_country == country:
            r = log.get("range", "").strip()
            if r and r not in seen:
                seen.add(r)
                ranges.append({"range": r, "time": log.get("time", "")})
    return ranges

# =============================================
#              HELPERS
# =============================================

def init_user(user_id):
    if user_id not in user_data:
        user_data[user_id] = {}
    d = user_data[user_id]
    d.setdefault("app", "FACEBOOK")
    d.setdefault("country", None)
    d.setdefault("range", None)
    d.setdefault("last_number", None)
    d.setdefault("waiting_for", None)
    d.setdefault("joined", datetime.now().strftime("%Y-%m-%d %H:%M"))
    d.setdefault("name", "User")

# =============================================
#              MENUS
# =============================================

def main_keyboard(user_id=None):
    buttons = [
        [KeyboardButton("✧ Start"), KeyboardButton("✧ Custom Range")],
        [KeyboardButton("✧ My Numbers"), KeyboardButton("✧ Bulk Service")],
    ]
    if user_id and user_id == ADMIN_ID:
        buttons.append([KeyboardButton("✧ Admin Panel")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

APP_DISPLAY_NAMES = {
    "FACEBOOK": "Facebook",
}

def app_select_inline():
    buttons = []
    for app in ALL_APPS:
        display = APP_DISPLAY_NAMES.get(app, app.capitalize())
        emoji = APP_EMOJIS.get(app, "🌐")
        buttons.append([InlineKeyboardButton(f"{emoji} {display}", callback_data=f"app_{app}")])
    return InlineKeyboardMarkup(buttons)

def country_select_inline(countries, app_name):
    buttons = []
    for c in countries:
        flag = get_flag(c)
        buttons.append([InlineKeyboardButton(f"{flag} {c}", callback_data=f"country_{c}")])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data="back_app")])
    return InlineKeyboardMarkup(buttons)

def range_select_inline(ranges, app_name, country):
    buttons = []
    for r in ranges[:20]:
        buttons.append([InlineKeyboardButton(f"📡 {r['range']}", callback_data=f"range_{r['range']}")])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data=f"back_country_{app_name}")])
    return InlineKeyboardMarkup(buttons)

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Bulk ON", callback_data="bulk_on"),
         InlineKeyboardButton("📦 Bulk OFF", callback_data="bulk_off")],
        [InlineKeyboardButton("👥 All Users", callback_data="admin_users"),
         InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
    ])

def after_number_inline(number, range_val):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 New Number", callback_data=f"same_{range_val}")],
        [InlineKeyboardButton("📢 Check OTP (Channel)", url="https://t.me/+SWraCXOQrWM4Mzg9")],
        [InlineKeyboardButton("🌍 Change Region", callback_data="change_range")],
    ])

# =============================================
#   USER OTP TASK TRACKER
# =============================================

user_otp_tasks = {}

def add_otp_task(user_id, task):
    if user_id not in user_otp_tasks:
        user_otp_tasks[user_id] = []
    tasks = user_otp_tasks[user_id]
    if len(tasks) >= 2:
        old_task = tasks.pop(0)
        old_task.cancel()
    tasks.append(task)

def cancel_all_otp_tasks(user_id):
    tasks = user_otp_tasks.pop(user_id, [])
    for t in tasks:
        t.cancel()

# =============================================
#         AUTO OTP CHECK
# =============================================

LOADING_TEXTS = [
    "⌛ Checking Inbox...",
    "⌛ Retrieving Code...",
    "⌛ Still checking...",
    "⌛ Verifying...",
    "⌛ Looking for response...",
    "⌛ Please wait...",
]

async def safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
        chat_id = query.message.chat.id
        user_msg[chat_id] = query.message.message_id
    except Exception as e:
        err_msg = str(e).lower()
        if "message is not modified" not in err_msg and "message to edit not found" not in err_msg:
            logging.warning(f"Edit message error: {e}")

async def auto_otp_single(number, user_id, stop_event, otp_callback):
    clean_num = number.replace("+", "").replace(" ", "").strip()
    app = user_data[user_id].get("app", "FACEBOOK")
    seen_otps = set()

    while not stop_event.is_set():
        if not user_data[user_id].get("otp_active", True):
            return
        await asyncio.sleep(5)
        if stop_event.is_set():
            return
        try:
            saved_session = user_data[user_id].get("number_session")
            if not saved_session or not saved_session.get("token"):
                logging.warning(f"⚠️ No saved session for user {user_id}")
                return

            nums = []
            data = await api_get_info_s2(search=clean_num, status="success", saved_session=saved_session)
            if data.get("meta", {}).get("code") == 200:
                nums = data["data"].get("numbers") or []
            if not nums:
                data = await api_get_info_s2(search=clean_num, status="", saved_session=saved_session)
                if data.get("meta", {}).get("code") == 200:
                    nums = [n for n in (data["data"].get("numbers") or []) if n.get("status") == "success"]

            for n in nums:
                api_num = str(n.get("number", "")).replace("+", "").replace(" ", "").strip()
                if clean_num != api_num:
                    continue
                raw_otp = (n.get("otp") or n.get("message") or "").strip()
                otp = extract_otp(raw_otp)
                if otp and otp not in seen_otps:
                    seen_otps.add(otp)
                    found_country = n.get("country", "").strip()
                    if not found_country or found_country.lower() in ["postpaid", "post paid", "other", "unknown"]:
                        found_country = user_data[user_id].get("country", "")
                    found_app = detect_app_from_message(raw_otp, app)
                    await otp_callback(otp, n, raw_otp, found_country, found_app)

        except Exception as e:
            logging.error(f"Auto OTP check error ({number}): {e}")
            await asyncio.sleep(5)

async def auto_otp_multi(message, numbers, user_id, range_val, bot=None):
    if user_data[user_id].get("otp_running"):
        return
    user_data[user_id]["otp_running"] = True
    user_data[user_id]["otp_active"] = True

    app = user_data[user_id].get("app", "FACEBOOK")
    stop_event = asyncio.Event()

    sent_message = None
    base_text = ""
    otp_lines = []

    def build_message(extra=""):
        text = base_text
        for line in otp_lines:
            text += f"\n{line}"
        if extra:
            text += f"\n{extra}"
        return text

    async def on_otp(otp, n, raw_otp, found_country, found_app):
        flag = get_flag(found_country)
        found_num = n.get("number", numbers[0])
        clean_found_num = str(found_num).replace("+", "").strip()

        if bot:
            try:
                await send_otp_to_channel(bot, clean_found_num, otp, found_app, found_country, flag, raw_otp)
            except Exception as e:
                logging.error(f"❌ Channel send error: {e}")

        current_num = str(user_data[user_id].get("last_number", "")).replace("+", "").replace(" ", "").strip()
        if current_num in clean_found_num or clean_found_num in current_num:
            otp_index = len(otp_lines) + 1
            otp_lines.append(f"🔑 OTP {otp_index} : `{otp}`")
            chat_id = message.chat.id
            msg_text = build_message()
            edited = False
            if chat_id in user_msg and bot:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=user_msg[chat_id],
                        text=msg_text,
                        parse_mode="Markdown",
                        reply_markup=after_number_inline(numbers[0], range_val)
                    )
                    edited = True
                except Exception:
                    pass
            if not edited:
                try:
                    await message.reply_text(
                        msg_text,
                        parse_mode="Markdown",
                        reply_markup=after_number_inline(numbers[0], range_val)
                    )
                except Exception as e:
                    logging.error(f"❌ OTP reply error: {e}")

    async def _run():
        nonlocal sent_message, base_text

        number = numbers[0]
        inner_task = asyncio.create_task(auto_otp_single(number, user_id, stop_event, on_otp))

        start_time = asyncio.get_event_loop().time()
        while not stop_event.is_set():
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= 60:
                stop_event.set()
                break
            if sent_message and not otp_lines:
                loading = random.choice(LOADING_TEXTS)
                if sent_message:
                    try:
                        await sent_message.edit_text(
                            build_message(f"\n{loading}"),
                            parse_mode="Markdown",
                            reply_markup=after_number_inline(number, range_val)
                        )
                    except Exception:
                        pass
            await asyncio.sleep(5)

        stop_event.set()
        inner_task.cancel()
        await asyncio.gather(inner_task, return_exceptions=True)

        saved_session = user_data[user_id].get("number_session")
        if saved_session and saved_session.get("token"):
            await xmint_pool.return_number_session(saved_session)
            user_data[user_id]["number_session"] = None

        user_data[user_id]["otp_running"] = False
        user_data[user_id]["otp_active"] = False

    number = numbers[0]
    country_r = user_data[user_id].get("country_r") or user_data[user_id].get("country", "")
    flag = get_flag(country_r)
    clean_number = str(number).replace("+", "").strip()

    base_text = (
        f"✔ Number Ready\n\n"
        f"⟡ Service : {app.capitalize()}\n"
        f"⟡ Number  : `{clean_number}`\n"
        f"⟡ Country : {country_r} {flag}\n"
    )

    chat_id = message.chat.id
    msg_text = build_message("\n⌛ Retrieving Code...")

    try:
        if chat_id in user_msg:
            try:
                sent_message = await message.get_bot().edit_message_text(
                    chat_id=chat_id,
                    message_id=user_msg[chat_id],
                    text=msg_text,
                    parse_mode="Markdown",
                    reply_markup=after_number_inline(number, range_val)
                )
            except Exception:
                sent_message = await message.reply_text(
                    msg_text,
                    parse_mode="Markdown",
                    reply_markup=after_number_inline(number, range_val)
                )
                user_msg[chat_id] = sent_message.message_id
        else:
            sent_message = await message.reply_text(
                msg_text,
                parse_mode="Markdown",
                reply_markup=after_number_inline(number, range_val)
            )
            user_msg[chat_id] = sent_message.message_id
    except Exception as e:
        logging.error(f"❌ Send message error: {e}")
        return

    wrapper = asyncio.create_task(_run())
    add_otp_task(user_id, wrapper)

# =============================================
#         CORE FUNCTIONS
# =============================================

async def do_get_number(message, user_id, count=1, user_name="User", bot=None):
    init_user(user_id)
    range_val = user_data[user_id].get("range")
    app = user_data[user_id].get("app", "FACEBOOK")

    if not range_val:
        await message.reply_text(
            "❌ Range select করা হয়নি!\n\n🏠 Start → Service → Country → Range",
            reply_markup=main_keyboard(user_id)
        )
        return

    if count == 1:
        chat_id = message.chat.id
        try:
            loading_msg = await message.reply_text("⏳ Getting Number...")
            user_msg[chat_id] = loading_msg.message_id
        except Exception:
            pass

        data, number_session = await api_get_number_s2(range_val, app)

        if data.get("meta", {}).get("code") == 200:
            num = data["data"]
            number = num.get("number") or num.get("num") or "N/A"
            country_r = num.get("country", "")
            if not country_r or country_r.lower() in ["postpaid", "post paid", "other", "unknown"]:
                country_r = user_data[user_id].get("country", "")
            user_data[user_id]["last_number"] = number
            user_data[user_id]["auto_otp_cancel"] = False
            user_data[user_id]["country_r"] = country_r
            user_data[user_id]["number_session"] = number_session
            asyncio.create_task(auto_otp_multi(message, [number], user_id, range_val, bot=bot))
        else:
            if number_session:
                await xmint_pool.return_number_session(number_session)
            await message.reply_text("❌ Number পাওয়া যায়নি!", reply_markup=main_keyboard(user_id))
    else:
        await message.reply_text(f"⏳ {count}টি number নেওয়া হচ্ছে...")
        got = 0
        msg = f"📦 BULK GET — Range: {range_val}\n📱 App: {app}\n\n"
        for i in range(count):
            d, sess = await api_get_number_s2(range_val, app)
            if sess:
                await xmint_pool.return_number_session(sess)
            if d.get("meta", {}).get("code") == 200:
                num = d["data"]
                number = num.get("number") or num.get("num") or "N/A"
                country_r = num.get("country", "")
                flag = get_flag(country_r)
                msg += f"{i+1}. {number} {flag} ✅\n"
                user_data[user_id]["last_number"] = number
                got += 1
            else:
                msg += f"{i+1}. ❌ Not found\n"
        msg += f"\n✅ Total received: {got}/{count}"
        await message.reply_text(msg, reply_markup=main_keyboard(user_id))

# =============================================
#         COMMAND HANDLERS
# =============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    init_user(user_id)
    user_data[user_id]["name"] = user.first_name or "User"

    joined = await check_joined(user_id, context.bot)
    if not joined:
        await update.message.reply_text(
            "⚠️ Channel Join করুন!\n\nBot ব্যবহার করতে আমাদের channel join করতে হবে।\n\n👇 নিচের button চাপুন, তারপর /start দিন।",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Channel Join করুন", url=CHANNEL_LINK)
            ]])
        )
        return

    chat_id = update.message.chat.id
    for key_dict in [user_msg, user_range_msg]:
        if chat_id in key_dict:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=key_dict[chat_id])
            except Exception:
                pass
            key_dict.pop(chat_id, None)
    try:
        await update.message.delete()
    except Exception:
        pass

    new_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"⟦  FACEBOOK SERVICE  ⟧\n\n"
            f"Select Your Desired Service\n"
            f"Choose App To Continue"
        ),
        reply_markup=app_select_inline()
    )
    user_msg[chat_id] = new_msg.message_id

async def cmd_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    init_user(user_id)
    await do_get_number(update.message, user_id, count=1, user_name=user.first_name, bot=context.bot)

async def cmd_get100(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    init_user(user_id)
    if not has_get100_access(user_id):
        await update.message.reply_text("❌ আপনার Get 100 access নেই।")
        return
    await do_get_number(update.message, user_id, count=100, user_name=user.first_name, bot=context.bot)

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    init_user(user_id)
    user_data[user_id]["auto_otp_cancel"] = True
    await update.message.reply_text("🛑 Auto OTP check বন্ধ হয়েছে।", reply_markup=main_keyboard(user_id))

async def cmd_mynum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    init_user(user_id)
    await update.message.reply_text("⏳ Loading...")

    last_number = str(user_data[user_id].get("last_number", "")).replace("+", "").strip()
    if not last_number:
        await update.message.reply_text("❌ কোনো number নেওয়া হয়নি।", reply_markup=main_keyboard(user_id))
        return

    _s2_session = await xmint_pool.get_otp_session()
    data = await api_get_info_s2(search=last_number, saved_session=_s2_session)
    await xmint_pool.return_otp_session(_s2_session)

    if data.get("meta", {}).get("code") == 200:
        nums = data["data"].get("numbers", []) or []
        stats = data["data"].get("stats", {})
        msg = (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📋  My Numbers\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"✅  Success: {stats.get('success_count', 0)}\n"
            f"⏳  Pending: {stats.get('pending_count', 0)}\n"
            f"❌  Failed: {stats.get('failed_count', 0)}\n\n"
        )
        for n in nums[:10]:
            e = "✅" if n.get("status") == "success" else "⏳" if n.get("status") == "pending" else "❌"
            msg += f"{e}  {n.get('number')}  —  {n.get('country', '')}  —  {n.get('last_activity', '')}\n"
        msg += "\n━━━━━━━━━━━━━━━━━━"
        await update.message.reply_text(msg, reply_markup=main_keyboard(user_id))
    else:
        await update.message.reply_text("❌ Load করতে ব্যর্থ।", reply_markup=main_keyboard(user_id))

# =============================================
#         ADMIN COMMANDS
# =============================================

async def cmd_allusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    msg = f"👥 Total Users: {len(user_data)}\n\n"
    for uid, uinfo in list(user_data.items())[:20]:
        msg += f"• {uid}  —  {uinfo.get('name','?')}  |  {uinfo.get('app','?')}\n"
    await update.message.reply_text(msg)

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊  BOT STATS\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👥  Users: {len(user_data)}\n"
        f"📦  Bulk: {'✅ ON' if GET100_ENABLED else '❌ OFF'}\n"
        f"👤  Bulk Users: {len(GET100_USERS)}\n"
        f"🔢  Number slots: {xmint_pool.number_sessions.qsize()}/25\n"
        f"🔑  OTP slots: {xmint_pool.otp_sessions.qsize()}/25\n"
        f"🕐  {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

async def cmd_apistatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    session = await xmint_pool._login_once()
    status = "✅ Connected" if session.get("token") else "❌ Failed"
    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔗 API STATUS\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📡 X.Mint: {status}\n"
        f"  🔢 Number slots: {xmint_pool.number_sessions.qsize()}/25\n"
        f"  🔑 OTP slots: {xmint_pool.otp_sessions.qsize()}/25\n\n"
        f"📢 OTP Channel: {OTP_CHANNEL_ID}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    user_data[ADMIN_ID]["waiting_for"] = "broadcast"
    await update.message.reply_text("📢 সবাইকে কী message পাঠাবেন?")

async def cmd_refreshsessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("🔄 Session pool refresh হচ্ছে...")
    await xmint_pool.refresh_all()
    await update.message.reply_text(
        f"✅ Session pool refresh হয়েছে!\n"
        f"Number slots: {xmint_pool.number_sessions.qsize()}/25\n"
        f"OTP slots: {xmint_pool.otp_sessions.qsize()}/25"
    )

async def cmd_get100on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GET100_ENABLED
    if update.effective_user.id != ADMIN_ID:
        return
    GET100_ENABLED = True
    await update.message.reply_text("✅ Get 100 সবার জন্য চালু করা হয়েছে।")

async def cmd_get100off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GET100_ENABLED
    if update.effective_user.id != ADMIN_ID:
        return
    GET100_ENABLED = False
    await update.message.reply_text("❌ Get 100 সবার জন্য বন্ধ করা হয়েছে।")

async def cmd_addget100(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /addget100 <user_id>")
        return
    try:
        uid = int(args[0])
        GET100_USERS.add(uid)
        await update.message.reply_text(f"✅ User {uid} কে Get 100 access দেওয়া হয়েছে।")
    except:
        await update.message.reply_text("❌ Invalid user ID.")

async def cmd_removeget100(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /removeget100 <user_id>")
        return
    try:
        uid = int(args[0])
        GET100_USERS.discard(uid)
        await update.message.reply_text(f"❌ User {uid} এর Get 100 access সরানো হয়েছে।")
    except:
        await update.message.reply_text("❌ Invalid user ID.")

# =============================================
#         CALLBACK HANDLER
# =============================================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GET100_ENABLED
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_name = query.from_user.first_name or "User"
    init_user(user_id)
    user_data[user_id]["name"] = user_name
    data = query.data

    if data == "go_home":
        await query.message.reply_text("📱 Service Select করুন:", reply_markup=app_select_inline())
        return

    if data == "stop_auto":
        user_data[user_id]["auto_otp_cancel"] = True
        await query.answer("🛑 Auto OTP বন্ধ করা হয়েছে!")
        return

    if data.startswith("app_"):
        app_name = data.replace("app_", "")
        user_data[user_id]["app"] = app_name
        user_data[user_id]["country"] = None
        user_data[user_id]["range"] = None
        await safe_edit(query, f"⏳ {app_name} লোড হচ্ছে...")
        countries = await get_countries_for_app(app_name)
        if not countries:
            await safe_edit(query,
                f"❌ {app_name} এ এখন কোনো active country নেই।",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back_app")]])
            )
            return
        emoji = APP_EMOJIS.get(app_name, "📱")
        await safe_edit(query,
            f"{emoji} {app_name}\n\n🌍 Country select করুন:",
            reply_markup=country_select_inline(countries, app_name)
        )

    elif data == "back_app":
        await safe_edit(query, "📱 Service Select করুন:", reply_markup=app_select_inline())

    elif data.startswith("country_"):
        country = data.replace("country_", "")
        app_name = user_data[user_id].get("app", "FACEBOOK")
        user_data[user_id]["country"] = country
        user_data[user_id]["range"] = None
        await safe_edit(query, "⏳ Range লোড হচ্ছে...")
        ranges = await get_ranges_for_country(app_name, country)
        if not ranges:
            await safe_edit(query,
                f"❌ {country} তে কোনো range নেই।",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data=f"back_country_{app_name}")]])
            )
            return
        flag = get_flag(country)
        await safe_edit(query, "👇", reply_markup=range_select_inline(ranges, app_name, country))

    elif data.startswith("back_country_"):
        app_name = data.replace("back_country_", "")
        user_data[user_id]["country"] = None
        await safe_edit(query, "⏳ Loading...")
        countries = await get_countries_for_app(app_name)
        emoji = APP_EMOJIS.get(app_name, "📱")
        await safe_edit(query,
            f"{emoji} {app_name}\n\n🌍 Country select করুন:",
            reply_markup=country_select_inline(countries, app_name)
        )

    elif data.startswith("range_"):
        range_val = data.replace("range_", "")
        app_name = user_data[user_id].get("app", "FACEBOOK")
        country = user_data[user_id].get("country", "")
        user_data[user_id]["range"] = range_val
        user_data[user_id]["auto_otp_cancel"] = False

        cancel_all_otp_tasks(user_id)
        user_data[user_id]["otp_active"] = False
        user_data[user_id]["otp_running"] = False

        loading_msg = await query.message.reply_text("⏳ Getting Number...")
        user_msg[query.message.chat.id] = loading_msg.message_id

        data_r, number_session = await api_get_number_s2(range_val, app_name)

        if data_r.get("meta", {}).get("code") == 200:
            num = data_r["data"]
            number = num.get("number") or num.get("num") or "N/A"
            country_r = num.get("country", country)
            if not country_r or country_r.lower() in ["postpaid", "post paid", "other", "unknown"]:
                country_r = user_data[user_id].get("country", "")
            user_data[user_id]["last_number"] = number
            user_data[user_id]["country_r"] = country_r
            user_data[user_id]["number_session"] = number_session
            asyncio.create_task(auto_otp_multi(query.message, [number], user_id, range_val, bot=context.bot))
        else:
            if number_session:
                await xmint_pool.return_number_session(number_session)
            await safe_edit(query,
                "❌ Number পাওয়া যায়নি!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Try Again", callback_data=f"range_{range_val}")],
                    [InlineKeyboardButton("◀️ Back", callback_data="back_app")]
                ])
            )

    elif data.startswith("same_"):
        range_val = data.replace("same_", "")
        app_name = user_data[user_id].get("app", "FACEBOOK")
        country = user_data[user_id].get("country", "")
        user_data[user_id]["range"] = range_val

        cancel_all_otp_tasks(user_id)
        user_data[user_id]["otp_active"] = False
        user_data[user_id]["otp_running"] = False

        chat_id = query.message.chat.id
        try:
            await query.message.delete()
        except Exception:
            pass
        if chat_id in user_msg:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=user_msg[chat_id])
            except Exception:
                pass
            user_msg.pop(chat_id, None)

        try:
            loading_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Getting Number...")
            user_msg[chat_id] = loading_msg.message_id
        except Exception:
            pass

        data_r, number_session = await api_get_number_s2(range_val, app_name)

        if data_r.get("meta", {}).get("code") == 200:
            num = data_r["data"]
            number = num.get("number") or num.get("num") or "N/A"
            country_r = num.get("country", country)
            if not country_r or country_r.lower() in ["postpaid", "post paid", "other", "unknown"]:
                country_r = user_data[user_id].get("country", "")
            user_data[user_id]["last_number"] = number
            user_data[user_id]["country_r"] = country_r
            user_data[user_id]["number_session"] = number_session
            asyncio.create_task(auto_otp_multi(query.message, [number], user_id, range_val, bot=context.bot))
        else:
            if number_session:
                await xmint_pool.return_number_session(number_session)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=user_msg.get(chat_id),
                    text="❌ Number পাওয়া যায়নি!"
                )
            except Exception:
                await query.message.reply_text("❌ Number পাওয়া যায়নি!", reply_markup=main_keyboard(user_id))

    elif data == "change_range":
        user_data[user_id]["auto_otp_cancel"] = True
        user_data[user_id]["range"] = None
        user_data[user_id]["country"] = None
        await asyncio.sleep(0.1)
        user_data[user_id]["auto_otp_cancel"] = False

        chat_id = query.message.chat.id
        try:
            await query.message.delete()
        except Exception:
            pass
        for key_dict in [user_msg, user_range_msg]:
            if chat_id in key_dict:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=key_dict[chat_id])
                except Exception:
                    pass
                key_dict.pop(chat_id, None)

        new_msg = await context.bot.send_message(
            chat_id=chat_id,
            text="📱 Service select করুন:",
            reply_markup=app_select_inline()
        )
        user_msg[chat_id] = new_msg.message_id

    elif data == "bulk_on":
        if user_id == ADMIN_ID:
            GET100_ENABLED = True
            await query.answer("✅ Bulk চালু হয়েছে!")
            await query.edit_message_reply_markup(reply_markup=admin_keyboard())
        return

    elif data == "bulk_off":
        if user_id == ADMIN_ID:
            GET100_ENABLED = False
            await query.answer("❌ Bulk বন্ধ হয়েছে!")
            await query.edit_message_reply_markup(reply_markup=admin_keyboard())
        return

    elif data == "admin_users":
        if user_id == ADMIN_ID:
            msg = f"👥 Total Users: {len(user_data)}\n\n"
            for uid, uinfo in list(user_data.items())[:15]:
                msg += f"• {uid}  —  {uinfo.get('name','?')}\n"
            await query.message.reply_text(msg)
        return

    elif data == "admin_stats":
        if user_id == ADMIN_ID:
            await query.message.reply_text(
                f"📊 BOT STATS\n\n"
                f"👥 Users: {len(user_data)}\n"
                f"📦 Bulk: {'✅ ON' if GET100_ENABLED else '❌ OFF'}\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )
        return

    elif data == "cancel":
        await query.message.reply_text("❌ বাতিল করা হয়েছে।", reply_markup=main_keyboard(user_id))

# =============================================
#         MESSAGE HANDLER
# =============================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user
    user_id = user.id
    user_name = user.first_name or "User"
    init_user(user_id)
    user_data[user_id]["name"] = user_name
    waiting = user_data[user_id].get("waiting_for")

    joined = await check_joined(user_id, context.bot)
    if not joined:
        await update.message.reply_text(
            "⚠️ Channel Join করুন!\n\nJoin করে /start দিন।",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Channel Join করুন", url=CHANNEL_LINK)
            ]])
        )
        return

    if text in ("✧ Start", "🏠 Start", "/start"):
        await start(update, context)
        return

    if text in ("✧ Custom Range", "🎯 Custom Range"):
        user_data[user_id]["waiting_for"] = "custom_range"
        await update.message.reply_text("📡 Range লিখুন:\n\nউদাহরণ: 23762155XXX", reply_markup=main_keyboard(user_id))
        return

    if user_data[user_id].get("waiting_for") == "custom_range":
        user_data[user_id]["waiting_for"] = None
        user_data[user_id]["range"] = text
        await do_get_number(update.message, user_id, count=1, user_name=user_name, bot=context.bot)
        return

    if text in ("✧ My Numbers", "📋 My Numbers"):
        await cmd_mynum(update, context)
        return

    if text in ("✧ Bulk Service", "📦 Bulk Number", "✧ Bulk Number"):
        if not has_get100_access(user_id):
            await update.message.reply_text("❌ Bulk Number এখন বন্ধ আছে।\n\nAdmin চালু করলে use করতে পারবেন।")
        else:
            await do_get_number(update.message, user_id, count=100, user_name=user_name, bot=context.bot)
        return

    if text in ("✧ Admin Panel", "👑 Admin Panel"):
        if user_id == ADMIN_ID:
            get100_status = "✅ ON" if GET100_ENABLED else "❌ OFF"
            await update.message.reply_text(
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👑  ADMIN PANEL\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"📋  /allusers — সব users\n"
                f"📊  /stats — Bot stats\n"
                f"🔑  /apistatus — API status\n"
                f"📢  /broadcast — সবাইকে message\n"
                f"🔄  /refreshsessions — Session refresh\n\n"
                f"📦  Bulk Number: {get100_status}\n"
                f"/get100on — সবার জন্য চালু\n"
                f"/get100off — সবার জন্য বন্ধ\n"
                f"/addget100 <id> — নির্দিষ্ট user চালু\n"
                f"/removeget100 <id> — নির্দিষ্ট user বন্ধ\n\n"
                f"━━━━━━━━━━━━━━━━━━",
                reply_markup=admin_keyboard()
            )
        else:
            await update.message.reply_text("❌ Admin access নেই।")
        return

    if user_id == ADMIN_ID and waiting == "broadcast":
        user_data[user_id]["waiting_for"] = None
        sent = 0
        failed = 0
        for uid in user_data:
            try:
                await context.bot.send_message(uid, f"📢 Admin Message:\n\n{text}")
                sent += 1
            except Exception as e:
                logging.warning(f"⚠️ Broadcast fail - User {uid}: {e}")
                failed += 1
        await update.message.reply_text(
            f"✅ {sent} জন কে পাঠানো হয়েছে।\n"
            f"❌ {failed} জন কে পাঠানো যায়নি।"
        )
        return

# =============================================
#              MAIN
# =============================================

async def post_init(application):
    try:
        asyncio.create_task(xmint_pool.initialize())
        logging.info("✅ Session pool background init started")
    except Exception as e:
        logging.error(f"⚠️ Pool init error: {e}")
    logging.info("✅ Facebook Service Bot started!")

async def post_shutdown(application):
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    logging.info("✅ All tasks cancelled cleanly.")

async def error_handler(update, context):
    error_msg = str(context.error).lower()
    if "message is not modified" in error_msg or "bad request" in error_msg or "message to edit not found" in error_msg:
        return
    logging.error(f"Exception while handling an update: {context.error}")

if __name__ == "__main__":
    app = (ApplicationBuilder()
           .token(BOT_TOKEN)
           .read_timeout(30)
           .write_timeout(30)
           .connect_timeout(30)
           .post_init(post_init)
           .post_shutdown(post_shutdown)
           .concurrent_updates(False)
           .build())

    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("get", cmd_get))
    app.add_handler(CommandHandler("get100", cmd_get100))
    app.add_handler(CommandHandler("mynum", cmd_mynum))
    app.add_handler(CommandHandler("allusers", cmd_allusers))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("apistatus", cmd_apistatus))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("get100on", cmd_get100on))
    app.add_handler(CommandHandler("get100off", cmd_get100off))
    app.add_handler(CommandHandler("addget100", cmd_addget100))
    app.add_handler(CommandHandler("removeget100", cmd_removeget100))
    app.add_handler(CommandHandler("refreshsessions", cmd_refreshsessions))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Facebook Service Bot is running...")
    app.run_polling(drop_pending_updates=True, timeout=30)
