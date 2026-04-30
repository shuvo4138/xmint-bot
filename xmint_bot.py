import logging
import asyncio
import re
import random
import time
import httpx
import os
import json as _json
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# =============================================
#              CONFIG (Environment Variables)
# =============================================
BOT_TOKEN = os.environ["BOT_TOKEN"]

# STEXSMS (S1)
STEXSMS_EMAIL = os.environ["STEXSMS_EMAIL"]
STEXSMS_PASSWORD = os.environ["STEXSMS_PASSWORD"]
BASE_URL = "https://stexsms.com/mapi/v1"

# X.MINT (S2)
XMINT_EMAIL = os.environ["XMINT_EMAIL"]
XMINT_PASSWORD = os.environ["XMINT_PASSWORD"]
XMINT_BASE_URL = "https://x.mnitnetwork.com/mapi/v1"

ADMIN_ID = int(os.environ["ADMIN_ID"])
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@alwaysrvice24hours")
CHANNEL_LINK = os.environ.get("CHANNEL_LINK", "https://t.me/alwaysrvice24hours")

# ✅ Join Verify — 2nd Channel
CHANNEL2_USERNAME = os.environ.get("CHANNEL2_USERNAME", "@Foggred")
CHANNEL2_LINK = os.environ.get("CHANNEL2_LINK", "https://t.me/Foggred")
CHANNEL2_NAME = os.environ.get("CHANNEL2_NAME", "Backup Channel")

OTP_CHANNEL_ID = int(os.environ["OTP_CHANNEL_ID"])

# Range post channel — same as OTP channel or different
RANGE_CHANNEL_ID = int(os.environ.get("RANGE_CHANNEL_ID", os.environ["OTP_CHANNEL_ID"]))

# ✅ DB channel বাদ দেওয়া হয়েছে

GET100_ENABLED = False
GET100_USERS = set()

SUPPORT_ADMIN_LINK = "https://t.me/NPO_Admin_support"

logging.basicConfig(level=logging.INFO)

user_data = {}
user_locks = {}
user_msg = {}
user_range_msg = {}
user_kb_msg = {}

# =============================================
#         EXISTING USERS (Hardcoded)
# =============================================
_EXISTING_USERS = [
    {"user_id": 1984916365, "name": "SHUVO"},
    {"user_id": 2056354289, "name": "Joy"},
    {"user_id": 7273612043, "name": "Md Tufan"},
    {"user_id": 7198345317, "name": "Shafi"},
    {"user_id": 8249336650, "name": "Mohazer"},
    {"user_id": 7003821995, "name": "Md Ebrahim"},
    {"user_id": 8589394826, "name": "My OLX"},
    {"user_id": 7528489859, "name": "Kylie"},
    {"user_id": 7308940812, "name": "Bhatparaja"},
    {"user_id": 6249183895, "name": "Err"},
    {"user_id": 7969629049, "name": "MD."},
    {"user_id": 7473150688, "name": "Emon Hosssin"},
    {"user_id": 8008653873, "name": "Faysal Ahmed"},
    {"user_id": 7259491851, "name": "Asif"},
    {"user_id": 8765450043, "name": "Facebook"},
]

def _load_existing_users():
    for u in _EXISTING_USERS:
        uid = u["user_id"]
        if uid not in user_data:
            user_data[uid] = {}
        user_data[uid].setdefault("name", u["name"])
        user_data[uid].setdefault("joined", "2026-03-28 00:00")
        user_data[uid].setdefault("app", "FACEBOOK")
        user_data[uid].setdefault("panel", "S1")
        user_data[uid].setdefault("country", None)
        user_data[uid].setdefault("range", None)
        user_data[uid].setdefault("last_number", None)
        user_data[uid].setdefault("waiting_for", None)

_load_existing_users()

# Console cache — 5 মিনিট
_console_cache = {"logs": [], "time": 0}
_xmint_console_cache = {"logs": [], "time": 0}
CONSOLE_CACHE_TTL = 300  # 5 minutes

# OTP Counter — memory তে, রাত 12টায় reset
_otp_counter = {}
_otp_counter_date = ""

def _get_otp_counter():
    global _otp_counter, _otp_counter_date
    from datetime import timezone, timedelta
    bd_today = datetime.now(timezone(timedelta(hours=6))).strftime("%Y-%m-%d")
    if _otp_counter_date != bd_today:
        _otp_counter = {}
        _otp_counter_date = bd_today
    return _otp_counter

def increment_otp_counter(app_name, country=""):
    counter = _get_otp_counter()
    app = app_name.upper()
    if app not in counter:
        counter[app] = {"total": 0, "countries": {}}
    counter[app]["total"] += 1
    if country:
        counter[app]["countries"][country] = counter[app]["countries"].get(country, 0) + 1

# =============================================
#         APP EMOJIS
# =============================================
APP_EMOJIS = {
    "FACEBOOK": "📘", "INSTAGRAM": "📸", "TIKTOK": "🎵",
    "SNAPCHAT": "👻", "TWITTER": "🐦", "GOOGLE": "🔍",
    "WHATSAPP": "💬", "TELEGRAM": "✈️", "CHATGPT": "🤖",
    "SHEIN": "👗", "TWILIO": "📞", "TWVERIFY": "✅",
    "VERIFY": "🔐", "VERIMSG": "💌", "VGSMS": "📡",
    "WORLDFIRST": "🌏", "GOFUNDME": "💰",
    "INFO": "ℹ️", "KLARNA": "💳", "VSHOW": "📺", "VERCEL": "🔗",
    "AUTHMSG": "📨",
}

# =============================================
#         SESSION POOL SYSTEM (S1)
# =============================================

SESSION_POOL_SIZE = 100
NUMBER_GET_SLOTS = 50
OTP_CHECK_SLOTS = 50

class SessionPool:
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
            results = []
            for i in range(SESSION_POOL_SIZE):
                r = await self._login_once()
                results.append(r)
                await asyncio.sleep(1)
            number_count = 0
            otp_count = 0
            for r in results:
                if isinstance(r, dict) and r.get("token"):
                    self.all_sessions.append(r)
                    if number_count < NUMBER_GET_SLOTS:
                        await self.number_sessions.put(r)
                        number_count += 1
                    elif otp_count < OTP_CHECK_SLOTS:
                        await self.otp_sessions.put(r)
                        otp_count += 1
            self.initialized = True
            logging.warning(f"✅ S1 Session pool ready! Number: {number_count}, OTP: {otp_count}")

    async def _login_once(self):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.post(
                    f"{BASE_URL}/mauth/login",
                    json={"email": STEXSMS_EMAIL, "password": STEXSMS_PASSWORD}
                )
            if res.status_code == 403:
                return {}
            if res.status_code != 200:
                return {}
            try:
                data = res.json()
            except Exception:
                return {}
            if data.get("meta", {}).get("code") == 200:
                token = data["data"].get("token")
                session_token = data["data"].get("session_token")
                if token:
                    return {"token": token, "session": session_token, "time": time.time()}
        except Exception as e:
            logging.error(f"S1 Login error: {e}")
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

session_pool = SessionPool()

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
            results = []
            for i in range(40):
                r = await self._login_once()
                results.append(r)
                await asyncio.sleep(1)
            number_count = 0
            otp_count = 0
            for r in results:
                if isinstance(r, dict) and r.get("token"):
                    self.all_sessions.append(r)
                    if number_count < 25:
                        await self.number_sessions.put(r)
                        number_count += 1
                    elif otp_count < 15:
                        await self.otp_sessions.put(r)
                        otp_count += 1
            self.initialized = True
            logging.warning(f"✅ S2 (X.Mint) Session pool ready! Number: {number_count}, OTP: {otp_count}")

    async def _login_once(self):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.post(
                    f"{XMINT_BASE_URL}/mauth/login",
                    json={"email": XMINT_EMAIL, "password": XMINT_PASSWORD}
                )
            if res.status_code == 403:
                return {}
            if res.status_code != 200:
                return {}
            try:
                data = res.json()
            except Exception:
                return {}
            if data.get("meta", {}).get("code") == 200:
                token = data["data"].get("token")
                if token:
                    return {"token": token, "session": "", "time": time.time()}
        except Exception as e:
            logging.error(f"X.Mint Login error: {e}")
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
#         X.MINT API FUNCTIONS (S2)
# =============================================

async def api_get_number_s2(range_val, app_name="FACEBOOK", _retry=0):
    clean_range = ''.join(c for c in range_val.upper() if c.isdigit() or c == 'X')
    if not clean_range:
        return {"error": "Invalid range"}, None
    base = clean_range.rstrip('X')
    clean_range = base + 'XXX'

    session = await xmint_pool.get_number_session()
    try:
        token = session.get("token")
        if not token:
            return {"error": "No session available"}, None

        payload = {
            "range": clean_range,
            "isNational": False,
            "isRemovePlus": True,
            "app": app_name
        }
        headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10)",
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
            new_session = await xmint_pool._login_once()
            if new_session.get("token") and _retry < 2:
                await asyncio.sleep(1)
                return await api_get_number_s2(range_val, app_name, _retry=_retry + 1)
            return {"error": "session_expired"}, None

        if res.status_code in (429, 503):
            wait_time = 10 * (2 ** _retry)
            await xmint_pool.return_number_session(session)
            if _retry < 3:
                await asyncio.sleep(wait_time)
                return await api_get_number_s2(range_val, app_name, _retry=_retry + 1)
            return {"error": f"HTTP {res.status_code}"}, None

        if res.status_code != 200:
            await xmint_pool.return_number_session(session)
            return {"error": f"HTTP {res.status_code}"}, None

        try:
            result = res.json()
        except Exception as e:
            await xmint_pool.return_number_session(session)
            return {"error": "Invalid JSON"}, None

        if result.get("meta", {}).get("code") != 200:
            msg = str(result.get("message", "")).lower()
            if any(k in msg for k in ["block", "rate", "limit", "many", "temporary"]):
                await xmint_pool.return_number_session(session)
                if _retry < 3:
                    wait_time = 10 * (2 ** _retry)
                    await asyncio.sleep(wait_time)
                    return await api_get_number_s2(range_val, app_name, _retry=_retry + 1)
                return result, None

        return result, session
    except Exception as e:
        logging.error(f"api_get_number_s2 error: {e}")
        if session and session.get("token"):
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

# =============================================
#         COUNTRY FLAGS
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
}

COUNTRY_NAME_TO_CODE = {
    "cameroon": "CM", "vietnam": "VN", "pakistan": "PK", "tanzania": "TZ",
    "tajikistan": "TJ", "togo": "TG", "nigeria": "NG", "ghana": "GH",
    "kenya": "KE", "bangladesh": "BD", "india": "IN", "philippines": "PH",
    "indonesia": "ID", "myanmar": "MM", "cambodia": "KH", "ethiopia": "ET",
    "congo": "CD", "dr congo": "CD", "democratic republic of congo": "CD",
    "drc": "CD", "mozambique": "MZ", "madagascar": "MG",
    "ivory coast": "CI", "cote d'ivoire": "CI", "côte d'ivoire": "CI", "senegal": "SN", "mali": "ML", "burkina faso": "BF",
    "guinea": "GN", "guinea republic": "GN", "zambia": "ZM", "zimbabwe": "ZW",
    "rwanda": "RW", "uganda": "UG", "angola": "AO", "sudan": "SD",
    "mauritania": "MR", "niger": "NE", "chad": "TD", "somalia": "SO",
    "burundi": "BI", "benin": "BJ", "malawi": "MW", "sierra leone": "SL",
    "liberia": "LR", "car": "CF", "central african republic": "CF",
    "central african": "CF", "gabon": "GA", "djibouti": "DJ",
    "equatorial guinea": "GQ", "sao tome": "ST", "sao tome and principe": "ST",
    "republic of the congo": "CG", "congo republic": "CG", "brazzaville": "CG",
    "eritrea": "ER", "gambia": "GM", "cape verde": "CV", "comoros": "KM",
    "seychelles": "SC", "mauritius": "MU", "south africa": "ZA",
    "namibia": "NA", "botswana": "BW", "lesotho": "LS", "eswatini": "SZ",
    "egypt": "EG", "libya": "LY", "tunisia": "TN", "algeria": "DZ",
    "morocco": "MA", "mexico": "MX", "brazil": "BR", "colombia": "CO",
    "peru": "PE", "venezuela": "VE", "argentina": "AR", "chile": "CL",
    "ecuador": "EC", "bolivia": "BO", "paraguay": "PY", "uruguay": "UY",
    "guyana": "GY", "suriname": "SR", "guatemala": "GT", "honduras": "HN",
    "el salvador": "SV", "nicaragua": "NI", "costa rica": "CR",
    "panama": "PA", "cuba": "CU", "haiti": "HT", "usa": "US",
    "united states": "US", "canada": "CA", "thailand": "TH", "laos": "LA",
    "malaysia": "MY", "singapore": "SG", "nepal": "NP", "sri lanka": "LK",
    "afghanistan": "AF", "iran": "IR", "iraq": "IQ", "syria": "SY",
    "yemen": "YE", "saudi arabia": "SA", "uae": "AE", "qatar": "QA",
    "kuwait": "KW", "bahrain": "BH", "oman": "OM", "jordan": "JO",
    "lebanon": "LB", "palestine": "PS", "armenia": "AM", "azerbaijan": "AZ",
    "georgia": "GE", "kazakhstan": "KZ", "uzbekistan": "UZ",
    "turkmenistan": "TM", "kyrgyzstan": "KG", "mongolia": "MN",
    "russia": "RU", "ukraine": "UA", "belarus": "BY", "moldova": "MD",
    "romania": "RO", "bulgaria": "BG", "serbia": "RS", "croatia": "HR",
    "bosnia": "BA", "north macedonia": "MK", "albania": "AL",
    "montenegro": "ME", "slovenia": "SI", "slovakia": "SK",
    "czech republic": "CZ", "poland": "PL", "hungary": "HU",
    "austria": "AT", "switzerland": "CH", "germany": "DE", "france": "FR",
    "spain": "ES", "italy": "IT", "portugal": "PT", "uk": "GB",
    "ireland": "IE", "netherlands": "NL", "belgium": "BE",
    "luxembourg": "LU", "denmark": "DK", "sweden": "SE",
    "norway": "NO", "finland": "FI", "iceland": "IS",
    "australia": "AU", "new zealand": "NZ", "japan": "JP",
    "south korea": "KR", "china": "CN", "taiwan": "TW", "hong kong": "HK",
    "postpaid": "PP", "post paid": "PP",
}

def get_flag(code):
    if not code:
        return "🌍"
    name_key = code.lower().strip()
    if name_key in ("postpaid", "post paid", "pp"):
        return "📱"
    if name_key in COUNTRY_NAME_TO_CODE:
        return COUNTRY_FLAGS.get(COUNTRY_NAME_TO_CODE[name_key], "🌍")
    short = code.upper().strip()[:2]
    if short in COUNTRY_FLAGS:
        return COUNTRY_FLAGS.get(short, "🌍")
    words = name_key.split()
    for word in words:
        if word in COUNTRY_NAME_TO_CODE:
            return COUNTRY_FLAGS.get(COUNTRY_NAME_TO_CODE[word], "🌍")
    return "🌍"

def get_country_code(country):
    if not country:
        return ""
    name_key = country.lower().strip()
    if name_key in ("postpaid", "post paid"):
        return "PP"
    if name_key in COUNTRY_NAME_TO_CODE:
        return COUNTRY_NAME_TO_CODE[name_key]
    if len(country) == 2 and country.upper() in COUNTRY_FLAGS:
        return country.upper()
    return ""

def extract_otp(message):
    """4 digit OTP = fake, skip করো। শুধু 5, 6, 8 digit accept।
    Space-separated OTP ও handle করে: 145 692 → 145692"""
    if not message:
        return None
    # Direct match:붙어있는 8, 6, 5 digit (000000 skip)
    match = re.search(r'\b(\d{8}|\d{6}|\d{5})\b', message)
    if match:
        otp = match.group(1)
        if re.fullmatch(r'0+', otp):
            pass  # all-zero হলে space-separated try করো
        else:
            return otp
    # Space-separated OTP: "145 692" → "145692"
    spaced = re.search(r'\b(\d{3} \d{3})\b', message)
    if spaced:
        candidate = spaced.group(1).replace(" ", "")
        if not re.fullmatch(r'0+', candidate):
            return candidate
    spaced2 = re.search(r'\b(\d{2} \d{3})\b', message)
    if spaced2:
        candidate = spaced2.group(1).replace(" ", "")
        if not re.fullmatch(r'0+', candidate):
            return candidate
    # সব চেষ্টা ব্যর্থ হলে all-zero টাই return করো (caller handle করবে)
    if match:
        return match.group(1)
    return None

def detect_app_from_message(message, default_app=""):
    if not message:
        return default_app
    msg_lower = message.lower()
    if "facebook" in msg_lower:
        return "FACEBOOK"
    elif "whatsapp" in msg_lower:
        return "WHATSAPP"
    elif "telegram" in msg_lower:
        return "TELEGRAM"
    elif "instagram" in msg_lower:
        return "INSTAGRAM"
    elif "google" in msg_lower:
        return "GOOGLE"
    elif "twitter" in msg_lower:
        return "TWITTER"
    elif "tiktok" in msg_lower:
        return "TIKTOK"
    elif "snapchat" in msg_lower:
        return "SNAPCHAT"
    return default_app

def has_get100_access(user_id):
    return GET100_ENABLED or user_id in GET100_USERS or user_id == ADMIN_ID

# =============================================
#         OTP CHANNEL FORWARD
# =============================================

def escape_mdv2(text):
    special = r'\_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{c}' if c in special else c for c in str(text))

async def safe_send_message(bot, chat_id, text, **kwargs):
    while True:
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
        except Exception as e:
            err = str(e).lower()
            if "retry after" in err or "flood" in err:
                import re as _re
                wait = int(_re.search(r'\d+', str(e)).group() or 5)
                await asyncio.sleep(wait + 1)
            else:
                raise

async def safe_edit_message(bot, chat_id, message_id, text, **kwargs):
    while True:
        try:
            return await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=text, **kwargs
            )
        except Exception as e:
            err = str(e).lower()
            if "retry after" in err or "flood" in err:
                import re as _re
                wait = int(_re.search(r'\d+', str(e)).group() or 5)
                await asyncio.sleep(wait + 1)
            else:
                raise

async def send_otp_to_channel(bot, number, otp, app, country, flag, raw_sms="", panel="S1"):
    try:
        # OTP counter increment
        increment_otp_counter(app, country)

        app_cap = app.capitalize()
        clean_num = str(number).replace("+", "").strip()
        if len(clean_num) > 8:
            hidden_num = "+" + clean_num[:5] + "xxxx" + clean_num[-3:]
        else:
            hidden_num = clean_num

        country_code = get_country_code(country)
        country_flag = COUNTRY_FLAGS.get(country_code, flag or "🌐")
        country_display = f"{escape_mdv2(country)} • {country_flag}" if country and country.lower() not in ["postpaid", "post paid", "other", "unknown", ""] else country_flag

        msg = (
            f"{country_display}\n\n"
            f"📞 `{escape_mdv2(hidden_num)}`\n"
            f"🔐 `{otp}`\n"
            f"💬 Service: {escape_mdv2(app_cap)} [{escape_mdv2(panel)}]\n"
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
            InlineKeyboardButton("🤖 Number Bot", url="https://t.me/Fb_KiNG_Seviceotp_bot"),
        ]])

        try:
            await safe_send_message(bot, chat_id=OTP_CHANNEL_ID, text=msg,
                                    parse_mode="MarkdownV2", reply_markup=keyboard)
        except Exception:
            plain_msg = (
                f"{country} {flag}\n\n"
                f"📞 {hidden_num}\n"
                f"🔐 {otp}\n"
                f"💬 Service: {app_cap} [{panel}]\n"
                f"────────────\n📩"
            )
            if raw_sms:
                plain_msg += f"\n{raw_sms[:200]}"
            await safe_send_message(bot, chat_id=OTP_CHANNEL_ID, text=plain_msg, reply_markup=keyboard)

    except Exception as e:
        logging.error(f"Channel error: {e}")

# =============================================
#         API FUNCTIONS (S1)
# =============================================

async def get_token():
    session = await session_pool.get_otp_session()
    await session_pool.return_otp_session(session)
    return session.get("token"), session.get("session")

async def fresh_login():
    session = await session_pool._login_once()
    return session.get("token"), session.get("session")

_join_cache = {}

async def check_joined(user_id, bot):
    """Single channel check (backward compat)"""
    now = time.time()
    cached = _join_cache.get(user_id)
    if cached and (now - cached["time"]) < 600:
        return cached["joined"]
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        joined = member.status in ["member", "administrator", "creator"]
        _join_cache[user_id] = {"joined": joined, "time": now}
        return joined
    except:
        return True

async def check_all_channels_joined(user_id, bot):
    """
    দুইটা channel join করেছে কিনা check করো।
    Returns: (ch1_joined: bool, ch2_joined: bool)
    """
    cache_key1 = f"{user_id}_ch1"
    cache_key2 = f"{user_id}_ch2"
    now = time.time()

    # Channel 1
    c1 = _join_cache.get(cache_key1)
    if c1 and (now - c1["time"]) < 300:
        ch1_joined = c1["joined"]
    else:
        try:
            m = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
            ch1_joined = m.status in ["member", "administrator", "creator"]
            _join_cache[cache_key1] = {"joined": ch1_joined, "time": now}
        except:
            ch1_joined = True

    # Channel 2
    c2 = _join_cache.get(cache_key2)
    if c2 and (now - c2["time"]) < 300:
        ch2_joined = c2["joined"]
    else:
        try:
            m = await bot.get_chat_member(CHANNEL2_USERNAME, user_id)
            ch2_joined = m.status in ["member", "administrator", "creator"]
            _join_cache[cache_key2] = {"joined": ch2_joined, "time": now}
        except:
            ch2_joined = True

    return ch1_joined, ch2_joined

def clear_join_cache(user_id):
    """Verify button চাপলে cache clear করো"""
    _join_cache.pop(f"{user_id}_ch1", None)
    _join_cache.pop(f"{user_id}_ch2", None)
    _join_cache.pop(user_id, None)

def get_headers(token, session):
    return {
        'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
        'Accept': "application/json, text/plain, */*",
        'Content-Type': "application/json",
        'mauthtoken': token,
        'Cookie': f"mauthtoken={token}; session_token={session}"
    }

async def get_console_logs(force=False):
    global _console_cache
    if not force and _console_cache["logs"] and (time.time() - _console_cache["time"]) < CONSOLE_CACHE_TTL:
        return _console_cache["logs"]
    try:
        token, session = await get_token()
        if not token:
            return []
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{BASE_URL}/mdashboard/console/info",
                headers=get_headers(token, session)
            )
        data = res.json()
        if data.get("meta", {}).get("code") == 200:
            logs = data["data"].get("logs", [])
            _console_cache = {"logs": logs, "time": time.time()}
            return logs
        return _console_cache["logs"]
    except Exception as e:
        logging.error(f"Console error: {e}")
        return _console_cache["logs"]

async def get_xmint_token():
    session = await xmint_pool.get_otp_session()
    await xmint_pool.return_otp_session(session)
    return session.get("token")

async def get_xmint_console_logs(force=False):
    global _xmint_console_cache
    if not force and _xmint_console_cache["logs"] and (time.time() - _xmint_console_cache["time"]) < CONSOLE_CACHE_TTL:
        return _xmint_console_cache["logs"]
    try:
        session = await xmint_pool.get_otp_session()
        token = session.get("token") if session else None
        await xmint_pool.return_otp_session(session)
        if not token:
            session = await xmint_pool._login_once()
            token = session.get("token")
        if not token:
            return _xmint_console_cache["logs"]
        headers = {
            'User-Agent': "Mozilla/5.0 (Linux; Android 10)",
            'Accept': "application/json",
            'Content-Type': "application/json",
            'mauthtoken': token,
            'Cookie': f"mautToken={token}"
        }
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(f"{XMINT_BASE_URL}/mdashboard/console/info", headers=headers)
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

# =============================================
#   CONSOLE DATA HELPERS (Carrier removed)
# =============================================

async def get_countries_for_app(app_name, panel="S1"):
    """Console থেকে app এর available countries আনো"""
    logs = await get_xmint_console_logs() if panel == "S2" else await get_console_logs()
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

async def get_all_ranges_for_country(app_name, country, panel="S1"):
    """
    Carrier step removed — country select করলেই সব ranges আসবে
    S1 + S2 উভয়ের জন্য কাজ করে
    """
    logs = await get_xmint_console_logs() if panel == "S2" else await get_console_logs()
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

async def get_live_traffic_data():
    """
    🚦 Live Traffic — S1 + S2 আলাদা
    Returns: {app_name: {total: N, s1: N, s2: N, countries: {country: count}}}
    """
    s1_logs = await get_console_logs(force=True)
    s2_logs = await get_xmint_console_logs(force=True)

    result = {}

    for panel_label, logs in [("S1", s1_logs), ("S2", s2_logs)]:
        for log in logs:
            app = log.get("app_name", "").replace("*", "").strip().upper()
            country = log.get("country", "").strip()
            if not app:
                continue
            if app not in result:
                result[app] = {"total": 0, "s1": 0, "s2": 0, "countries": {}}
            result[app]["total"] += 1
            result[app][panel_label.lower()] += 1
            if country:
                result[app]["countries"][country] = result[app]["countries"].get(country, 0) + 1

    result = dict(sorted(result.items(), key=lambda x: x[1]["total"], reverse=True))
    return result

async def get_all_ranges_by_country_combined(app_name):
    """
    S1 + S2 combined ranges by country for channel post
    Returns: {country: [range1, range2, ...]}
    """
    s1_logs = await get_console_logs()
    s2_logs = await get_xmint_console_logs()
    all_logs = s1_logs + s2_logs

    result = {}
    known_countries = set()

    for log in all_logs:
        log_app = log.get("app_name", "").replace("*", "").strip().upper()
        if log_app != app_name.upper():
            continue
        country = log.get("country", "").strip()
        range_val = log.get("range", "").strip()
        if not range_val:
            continue

        # Unknown/PostPaid country group করো
        if not country or country.lower() in ["unknown", ""]:
            country = "OTHER REGIONS"
        elif country.lower() in ["postpaid", "post paid"]:
            country = "PostPaid"
        else:
            known_countries.add(country)

        if country not in result:
            result[country] = []
        if range_val not in result[country]:
            result[country].append(range_val)

    return result

# =============================================
#   LIVE TRAFFIC MESSAGE BUILDER
# =============================================

def build_live_traffic_message(traffic_data):
    """🚦 Live Traffic — শুধু Facebook, OTP counter + BD time"""
    from datetime import timezone, timedelta
    bd_now = datetime.now(timezone(timedelta(hours=6))).strftime("%I:%M %p")

    # Counter থেকে data নাও
    counter = _get_otp_counter()
    fb_counter = counter.get("FACEBOOK", {})
    counter_total = fb_counter.get("total", 0)

    # Console থেকে S1/S2 breakdown
    fb_console = traffic_data.get("FACEBOOK", {}) if traffic_data else {}
    s1 = fb_console.get("s1", 0)
    s2 = fb_console.get("s2", 0)

    # Total — counter এর total দেখাবে (বেশি accurate)
    total = counter_total if counter_total > 0 else (fb_console.get("total", 0))

    if total == 0:
        return f"🚦 FACEBOOK LIVE TRAFFIC\n\nNo data available.\n\n🕐 Last Update: {bd_now}"

    # Countries — counter থেকে
    countries = fb_counter.get("countries", {})
    if not countries:
        countries = fb_console.get("countries", {})

    lines = [f"🚦 FACEBOOK LIVE TRAFFIC — Total OTP: {total}\n"]
    lines.append(f"🔵 S1: {s1} OTP")
    lines.append(f"🟢 S2: {s2} OTP\n")

    sorted_countries = sorted(countries.items(), key=lambda x: x[1], reverse=True)
    top3 = sorted_countries[:3]
    rest = sorted_countries[3:]

    for country, count in top3:
        flag = get_flag(country)
        lines.append(f"⭐ {flag} {country} — {count} OTP")

    if rest:
        lines.append("")
        for country, count in rest:
            flag = get_flag(country)
            lines.append(f"{flag} {country} — {count} OTP")

    lines.append(f"\n🕐 Last Update: {bd_now}")
    return "\n".join(lines)

# =============================================
#   RANGE DASHBOARD MESSAGE BUILDER
# =============================================

def build_range_dashboard(app_name, ranges_by_country, interval_min=20):
    """Channel এ post করার জন্য range dashboard — S1/S2 আলাদা, BD time"""
    from datetime import timezone, timedelta
    if not ranges_by_country:
        return None

    bd_now = datetime.now(timezone(timedelta(hours=6)))
    current_time = bd_now.strftime("%I:%M %p")
    next_time = (bd_now + timedelta(minutes=interval_min)).strftime("%I:%M %p")

    # total ranges count — S1+S2 combined per country
    total_ranges = sum(len(v["S1"]) + len(v["S2"]) for v in ranges_by_country.values())
    total_countries = len([k for k in ranges_by_country if k not in ("OTHER REGIONS",)])

    app_emoji = APP_EMOJIS.get(app_name.upper(), "📱")

    lines = []
    lines.append(f"{app_emoji} {app_name.upper()} LIVE RANGE S1/S2\n")
    lines.append(f"📊 TOTAL COUNTRIES: {total_countries}")
    lines.append(f"🟨 TOTAL RANGES: {total_ranges}")
    lines.append(f"🟩 UPDATE INTERVAL: {interval_min} MIN\n")

    # Sort by total ranges per country (S1+S2)
    def country_total(item):
        return len(item[1]["S1"]) + len(item[1]["S2"])

    # Known countries first, PostPaid, OTHER REGIONS last
    known = {k: v for k, v in ranges_by_country.items() if k not in ("OTHER REGIONS", "PostPaid")}
    postpaid = {"PostPaid": ranges_by_country["PostPaid"]} if "PostPaid" in ranges_by_country else {}
    other = {"OTHER REGIONS": ranges_by_country["OTHER REGIONS"]} if "OTHER REGIONS" in ranges_by_country else {}

    sorted_known = sorted(known.items(), key=country_total, reverse=True)
    sorted_postpaid = sorted(postpaid.items(), key=country_total, reverse=True)
    sorted_other = sorted(other.items(), key=country_total, reverse=True)
    sorted_countries = sorted_known + sorted_postpaid + sorted_other

    top2 = {k for k, _ in sorted_known[:2]}

    number_emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

    for country, panels in sorted_countries:
        flag = get_flag(country)
        star = "⭐ " if country in top2 else ""
        total = len(panels["S1"]) + len(panels["S2"])
        lines.append(f"{star}🌍 {flag} {country.upper()} — {total}")

        if panels["S1"]:
            lines.append("🔵 S1")
            for i, r in enumerate(panels["S1"]):
                num_emoji = number_emojis[i] if i < len(number_emojis) else f"{i+1}."
                lines.append(f"{num_emoji} `{r}`")

        if panels["S2"]:
            lines.append("🟢 S2")
            for i, r in enumerate(panels["S2"]):
                num_emoji = number_emojis[i] if i < len(number_emojis) else f"{i+1}."
                lines.append(f"{num_emoji} `{r}`")

        lines.append("")

    lines.append(f"🕐 LAST UPDATE: {current_time}")
    lines.append(f"⏳ NEXT UPDATE: {next_time}")
    lines.append("______Power by Shuvo........")

    return "\n".join(lines)

# =============================================
#   AUTO RANGE POST TO CHANNEL (Every 20 min)
# =============================================

# =============================================
#   LIVE SMS POST TO CHANNEL (Every 30 sec)
# =============================================

# Already posted entries track করো (duplicate avoid)
_posted_sms_ids = set()

_job_is_running = False  # Job running flag

async def job_post_live_sms(context):
    """Optimized: no timeout loss + retry + safe delay"""
    global _posted_sms_ids, _job_is_running

    if _job_is_running:
        logging.warning("⚠️ job already running, skipping...")
        return

    _job_is_running = True

    try:
        bot = context.bot

        s1_logs = await asyncio.wait_for(get_console_logs(force=True), timeout=20)
        s2_logs = await asyncio.wait_for(get_xmint_console_logs(force=True), timeout=20)

        messages_to_send = []

        for panel_label, logs in [("S1", s1_logs), ("S2", s2_logs)]:
            for log in logs:
                app = log.get("app_name", "").replace("*", "").strip().upper()
                if app != "FACEBOOK":
                    continue

                range_val = log.get("range", "").strip()
                log_time = log.get("time", "").strip()
                # Duplicate fix: panel prefix সরিয়ে দিলাম
                # S1+S2 same range/time হলে একটাই post হবে
                unique_id = f"{range_val}_{log_time}"

                if unique_id in _posted_sms_ids:
                    continue

                _posted_sms_ids.add(unique_id)

                country = log.get("country", "").strip() or "Unknown"
                flag = get_flag(country)
                # SMS field — multiple possible names check করো
                raw_sms = (
                    log.get("message", "") or
                    log.get("sms", "") or
                    log.get("raw_sms", "") or
                    log.get("text", "") or
                    log.get("body", "") or
                    log.get("content", "") or ""
                ).strip()

                # ✅ প্রথম লাইনে isolated star group count (H**Q+Fsn*Sr ignore)
                import re as _re
                _fl = raw_sms.splitlines()[0] if raw_sms else ""
                _sg = _re.findall(r'(?<![A-Za-z0-9])\*{2,}(?![A-Za-z0-9])', _fl)
                otp_len = sum(len(g) for g in _sg) if _sg else 6
                otp_len = max(5, min(8, otp_len))  # 4 digit fake — min 5
                otp = ''.join([str(random.randint(0, 9)) for _ in range(otp_len)])

                if range_val and not range_val.upper().endswith('X'):
                    display_range = range_val + "XXX"
                else:
                    display_range = range_val

                msg = (
                    f"{escape_mdv2(country)} {flag}\n\n"
                    f"📞 `{escape_mdv2(display_range)}`\n"
                    f"🔐 `{escape_mdv2(otp)}`\n"
                    f"💬 Service: Facebook \\| {escape_mdv2(panel_label)}\n"
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
                    InlineKeyboardButton("🤖 Number Bot", url="https://t.me/Fb_KiNG_Seviceotp_bot"),
                ]])

                messages_to_send.append((msg, keyboard))

        # Limit to avoid flood
        messages_to_send = messages_to_send[:20]

        for msg, keyboard in messages_to_send:
            success = False

            # Try 2 times max
            for attempt in range(2):
                try:
                    await asyncio.wait_for(
                        safe_send_message(
                            bot,
                            chat_id=RANGE_CHANNEL_ID,
                            text=msg,
                            parse_mode="MarkdownV2",
                            reply_markup=keyboard
                        ),
                        timeout=30
                    )
                    success = True
                    logging.info(f"✅ Message posted successfully")
                    await asyncio.sleep(random.uniform(1, 2))
                    break

                except asyncio.TimeoutError:
                    logging.warning(f"⚠️ Timeout (attempt {attempt+1}), retrying...")

                except Exception as e:
                    logging.error(f"Error posting message: {e}")
                    break

            if not success:
                logging.error(f"❌ Failed to post message after 2 attempts")

        # Memory leak avoid
        if len(_posted_sms_ids) > 5000:
            _posted_sms_ids = set(list(_posted_sms_ids)[-2000:])

        logging.info(f"✅ job_post_live_sms completed: {len(messages_to_send)} messages processed")

    except asyncio.TimeoutError:
        logging.error("⚠️ job_post_live_sms timeout — logs fetch failed")
    except Exception as e:
        logging.error(f"job_post_live_sms error: {e}")
    finally:
        _job_is_running = False

# =============================================
#         API FUNCTIONS (S1)
# =============================================

async def api_get_number(range_val, app_name="FACEBOOK", _retry=0):
    clean_range = ''.join(c for c in range_val.upper() if c.isdigit() or c == 'X')
    if not clean_range:
        return {"error": "Invalid range"}, None
    x_count = len(clean_range) - len(clean_range.rstrip('X'))
    if x_count < 3:
        clean_range = clean_range.rstrip('X') + 'XXX'
    payload = {
        "range": clean_range,
        "is_national": False,
        "remove_plus": False,
        "app": app_name
    }
    session = await session_pool.get_number_session()
    try:
        token = session.get("token")
        sess = session.get("session")
        if not token:
            return {"error": "No session available"}, None

        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(
                f"{BASE_URL}/mdashboard/getnum/number",
                json=payload,
                headers=get_headers(token, sess)
            )

        if res.status_code == 403:
            new_session = await session_pool._login_once()
            if new_session.get("token") and _retry < 2:
                await asyncio.sleep(1)
                return await api_get_number(range_val, app_name, _retry=_retry + 1)
            return {"error": "session_expired"}, new_session if new_session.get("token") else None

        if res.status_code in (429, 503):
            wait_time = 10 * (2 ** _retry)
            await session_pool.return_number_session(session)
            if _retry < 3:
                await asyncio.sleep(wait_time)
                return await api_get_number(range_val, app_name, _retry=_retry + 1)
            return {"error": f"HTTP {res.status_code}"}, None

        if res.status_code != 200:
            await session_pool.return_number_session(session)
            return {"error": f"HTTP {res.status_code}"}, None

        try:
            data = res.json()
        except Exception:
            await session_pool.return_number_session(session)
            return {"error": "Invalid JSON"}, None

        msg = str(data.get("message", "")).lower()
        if any(k in msg for k in ["block", "rate", "limit", "many", "temporary"]):
            await session_pool.return_number_session(session)
            if _retry < 3:
                wait_time = 10 * (2 ** _retry)
                await asyncio.sleep(wait_time)
                return await api_get_number(range_val, app_name, _retry=_retry + 1)
            return data, None
        return data, session
    except Exception as e:
        logging.error(f"api_get_number error: {e}")
        await session_pool.return_number_session(session)
        return {"error": str(e)}, None

async def api_get_info(search="", status="", saved_session=None):
    if not saved_session or not saved_session.get("token"):
        return {"error": "No session"}
    session = saved_session
    try:
        token = session.get("token")
        sess = session.get("session")
        clean_search = search.replace("+", "").strip()
        today = datetime.now().strftime("%Y-%m-%d")
        params = {"date": today, "page": 1, "search": clean_search, "status": status}
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{BASE_URL}/mdashboard/getnum/info",
                params=params,
                headers=get_headers(token, sess)
            )
        if res.status_code == 403:
            return {"error": "session_expired"}
        if res.status_code != 200:
            return {"error": f"HTTP {res.status_code}"}
        try:
            return res.json()
        except Exception:
            return {"error": "Invalid JSON"}
    except Exception as e:
        return {"error": str(e)}

# =============================================
#              HELPERS
# =============================================

def init_user(user_id):
    if user_id not in user_data:
        user_data[user_id] = {}
    d = user_data[user_id]
    d.setdefault("app", "FACEBOOK")
    d.setdefault("panel", "S1")
    d.setdefault("country", None)
    d.setdefault("range", None)
    d.setdefault("last_number", None)
    d.setdefault("waiting_for", None)
    d.setdefault("joined", datetime.now().strftime("%Y-%m-%d %H:%M"))
    d.setdefault("name", "User")

# =============================================
#         USER DATABASE (Telegram Channel)
# =============================================

# ✅ DB channel বাদ — db_save_user removed

# ✅ DB channel বাদ — _parse_user_record removed

# ✅ DB channel বাদ — _db_forward_read, _safe_delete, db_load_all_users removed

# =============================================
#              MENUS
# =============================================

def main_keyboard(user_id=None):
    """Reply keyboard — 🚦 Live Traffic button added"""
    buttons = [
        [KeyboardButton("📞 Get Number"), KeyboardButton("📡 Custom Range")],
        [KeyboardButton("⏭️ Bulk Number"), KeyboardButton("🚦 Live Traffic")],
        [KeyboardButton("🛟 Support Admin")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

START_MENU_TEXT = "╔════════════════════╗\n   🏴‍☠️ NUMBER PANEL OTP 🇧🇩\n╚════════════════════╝\n\n◈ Select Your Service"

APP_DISPLAY_NAMES = {
    "FACEBOOK": "Facebook",
    "INSTAGRAM": "Instagram",
    "WHATSAPP": "WhatsApp",
    "TELEGRAM": "Telegram",
}

async def get_dynamic_apps():
    """S1 + S2 console থেকে available apps আনো"""
    try:
        s1_logs = await get_console_logs()
        s2_logs = await get_xmint_console_logs()
        all_logs = s1_logs + s2_logs
        seen = set()
        apps = []
        for log in all_logs:
            app_name = log.get("app_name", "").replace("*", "").strip().upper()
            if app_name and app_name != "FACEBOOK" and app_name not in seen:
                seen.add(app_name)
                apps.append(app_name)
        random.shuffle(apps)
        return apps[:5]
    except Exception as e:
        logging.error(f"get_dynamic_apps error: {e}")
        return []

async def app_select_inline_dynamic():
    dynamic_apps = await get_dynamic_apps()
    buttons = [
        [InlineKeyboardButton("🟦 Facebook", callback_data="select_app_FACEBOOK")],
    ]
    for app_name in dynamic_apps:
        emoji = APP_EMOJIS.get(app_name, "📱")
        display = app_name.capitalize()
        buttons.append([InlineKeyboardButton(f"{emoji} {display}", callback_data=f"select_app_{app_name}")])
    return InlineKeyboardMarkup(buttons)

def server_select_inline(app_name):
    display = app_name.capitalize()
    s1_btn = InlineKeyboardButton(f"☎️ {display} S1", callback_data=f"app_s1_{app_name}")
    s2_btn = InlineKeyboardButton(f"☎️ {display} S2", callback_data=f"app_s2_{app_name}")
    order = [s1_btn, s2_btn] if random.randint(0, 1) == 0 else [s2_btn, s1_btn]
    buttons = [
        [order[0]],
        [order[1]],
        [InlineKeyboardButton("◀️ Back", callback_data="back_app")],
    ]
    return InlineKeyboardMarkup(buttons)

def country_select_inline(countries, app_name):
    """Country select — carrier step নেই, directly range এ যাবে"""
    buttons = []
    for c in countries:
        if isinstance(c, dict):
            country = c["country"]
            panel = c["panel"]
            flag = get_flag(country)
            buttons.append([InlineKeyboardButton(
                f"{flag} {country}", callback_data=f"country_{panel}_{country}"
            )])
        else:
            flag = get_flag(c)
            buttons.append([InlineKeyboardButton(
                f"{flag} {c}", callback_data=f"country_{c}"
            )])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data=f"select_app_{app_name}")])
    return InlineKeyboardMarkup(buttons)

def range_select_inline(ranges, app_name, country):
    """Carrier step removed — directly ranges দেখাও"""
    buttons = []
    for r in ranges[:20]:
        buttons.append([InlineKeyboardButton(
            f"📡 {r['range']}", callback_data=f"range_{r['range']}"
        )])
    buttons.append([InlineKeyboardButton(
        "◀️ Back", callback_data=f"back_country_{app_name}"
    )])
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
#         AUTO OTP CHECK
# =============================================

async def safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
        chat_id = query.message.chat.id
        user_msg[chat_id] = query.message.message_id
        user_range_msg[chat_id] = query.message.message_id
    except Exception as e:
        err_msg = str(e).lower()
        if "message is not modified" in err_msg or "message to edit not found" in err_msg:
            return
        if "bad request" in err_msg or "400" in err_msg:
            try:
                chat_id = query.message.chat.id
                new_msg = await query.message.reply_text(text, **kwargs)
                user_msg[chat_id] = new_msg.message_id
                user_range_msg[chat_id] = new_msg.message_id
            except Exception as e2:
                logging.warning(f"safe_edit fallback error: {e2}")
        else:
            logging.warning(f"Edit message error: {e}")

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

async def auto_otp_single(number, user_id, stop_event, otp_callback):
    clean_num = number.replace("+", "").replace(" ", "").strip()
    app = user_data[user_id].get("app", "FACEBOOK")
    panel = user_data[user_id].get("panel", "S1")
    seen_otps = set()
    elapsed = 0

    while not stop_event.is_set():
        if not user_data[user_id].get("otp_active", True):
            return
        interval = 5 if elapsed < 60 else 10
        await asyncio.sleep(interval)
        elapsed += interval
        if stop_event.is_set():
            return
        try:
            nums = []
            if panel == "S1":
                saved_session = user_data[user_id].get("number_session")
                if not saved_session or not saved_session.get("token"):
                    return
                data = await api_get_info(search=clean_num, status="success", saved_session=saved_session)
                if data.get("meta", {}).get("code") == 200:
                    nums = data["data"].get("numbers") or []
            else:
                # S2 — আলাদা xmint pool থেকে session নাও
                s2_session = await xmint_pool.get_otp_session()
                if not s2_session or not s2_session.get("token"):
                    await xmint_pool.return_otp_session(s2_session)
                    return
                data = await api_get_info_s2(search=clean_num, status="success", saved_session=s2_session)
                await xmint_pool.return_otp_session(s2_session)
                if data.get("meta", {}).get("code") == 200:
                    nums = data["data"].get("numbers") or []

            for n in nums:
                api_num = str(n.get("number", "")).replace("+", "").replace(" ", "").strip()
                if clean_num != api_num:
                    continue
                # otp field আগে নাও, 000000 হলে message/sms field থেকে নাও
                _otp_field = str(n.get("otp") or "").strip()
                _msg_field = (
                    n.get("message") or n.get("sms") or
                    n.get("raw_sms") or n.get("text") or
                    n.get("body") or n.get("content") or ""
                ).strip()

                # 000000 বা খালি হলে সরাসরি message field দিয়ে try করো
                if re.fullmatch(r'0+', _otp_field) or not _otp_field:
                    raw_otp = _msg_field or _otp_field
                else:
                    raw_otp = _otp_field or _msg_field

                otp = extract_otp(raw_otp)

                # তখনও না পেলে message field আলাদাভাবে try করো
                if not otp or re.fullmatch(r'0+', otp):
                    if _msg_field and _msg_field != raw_otp:
                        fallback = extract_otp(_msg_field)
                        if fallback and not re.fullmatch(r'0+', fallback):
                            otp = fallback
                            raw_otp = _msg_field

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

LOADING_TEXTS = [
    "⏳ Checking OTP...",
    "⌛ Checking Inbox...",
    "🔄 Retrieving Code...",
    "👀 Still Checking...",
    "✅ Verifying...",
    "📡 Looking For Response...",
    "⏳ Please Wait...",
]

async def auto_otp_multi(message, numbers, user_id, range_val, bot=None):
    if user_data[user_id].get("otp_running"):
        return
    user_data[user_id]["otp_running"] = True
    user_data[user_id]["otp_active"] = True

    app = user_data[user_id].get("app", "FACEBOOK")
    panel = user_data[user_id].get("panel", "S1")
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

    async def update_msg(extra=""):
        nonlocal sent_message
        chat_id = message.chat.id
        msg_id = user_msg.get(chat_id) or (sent_message.message_id if sent_message else None)
        if not msg_id or not bot:
            return
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=build_message(extra),
                parse_mode="Markdown",
                reply_markup=after_number_inline(numbers[0], range_val)
            )
        except Exception:
            pass

    async def on_otp(otp, n, raw_otp, found_country, found_app):
        flag = get_flag(found_country)
        app_cap = found_app.capitalize()
        found_num = n.get("number", numbers[0])
        clean_found_num = str(found_num).replace("+", "").strip()

        if bot:
            try:
                await send_otp_to_channel(bot, clean_found_num, otp, found_app, found_country, flag, raw_otp, panel)
            except Exception as e:
                logging.error(f"Channel send error: {e}")

        current_num = str(user_data[user_id].get("last_number", "")).replace("+", "").replace(" ", "").strip()
        # শেষের 7 digit দিয়ে match করো — loose match
        match = (
            current_num in clean_found_num or
            clean_found_num in current_num or
            (len(current_num) >= 7 and len(clean_found_num) >= 7 and current_num[-7:] == clean_found_num[-7:])
        )
        if match:
            otp_index = len(otp_lines) + 1
            otp_lines.append(f"\n✅ OTP {otp_index} :  `{otp}`")
            chat_id = message.chat.id
            msg_text = build_message()
            edited = False
            if chat_id in user_msg and bot:
                try:
                    result = await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=user_msg[chat_id],
                        text=msg_text,
                        parse_mode="Markdown",
                        reply_markup=after_number_inline(numbers[0], range_val)
                    )
                    if result:
                        sent_message = result
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
                    logging.error(f"OTP reply error: {e}")

    async def _run():
        nonlocal sent_message, base_text

        OTP_TIMEOUT = 10 * 60
        elapsed = 0
        last_otp_count = 0

        number = numbers[0]
        inner_task = asyncio.create_task(auto_otp_single(number, user_id, stop_event, on_otp))

        while not stop_event.is_set():
            # OTP নতুন আসলে timer reset
            if len(otp_lines) > last_otp_count:
                last_otp_count = len(otp_lines)
                elapsed = 0

            if sent_message and not otp_lines:
                loading = random.choice(LOADING_TEXTS)
                await update_msg(f"\n{loading}")
            await asyncio.sleep(5)
            elapsed += 5

            if elapsed >= OTP_TIMEOUT:
                stop_event.set()
                break

        stop_event.set()
        inner_task.cancel()
        await asyncio.gather(inner_task, return_exceptions=True)

        saved_session = user_data[user_id].get("number_session")
        if saved_session and saved_session.get("token"):
            panel_s = user_data[user_id].get("panel", "S1")
            if panel_s == "S1":
                await session_pool.return_number_session(saved_session)
            else:
                await xmint_pool.return_number_session(saved_session)
            user_data[user_id]["number_session"] = None

        user_data[user_id]["otp_running"] = False
        user_data[user_id]["otp_active"] = False

    number = numbers[0]
    country_r = user_data[user_id].get("country_r") or user_data[user_id].get("country", "")
    flag = get_flag(country_r)
    clean_number = str(number).replace("+", "").strip()

    base_text = (
        f"🔷 {app.upper()} NUMBER\n\n"
        f"📞 Number : `{clean_number}`\n"
        f"🌍 Region : {flag} {get_country_code(country_r) or country_r}\n"
        f"🟢 Status : Active\n"
        f"─────────────────"
    )

    chat_id = message.chat.id
    msg_text = build_message(f"\n{random.choice(LOADING_TEXTS)}")

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
        logging.error(f"Send message error: {e}")
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
    panel = user_data[user_id].get("panel", "S1")

    if not range_val:
        await message.reply_text(
            "❌ Range select করা হয়নি!\n\n"
            "🏠 Start → Service → Country → Range",
            reply_markup=main_keyboard(user_id)
        )
        return

    if count == 1:
        chat_id = message.chat.id
        if chat_id in user_msg:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=user_msg[chat_id])
            except Exception:
                pass
            user_msg.pop(chat_id, None)

        # /get command এ loading reply off করা হয়েছে

        if panel == "S1":
            data, number_session = await api_get_number(range_val, app)
        else:
            data, number_session = await api_get_number_s2(range_val, app)

        if data.get("meta", {}).get("code") == 200:
            num = data["data"]
            number = (
                num.get("number") or num.get("num") or
                num.get("phone") or num.get("mobile") or "N/A"
            )
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
                if panel == "S1":
                    await session_pool.return_number_session(number_session)
                else:
                    await xmint_pool.return_number_session(number_session)
            err_msg = data.get("message") or data.get("error") or "Number পাওয়া যায়নি"
            await message.reply_text(f"❌ {err_msg}", reply_markup=main_keyboard(user_id))
    else:
        await message.reply_text(f"⏳ {count}টি number নেওয়া হচ্ছে...")
        got = 0
        msg = f"📦 BULK GET — Range: {range_val}\n📱 App: {app}\n🖥 Panel: {panel}\n\n"
        for i in range(count):
            if panel == "S1":
                data, sess = await api_get_number(range_val, app)
                if sess:
                    await session_pool.return_number_session(sess)
            else:
                data, sess = await api_get_number_s2(range_val, app)
                if sess:
                    await xmint_pool.return_number_session(sess)
            if data.get("meta", {}).get("code") == 200:
                num = data["data"]
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

async def do_otp_check(message, number, user_id=None, bot=None):
    clean_number = number.replace("+", "").replace(" ", "").strip()
    await message.reply_text(f"🔍 OTP চেক করা হচ্ছে...\n📞 {number}")

    data = await api_get_info(search=clean_number, status="success")
    nums = data.get("data", {}).get("numbers") or [] if data.get("meta", {}).get("code") == 200 else []

    found = []
    for n in nums:
        raw_otp = (n.get("otp") or n.get("message") or "").strip()
        otp = extract_otp(raw_otp)
        if otp:
            found.append((n, otp, raw_otp))

    if not found:
        data2 = await api_get_info(search=clean_number, status="")
        nums2 = data2.get("data", {}).get("numbers") or [] if data2.get("meta", {}).get("code") == 200 else []
        for n in nums2:
            if n.get("status") == "success":
                raw_otp = (n.get("otp") or n.get("message") or "").strip()
                otp = extract_otp(raw_otp)
                if otp:
                    found.append((n, otp, raw_otp))

    if found:
        n, otp, raw_otp = found[0]
        app = user_data.get(user_id, {}).get("app", "FACEBOOK") if user_id else "FACEBOOK"
        detected_app = detect_app_from_message(raw_otp, app)
        country_r = n.get("country", "") or (user_data.get(user_id, {}).get("country", "") if user_id else "")
        flag = get_flag(country_r)
        clean_num_display = str(n.get('number', number)).replace("+", "").strip()

        _panel = user_data.get(user_id, {}).get("panel", "S1") if user_id else "S1"
        if bot:
            await send_otp_to_channel(bot, clean_num_display, otp, detected_app, country_r, flag, raw_otp, _panel)
        else:
            app_cap = detected_app.capitalize()
            await message.reply_text(
                f"🌎 Country : {country_r} {app_cap} {flag}\n"
                f"🔢 Number : `{clean_num_display}`\n"
                f"🔑 OTP : `{otp}`",
                parse_mode="Markdown",
                reply_markup=main_keyboard(user_id)
            )
    else:
        await message.reply_text(
            "⏳ OTP এখনো আসেনি।\n\nকিছুক্ষণ পর আবার check করুন।",
            reply_markup=main_keyboard(user_id)
        )

# =============================================
#         COMMAND HANDLERS
# =============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    is_new_user = user_id not in user_data
    init_user(user_id)
    user_data[user_id]["name"] = user.first_name or "User"

    if is_new_user:
        asyncio.create_task(db_save_user(context.bot, user_id))

    # ✅ শুধু নতুন user এর জন্য join check
    if is_new_user:
        ch1_joined, ch2_joined = await check_all_channels_joined(user_id, context.bot)
        if not ch1_joined or not ch2_joined:
            keyboard_buttons = []
            if not ch1_joined:
                keyboard_buttons.append([InlineKeyboardButton(
                    f"🔗 Main Channel", url=CHANNEL_LINK
                )])
            if not ch2_joined:
                keyboard_buttons.append([InlineKeyboardButton(
                    f"🔗 {CHANNEL2_NAME}", url=CHANNEL2_LINK
                )])
            keyboard_buttons.append([InlineKeyboardButton(
                "✅ Verify", callback_data="verify_join"
            )])
            await update.message.reply_text(
                "🚦 Access Locked. Join all channels then Verify.",
                reply_markup=InlineKeyboardMarkup(keyboard_buttons)
            )
            return

    # Bug #1 #2 fix — range + country always clear on start
    cancel_all_otp_tasks(user_id)
    user_data[user_id]["range"] = None
    user_data[user_id]["country"] = None
    user_data[user_id]["otp_active"] = False
    user_data[user_id]["otp_running"] = False

    chat_id = update.message.chat.id
    for msg_dict in [user_msg, user_range_msg]:
        if chat_id in msg_dict:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_dict[chat_id])
            except Exception:
                pass
            msg_dict.pop(chat_id, None)

    try:
        await update.message.delete()
    except Exception:
        pass

    # ✅ Welcome message — inline menu নেই, শুধু welcome + keyboard
    welcome_text = (
        "╔══════════════════════╗\n"
        f"   🎉 স্বাগতম, {user.first_name}! 🎉\n"
        "╚══════════════════════╝\n\n"
        "🤖 *@Fb_KiNG_Seviceotp_bot*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ *Super Fast OTP Service*\n"
        "🌍 *Worldwide Numbers*\n"
        "🔒 *100% Secure & Trusted*\n"
        "🕐 *24/7 Active Service*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👇 *নিচের Menu থেকে শুরু করুন!*"
    )
    kb_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=welcome_text,
        parse_mode="Markdown",
        reply_markup=main_keyboard(user_id)
    )
    user_kb_msg[chat_id] = kb_msg.message_id

async def cmd_get(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    init_user(user_id)
    user_data[user_id]["name"] = user.first_name or "User"
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
    await update.message.reply_text("🛑 Auto OTP check বন্ধ হয়েছে.", reply_markup=main_keyboard(user_id))

async def cmd_mynum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    init_user(user_id)
    await update.message.reply_text("⏳ Loading...")

    panel = user_data[user_id].get("panel", "S1")
    last_number = str(user_data[user_id].get("last_number", "")).replace("+", "").strip()

    if not last_number:
        await update.message.reply_text(
            "❌ কোনো number নেওয়া হয়নি।", reply_markup=main_keyboard(user_id)
        )
        return

    if panel == "S1":
        _s1_session = await session_pool.get_otp_session()
        data = await api_get_info(search=last_number, saved_session=_s1_session)
        await session_pool.return_otp_session(_s1_session)
    else:
        _s2_session = await xmint_pool.get_otp_session()
        data = await api_get_info_s2(search=last_number, saved_session=_s2_session)
        await xmint_pool.return_otp_session(_s2_session)

    if data.get("meta", {}).get("code") == 200:
        nums = data["data"].get("numbers", []) or []
        stats = data["data"].get("stats", {})
        msg = (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📋  My Numbers ({panel})\n"
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
        f"━━━━━━━━━━━━━━━━━━\n📊  BOT STATS\n━━━━━━━━━━━━━━━━━━\n\n"
        f"👥  Users: {len(user_data)}\n"
        f"📦  Get 100: {'✅ ON' if GET100_ENABLED else '❌ OFF'}\n"
        f"🕐  {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n━━━━━━━━━━━━━━━━━━"
    )

async def cmd_apistatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    token_s1, _ = await fresh_login()
    status_s1 = "✅ Connected" if token_s1 else "❌ Failed"
    token_s2 = await get_xmint_token()
    status_s2 = "✅ Connected" if token_s2 else "❌ Failed"
    await update.message.reply_text(
        f"━━━━━━━━━━━━━━━━━━\n🔗 API STATUS\n━━━━━━━━━━━━━━━━━━\n\n"
        f"📡 S1 (StexSMS): {status_s1}\n"
        f"  🔢 Number slots: {session_pool.number_sessions.qsize()}/50\n"
        f"  🔑 OTP slots: {session_pool.otp_sessions.qsize()}/50\n\n"
        f"📡 S2 (X.Mint): {status_s2}\n"
        f"  🔢 Number slots: {xmint_pool.number_sessions.qsize()}/25\n"
        f"  🔑 OTP slots: {xmint_pool.otp_sessions.qsize()}/25\n\n"
        f"👥 Total Users: {len(user_data)}\n━━━━━━━━━━━━━━━━━━"
    )

async def cmd_refreshsessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("🔄 Session pool refresh হচ্ছে...")
    await session_pool.refresh_all()
    await update.message.reply_text(
        f"✅ S1 refresh done!\nNumber: {session_pool.number_sessions.qsize()}/50\n"
        f"OTP: {session_pool.otp_sessions.qsize()}/50"
    )

async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID and user_id != 1984916365:
        await update.message.reply_text("❌ Admin access নেই।")
        return
    get100_status = "✅ ON" if GET100_ENABLED else "❌ OFF"
    msg = (
        "━━━━━━━━━━━━━━━━━━\n👑  ADMIN PANEL\n━━━━━━━━━━━━━━━━━━\n\n"
        "📋  /allusers\n📊  /stats\n🔑  /apistatus\n📢  /broadcast\n\n"
        f"📦  Bulk: {get100_status}\n"
        "/get100on | /get100off\n/addget100 <id> | /removeget100 <id>\n\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(msg, reply_markup=admin_keyboard())

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    user_data[ADMIN_ID]["waiting_for"] = "broadcast"
    await update.message.reply_text("📢 সবাইকে কী message পাঠাবেন?")

async def cmd_get100on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GET100_ENABLED
    if update.effective_user.id != ADMIN_ID:
        return
    GET100_ENABLED = True
    await update.message.reply_text("✅ Get 100 চালু।")

async def cmd_get100off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GET100_ENABLED
    if update.effective_user.id != ADMIN_ID:
        return
    GET100_ENABLED = False
    await update.message.reply_text("❌ Get 100 বন্ধ।")

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

    # ✅ VERIFY JOIN BUTTON
    if data == "verify_join":
        clear_join_cache(user_id)
        ch1_joined, ch2_joined = await check_all_channels_joined(user_id, context.bot)
        if ch1_joined and ch2_joined:
            try:
                await query.message.delete()
            except Exception:
                pass
            # সব clear করে main menu দেখাও
            cancel_all_otp_tasks(user_id)
            user_data[user_id]["range"] = None
            user_data[user_id]["country"] = None
            user_data[user_id]["otp_active"] = False
            user_data[user_id]["otp_running"] = False
            chat_id = query.message.chat.id
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Verified! Welcome, {user_name}!\n\n" + START_MENU_TEXT,
                reply_markup=main_keyboard(user_id)
            )
            inline_kb = await app_select_inline_dynamic()
            new_msg = await context.bot.send_message(chat_id=chat_id, text=START_MENU_TEXT, reply_markup=inline_kb)
            user_msg[chat_id] = new_msg.message_id
        else:
            # কোন channel join হয়নি সেটা দেখাও
            keyboard_buttons = []
            if not ch1_joined:
                keyboard_buttons.append([InlineKeyboardButton("🔗 Main Channel", url=CHANNEL_LINK)])
            if not ch2_joined:
                keyboard_buttons.append([InlineKeyboardButton(f"🔗 {CHANNEL2_NAME}", url=CHANNEL2_LINK)])
            keyboard_buttons.append([InlineKeyboardButton("✅ Verify", callback_data="verify_join")])
            try:
                await query.edit_message_text(
                    "🚦 Access Locked. Join all channels then Verify.",
                    reply_markup=InlineKeyboardMarkup(keyboard_buttons)
                )
            except Exception:
                pass
        return


        cancel_all_otp_tasks(user_id)
        user_data[user_id].update({
            "auto_otp_cancel": True, "otp_active": False, "otp_running": False,
            "number_session": None, "last_number": None,
            "country_r": None, "range": None, "country": None,
        })
        await asyncio.sleep(0.1)
        user_data[user_id]["auto_otp_cancel"] = False
        chat_id = query.message.chat.id
        try:
            await query.message.delete()
        except Exception:
            pass
        for msg_dict in [user_msg, user_range_msg]:
            if chat_id in msg_dict:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_dict[chat_id])
                except Exception:
                    pass
                msg_dict.pop(chat_id, None)
        inline_kb = await app_select_inline_dynamic()
        new_msg = await context.bot.send_message(chat_id=chat_id, text=START_MENU_TEXT, reply_markup=inline_kb)
        user_msg[chat_id] = new_msg.message_id
        return

    if data == "stop_auto":
        cancel_all_otp_tasks(user_id)
        user_data[user_id]["auto_otp_cancel"] = True
        user_data[user_id]["otp_active"] = False
        user_data[user_id]["otp_running"] = False
        await query.answer("🛑 Auto OTP বন্ধ করা হয়েছে!")
        return

    if data.startswith("select_app_"):
        app_name = data.replace("select_app_", "")
        user_data[user_id]["app"] = app_name
        user_data[user_id]["country"] = None
        user_data[user_id]["range"] = None
        emoji = APP_EMOJIS.get(app_name, "📱")

        if app_name == "FACEBOOK":
            await safe_edit(query,
                f"{emoji} {app_name.capitalize()}\n\nServer select করুন:",
                reply_markup=server_select_inline(app_name)
            )
        else:
            await safe_edit(query, "⏳ লোড হচ্ছে...")
            s1_countries = await get_countries_for_app(app_name, panel="S1")
            s2_countries = await get_countries_for_app(app_name, panel="S2")
            seen = set()
            countries = []
            for c in s1_countries:
                if c not in seen:
                    seen.add(c)
                    countries.append({"country": c, "panel": "S1"})
            for c in s2_countries:
                if c not in seen:
                    seen.add(c)
                    countries.append({"country": c, "panel": "S2"})
            if not countries:
                await safe_edit(query, f"❌ {app_name} এর জন্য কোনো active country নেই.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="back_app")]]))
                return
            await safe_edit(query,
                f"{emoji} {app_name.capitalize()}\n\n🌍 Country select করুন:",
                reply_markup=country_select_inline(countries, app_name)
            )
        return

    if data.startswith("app_s1_"):
        app_name = data.replace("app_s1_", "")
        user_data[user_id].update({"app": app_name, "panel": "S1", "country": None, "range": None})
        await safe_edit(query, "⏳ লোড হচ্ছে...")
        countries = await get_countries_for_app(app_name, panel="S1")
        if not countries:
            await safe_edit(query, "❌ এখন কোনো active country নেই.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data=f"select_app_{app_name}")]]))
            return
        await safe_edit(query,
            f"☎️ {app_name.capitalize()} S1\n\n🌍 Country select করুন:",
            reply_markup=country_select_inline(countries, app_name)
        )

    elif data.startswith("app_s2_"):
        app_name = data.replace("app_s2_", "")
        user_data[user_id].update({"app": app_name, "panel": "S2", "country": None, "range": None})
        await safe_edit(query, "⏳ লোড হচ্ছে...")
        countries = await get_countries_for_app(app_name, panel="S2")
        if not countries:
            await safe_edit(query, "❌ এখন কোনো active country নেই.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data=f"select_app_{app_name}")]]))
            return
        await safe_edit(query,
            f"☎️ {app_name.capitalize()} S2\n\n🌍 Country select করুন:",
            reply_markup=country_select_inline(countries, app_name)
        )

    elif data == "back_app":
        inline_kb = await app_select_inline_dynamic()
        await safe_edit(query, START_MENU_TEXT, reply_markup=inline_kb)

    elif data.startswith("country_"):
        # Carrier step removed — directly ranges load করো
        raw = data.replace("country_", "")
        if raw.startswith("S1_") or raw.startswith("S2_"):
            panel = raw[:2]
            country = raw[3:]
            user_data[user_id]["panel"] = panel
        else:
            country = raw
            panel = user_data[user_id].get("panel", "S1")
        app_name = user_data[user_id].get("app", "FACEBOOK")
        user_data[user_id]["country"] = country
        user_data[user_id]["range"] = None
        await safe_edit(query, "⏳ Range লোড হচ্ছে...")

        # get_all_ranges_for_country — carrier step নেই
        ranges = await get_all_ranges_for_country(app_name, country, panel=panel)

        if not ranges:
            await safe_edit(query, f"❌ {country} তে কোনো range নেই.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data=f"back_country_{app_name}")]]))
            return
        flag = get_flag(country)
        await safe_edit(query,
            f"{flag} {country}\n\n📡 Range select করুন:",
            reply_markup=range_select_inline(ranges, app_name, country)
        )

    elif data.startswith("back_country_"):
        app_name = data.replace("back_country_", "")
        panel = user_data[user_id].get("panel", "S1")
        user_data[user_id]["country"] = None
        await safe_edit(query, "⏳ Loading...")
        countries = await get_countries_for_app(app_name, panel=panel)
        server_label = "S1" if panel == "S1" else "S2"
        await safe_edit(query,
            f"☎️ {app_name.capitalize()} {server_label}\n\n🌍 Country select করুন:",
            reply_markup=country_select_inline(countries, app_name)
        )

    elif data.startswith("range_"):
        range_val = data.replace("range_", "")
        app_name = user_data[user_id].get("app", "FACEBOOK")
        panel = user_data[user_id].get("panel", "S1")
        country = user_data[user_id].get("country", "")
        user_data[user_id]["range"] = range_val
        user_data[user_id]["auto_otp_cancel"] = False

        old_session = user_data[user_id].get("number_session")
        if old_session and old_session.get("token"):
            if user_data[user_id].get("panel", "S1") == "S1":
                await session_pool.return_number_session(old_session)
            else:
                await xmint_pool.return_number_session(old_session)
            user_data[user_id]["number_session"] = None

        cancel_all_otp_tasks(user_id)
        user_data[user_id]["otp_active"] = False
        user_data[user_id]["otp_running"] = False

        chat_id = query.message.chat.id

        # পুরনো message delete করো
        if chat_id in user_msg:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=user_msg[chat_id])
            except Exception:
                pass
            user_msg.pop(chat_id, None)
        try:
            await query.message.delete()
        except Exception:
            pass

        # নতুন loading message পাঠাও
        loading_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Getting Number...")
        user_msg[chat_id] = loading_msg.message_id

        if panel == "S1":
            data_r, number_session = await api_get_number(range_val, app_name)
        else:
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
            asyncio.create_task(auto_otp_multi(loading_msg, [number], user_id, range_val, bot=context.bot))
        else:
            if number_session:
                if panel == "S1":
                    await session_pool.return_number_session(number_session)
                else:
                    await xmint_pool.return_number_session(number_session)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=user_msg.get(chat_id),
                    text="❌ Number পাওয়া যায়নি!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Try Again", callback_data=f"range_{range_val}")],
                        [InlineKeyboardButton("◀️ Back", callback_data="back_app")]
                    ])
                )
            except Exception:
                pass

    elif data.startswith("same_"):
        range_val = data.replace("same_", "")
        app_name = user_data[user_id].get("app", "FACEBOOK")
        panel = user_data[user_id].get("panel", "S1")
        country = user_data[user_id].get("country", "")
        user_data[user_id]["range"] = range_val
        user_data[user_id]["name"] = user_name

        old_session = user_data[user_id].get("number_session")
        if old_session and old_session.get("token"):
            if panel == "S1":
                await session_pool.return_number_session(old_session)
            else:
                await xmint_pool.return_number_session(old_session)
            user_data[user_id]["number_session"] = None

        cancel_all_otp_tasks(user_id)
        user_data[user_id]["otp_active"] = False
        user_data[user_id]["otp_running"] = False

        chat_id = query.message.chat.id

        # user_msg আর query.message একসাথে handle — double delete avoid
        msg_id = user_msg.get(chat_id)
        query_msg_id = query.message.message_id
        if msg_id and msg_id != query_msg_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                pass
        try:
            await query.message.delete()
        except Exception:
            pass
        user_msg.pop(chat_id, None)

        loading_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ Getting Number...")
        user_msg[chat_id] = loading_msg.message_id

        if panel == "S1":
            data_r, number_session = await api_get_number(range_val, app_name)
        else:
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
            asyncio.create_task(auto_otp_multi(loading_msg, [number], user_id, range_val, bot=context.bot))
        else:
            if number_session:
                if panel == "S1":
                    await session_pool.return_number_session(number_session)
                else:
                    await xmint_pool.return_number_session(number_session)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=user_msg.get(chat_id),
                    text="❌ Number পাওয়া যায়নি!"
                )
            except Exception:
                pass

    elif data == "change_range":
        app_name = user_data[user_id].get("app", "FACEBOOK")
        country = user_data[user_id].get("country", "")
        panel = user_data[user_id].get("panel", "S1")

        # Bug 1 fix — OTP task cancel + state reset
        cancel_all_otp_tasks(user_id)
        user_data[user_id]["otp_active"] = False
        user_data[user_id]["otp_running"] = False
        user_data[user_id]["range"] = None  # Bug 3 fix — range reset

        # Bug 2 fix — country নেই তো country select এ পাঠাও, app select এ না
        if not country:
            await safe_edit(query, "⏳ Loading...")
            countries = await get_countries_for_app(app_name, panel=panel)
            server_label = "S1" if panel == "S1" else "S2"
            await safe_edit(query,
                f"☎️ {app_name.capitalize()} {server_label}\n\n🌍 Country select করুন:",
                reply_markup=country_select_inline(countries, app_name)
            )
            return

        await safe_edit(query, "⏳ Range লোড হচ্ছে...")
        ranges = await get_all_ranges_for_country(app_name, country, panel=panel)
        flag = get_flag(country)
        if not ranges:
            await safe_edit(query, f"❌ {country} তে কোনো range নেই.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Back", callback_data=f"back_country_{app_name}")
                ]]))
            return
        await safe_edit(query,
            f"{flag} {country}\n\n📡 Range select করুন:",
            reply_markup=range_select_inline(ranges, app_name, country)
        )

    elif data == "bulk_on":
        if user_id == ADMIN_ID:
            GET100_ENABLED = True
            await query.answer("✅ Bulk চালু!")
            await query.edit_message_reply_markup(reply_markup=admin_keyboard())

    elif data == "bulk_off":
        if user_id == ADMIN_ID:
            GET100_ENABLED = False
            await query.answer("❌ Bulk বন্ধ!")
            await query.edit_message_reply_markup(reply_markup=admin_keyboard())

    elif data == "admin_users":
        if user_id == ADMIN_ID:
            msg = f"👥 Total Users: {len(user_data)}\n\n"
            for uid, uinfo in list(user_data.items())[:15]:
                msg += f"• {uid}  —  {uinfo.get('name','?')}\n"
            await query.message.reply_text(msg)

    elif data == "admin_stats":
        if user_id == ADMIN_ID:
            await query.message.reply_text(
                f"📊 BOT STATS\n\n"
                f"👥 Users: {len(user_data)}\n"
                f"📦 Bulk: {'✅ ON' if GET100_ENABLED else '❌ OFF'}\n"
                f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            )

# =============================================
#         MESSAGE HANDLER
# =============================================

async def auto_menu_restore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply keyboard সবসময় visible রাখো"""
    if not update.message or not update.message.text:
        return
    user_id = update.effective_user.id
    chat_id = update.message.chat.id
    init_user(user_id)
    if chat_id not in user_kb_msg:
        try:
            kb_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⌨️ Menu",
                reply_markup=main_keyboard(user_id)
            )
            user_kb_msg[chat_id] = kb_msg.message_id
        except Exception:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or "User"
    chat_id = update.message.chat.id
    init_user(user_id)
    user_data[user_id]["name"] = user_name

    waiting = user_data[user_id].get("waiting_for")

    # ✅ Button press হলে waiting_for reset করো
    BUTTON_TEXTS = {
        "📞 Get Number", "📡 Custom Range",
        "⏭️ Bulk Number", "🚦 Live Traffic", "🛟 Support Admin"
    }
    if text in BUTTON_TEXTS and waiting == "custom_range":
        user_data[user_id]["waiting_for"] = None
        waiting = None

    # Custom range input
    if waiting == "custom_range":
        range_text = text.strip().upper()
        clean = ''.join(c for c in range_text if c.isdigit() or c == 'X')
        if len(clean) < 4:
            await update.message.reply_text("❌ Invalid range! উদাহরণ: 23762155XXX", reply_markup=main_keyboard(user_id))
            return
        user_data[user_id]["waiting_for"] = None
        user_data[user_id]["range"] = clean
        cancel_all_otp_tasks(user_id)
        user_data[user_id]["otp_active"] = False
        user_data[user_id]["otp_running"] = False

        panel = user_data[user_id].get("panel", "S1")
        app = user_data[user_id].get("app", "FACEBOOK")

        if chat_id in user_msg:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=user_msg[chat_id])
            except Exception:
                pass
            user_msg.pop(chat_id, None)

        try:
            loading_msg = await update.message.reply_text(
                f"✅ Range: `{clean}`\n🖥 Panel: {panel}\n📱 App: {app}\n\n⏳ Number নেওয়া হচ্ছে...",
                parse_mode="Markdown"
            )
            user_msg[chat_id] = loading_msg.message_id
        except Exception:
            pass

        await do_get_number(update.message, user_id, count=1, user_name=user_name, bot=context.bot)
        return

    # Broadcast
    if user_id == ADMIN_ID and waiting == "broadcast":
        user_data[user_id]["waiting_for"] = None
        sent = 0
        failed = 0
        for uid in user_data:
            try:
                await context.bot.send_message(uid, f"📢 Admin Message:\n\n{text}")
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        await update.message.reply_text(f"✅ {sent} জন কে পাঠানো হয়েছে।\n❌ {failed} জন failed।")
        return

    if text in ("🟩 Start", "✧ Start", "🏠 Start", "/start"):
        try:
            await update.message.delete()
        except Exception:
            pass
        await start(update, context)
        return

    if text == "📞 Get Number":
        # Bug #1 #2 fix — range + country clear
        cancel_all_otp_tasks(user_id)
        user_data[user_id]["range"] = None
        user_data[user_id]["country"] = None
        user_data[user_id]["otp_active"] = False
        user_data[user_id]["otp_running"] = False
        for msg_dict in [user_msg, user_range_msg]:
            if chat_id in msg_dict:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_dict[chat_id])
                except Exception:
                    pass
                msg_dict.pop(chat_id, None)
        try:
            await update.message.delete()
        except Exception:
            pass
        inline_kb = await app_select_inline_dynamic()
        new_msg = await context.bot.send_message(chat_id=chat_id, text=START_MENU_TEXT, reply_markup=inline_kb)
        user_msg[chat_id] = new_msg.message_id
        return

    if text in ("📡 Custom Range", "🟨 Cs Range", "✧ Custom Range", "🎯 Custom Range", "🟩 Custom Range"):
        panel = user_data[user_id].get("panel", "S1")
        app = user_data[user_id].get("app", "FACEBOOK")
        cancel_all_otp_tasks(user_id)
        user_data[user_id]["otp_active"] = False
        user_data[user_id]["otp_running"] = False
        user_data[user_id]["waiting_for"] = "custom_range"
        await update.message.reply_text(
            f"📡 Custom Range লিখুন:\n\n🖥 Panel: {panel}\n📱 App: {app}\n\nউদাহরণ: 23762155XXX",
            reply_markup=main_keyboard(user_id)
        )
        return

    if text in ("✧ My Numbers", "📋 My Numbers"):
        await cmd_mynum(update, context)
        return

    if text in ("⏭️ Bulk Number", "🟦 Bulk Number", "📦 Bulk Number"):
        if not has_get100_access(user_id):
            await update.message.reply_text("❌ Bulk Number এখন বন্ধ আছে।", reply_markup=main_keyboard(user_id))
        else:
            await do_get_number(update.message, user_id, count=100, user_name=user_name, bot=context.bot)
        return

    # 🚦 Live Traffic button
    if text == "🚦 Live Traffic":
        await update.message.reply_text("⏳ Live Traffic লোড হচ্ছে...", reply_markup=main_keyboard(user_id))
        try:
            traffic_data = await get_live_traffic_data()
            msg = build_live_traffic_message(traffic_data)
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard(user_id))
        except Exception as e:
            logging.error(f"Live Traffic error: {e}")
            await update.message.reply_text("❌ Data load করতে সমস্যা হয়েছে।", reply_markup=main_keyboard(user_id))
        return

    if text == "🛟 Support Admin":
        await update.message.reply_text(
            "🛟 Support এর জন্য নিচের button এ click করুন:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🛟 Support Admin", url=SUPPORT_ADMIN_LINK)
            ]])
        )
        return

    if text in ("/admin", "✧ Admin Panel", "👑 Admin Panel"):
        if user_id == ADMIN_ID or user_id == 1984916365:
            await cmd_admin(update, context)
        else:
            await update.message.reply_text("❌ Admin access নেই।")
        return

    # Unknown text — keyboard সবসময় দেখাও, delete করো না
    try:
        await update.message.delete()
    except Exception:
        pass
    # kb_msg না থাকলে নতুন করে পাঠাও
    if chat_id not in user_kb_msg:
        try:
            kb_msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⌨️ Menu",
                reply_markup=main_keyboard(user_id)
            )
            user_kb_msg[chat_id] = kb_msg.message_id
        except Exception:
            pass

# =============================================
#              MAIN
# =============================================

# ✅ DB channel বাদ — db_index_existing_users removed


async def post_init(application):
    try:
        asyncio.create_task(session_pool.initialize())
        logging.warning("✅ S1 pool background init started")
    except Exception as e:
        logging.error(f"S1 pool init error: {e}")

    try:
        asyncio.create_task(xmint_pool.initialize())
        logging.warning("✅ S2 pool background init started")
    except Exception as e:
        logging.error(f"S2 pool init error: {e}")

    logging.warning("✅ Bot started - Dual-panel system active")

async def post_shutdown(application):
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

async def error_handler(update, context):
    error_msg = str(context.error).lower()
    if any(x in error_msg for x in ["message is not modified", "bad request", "message to edit not found"]):
        return
    logging.error(f"Exception: {context.error}")

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
    app.add_handler(CommandHandler("admin", cmd_admin))
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_menu_restore), group=0)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message), group=1)

    # ✅ প্রতি 60 সেকেন্ডে Console থেকে Live Facebook SMS post করো
    app.job_queue.run_repeating(job_post_live_sms, interval=60, first=60)

    print("✅ Bot is running...")
    app.run_polling(drop_pending_updates=True, timeout=30)
