import os, json, hmac, hashlib, time, random, sqlite3, asyncio
from urllib.parse import parse_qsl
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# ===== CẤU HÌNH: điền 3 dòng dưới (repo GitHub phải để Private) =====
BOT_TOKEN = "9294891883:AAHsv-TTxyop9p_nCtqPEoPuaP3NXoo0bAk"
MINIAPP_URL = "https://anbuoi28.onrender.com"
ADMIN_IDS_TEXT = "6685909406"  # nhiều admin thì cách nhau bằng dấu phẩy: 111,222
# ====================================================================
TOKEN = os.environ.get("BOT_TOKEN", BOT_TOKEN)
URL = os.environ.get("MINIAPP_URL", MINIAPP_URL)
ADMINS = {int(x) for x in os.environ.get("ADMIN_IDS", ADMIN_IDS_TEXT).split(",") if x.strip().isdigit()}
START = int(os.environ.get("START_BAL", "0"))  # điểm ảo tặng người mới
BET_SEC, COVER_SEC, RESULT_SEC, ODDS = 60, 15, 6, 1.97
HERE = os.path.dirname(os.path.abspath(__file__))

db = sqlite3.connect(os.environ.get("DB_PATH", os.path.join(HERE, "taixiu.db")), check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
create table if not exists users(uid integer primary key, name text, bal integer default 0);
create table if not exists bets(rid integer, uid integer, side text, amt integer);
create table if not exists rounds(id integer primary key, d1 integer, d2 integer, d3 integer);
""")
G = {"id": 0, "phase": "bet", "end": 0.0, "dice": None}


def ensure(uid, name="?"):
    db.execute("insert or ignore into users(uid,name,bal) values(?,?,?)", (uid, name, START))
    db.commit()


def auth(init):
    try:
        p = dict(parse_qsl(init, keep_blank_values=True))
        h = p.pop("hash", "")
        chk = "\n".join(f"{k}={v}" for k, v in sorted(p.items()))
        key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(key, chk.encode(), hashlib.sha256).hexdigest(), h):
            return None
        if time.time() - int(p.get("auth_date", 0)) > 86400:
            return None
        u = json.loads(p["user"])
        ensure(u["id"], u.get("first_name", "?"))
        return u["id"]
    except Exception:
        return None


def win_side(d):
    if d[0] == d[1] == d[2]:
        return None  # bão: nhà ăn
    return "tai" if sum(d) >= 11 else "xiu"


def settle(rid, d):
    db.execute("insert into rounds values(?,?,?,?)", (rid, *d))
    w = win_side(d)
    if w:
        for b in db.execute("select uid,amt from bets where rid=? and side=?", (rid, w)).fetchall():
            db.execute("update users set bal=bal+? where uid=?", (int(b["amt"] * ODDS), b["uid"]))
    db.commit()


def refund_unsettled():
    q = "from bets where rid not in (select id from rounds)"
    for b in db.execute("select uid,amt " + q).fetchall():
        db.execute("update users set bal=bal+? where uid=?", (b["amt"], b["uid"]))
    db.execute("delete " + q)
    db.commit()


async def game_loop():
    while True:
        rid = db.execute("select coalesce(max(id),0)+1 from rounds").fetchone()[0]
        G.update(id=rid, phase="bet", end=time.time() + BET_SEC, dice=None)
        await asyncio.sleep(BET_SEC)
        d = [random.randint(1, 6) for _ in range(3)]
        G.update(phase="cover", end=time.time() + COVER_SEC, dice=d)  # úp bát
        await asyncio.sleep(COVER_SEC)
        settle(rid, d)
        G.update(phase="result", end=time.time() + RESULT_SEC)
        await asyncio.sleep(RESULT_SEC)


def tot(side):
    r = db.execute("select coalesce(sum(amt),0),count(distinct uid) from bets where rid=? and side=?",
                   (G["id"], side)).fetchone()
    return [r[0], r[1]]


async def state(req):
    uid = auth(req.headers.get("X-Init", ""))
    if not uid:
        return web.json_response({"err": "Chưa xác thực"}, status=401)
    d = G["dice"] if G["phase"] != "bet" else None
    my = {r["side"]: r["a"] for r in db.execute(
        "select side,sum(amt) a from bets where rid=? and uid=? group by side", (G["id"], uid))}
    out = {
        "id": G["id"], "phase": G["phase"], "left": max(0, G["end"] - time.time()),
        "dice": d, "my": my, "tot": {s: tot(s) for s in ("tai", "xiu")},
        "bal": db.execute("select bal from users where uid=?", (uid,)).fetchone()[0],
        "hist": [[r[0], r[1], r[2]] for r in db.execute("select d1,d2,d3 from rounds order by id desc limit 14")],
    }
    if d:
        out["win"] = win_side(d)
        if G["phase"] == "result":
            out["net"] = (int(my.get(out["win"], 0) * ODDS) if out["win"] else 0) - sum(my.values())
    return web.json_response(out)


async def bet(req):
    uid = auth(req.headers.get("X-Init", ""))
    if not uid:
        return web.json_response({"err": "Chưa xác thực"}, status=401)
    j = await req.json()
    side, amt = j.get("side"), int(j.get("amt", 0))
    if G["phase"] != "bet" or time.time() >= G["end"]:
        return web.json_response({"err": "Đã hết giờ đặt cược"})
    if side not in ("tai", "xiu") or amt <= 0:
        return web.json_response({"err": "Cược không hợp lệ"})
    opp = "xiu" if side == "tai" else "tai"
    if db.execute("select 1 from bets where rid=? and uid=? and side=?", (G["id"], uid, opp)).fetchone():
        return web.json_response({"err": "Mỗi phiên chỉ cược một cửa"})
    bal = db.execute("select bal from users where uid=?", (uid,)).fetchone()[0]
    if amt > bal:
        return web.json_response({"err": "Không đủ điểm"})
    db.execute("update users set bal=bal-? where uid=?", (amt, uid))
    db.execute("insert into bets values(?,?,?,?)", (G["id"], uid, side, amt))
    db.commit()
    return web.json_response({"ok": 1})


# ---------- Lệnh bot ----------
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    ensure(u.effective_user.id, u.effective_user.first_name)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Vào bàn Tài Xỉu", web_app=WebAppInfo(url=URL))]])
    await u.message.reply_text(
        "Tài Xỉu giải trí: chỉ dùng điểm ảo, không nạp/rút tiền thật.\n"
        f"ID của bạn: {u.effective_user.id} (gửi cho admin để nhận điểm chơi).", reply_markup=kb)


async def myid(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(f"ID của bạn: {u.effective_user.id}")


async def sodu(u: Update, c: ContextTypes.DEFAULT_TYPE):
    ensure(u.effective_user.id, u.effective_user.first_name)
    b = db.execute("select bal from users where uid=?", (u.effective_user.id,)).fetchone()[0]
    await u.message.reply_text(f"Số dư: {b:,} điểm ảo")


async def nap(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.effective_user.id not in ADMINS:
        return
    try:
        uid, amt = int(c.args[0]), int(c.args[1])
    except Exception:
        return await u.message.reply_text("Cú pháp: /nap <id> <số điểm>")
    if not db.execute("select 1 from users where uid=?", (uid,)).fetchone():
        return await u.message.reply_text("ID này chưa từng /start bot.")
    db.execute("update users set bal=bal+? where uid=?", (amt, uid))
    db.commit()
    b = db.execute("select bal from users where uid=?", (uid,)).fetchone()[0]
    await u.message.reply_text(f"Đã cộng {amt:,} điểm ảo cho {uid}. Số dư: {b:,}")
    try:
        await c.bot.send_message(uid, f"Admin đã cộng {amt:,} điểm ảo. Số dư: {b:,}")
    except Exception:
        pass


async def main():
    refund_unsettled()
    app = Application.builder().token(TOKEN).build()
    for n, h in (("start", start), ("id", myid), ("sodu", sodu), ("nap", nap)):
        app.add_handler(CommandHandler(n, h))
    await app.initialize(); await app.start(); await app.updater.start_polling()

    w = web.Application()
    w.add_routes([
        web.get("/", lambda r: web.FileResponse(os.path.join(HERE, "index.html"))),
        web.get("/api/state", state), web.post("/api/bet", bet),
    ])
    run = web.AppRunner(w); await run.setup()
    await web.TCPSite(run, "0.0.0.0", int(os.environ.get("PORT", 8080))).start()
    asyncio.create_task(game_loop())
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
