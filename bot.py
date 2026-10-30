import os, re, json, hmac, hashlib, time, random, sqlite3, asyncio
from urllib.parse import parse_qsl
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

# Giá trị mặc định ghi thẳng trong code; nếu có đặt biến môi trường trên Render thì biến đó được ưu tiên
TOKEN = os.environ.get("BOT_TOKEN", "9294891883:AAHsv-TTxyop9p_nCtqPEoPuaP3NXoo0bAk")
URL = os.environ.get("MINIAPP_URL", "https://anbuoi28.onrender.com")  # link công khai của chính server này
ADMINS = {int(x) for x in os.environ.get("ADMIN_IDS", "7884394252").split(",") if x.strip()}
START = int(os.environ.get("START_BAL", "0"))  # điểm ảo tặng người mới
BET_SEC, COVER_SEC, ODDS = 60, 15, 1.97  # hết giờ mở bát là sang phiên mới ngay
JP_RATE = 0.0             # 0% = không bao giờ tự nổ; chỉ nổ khi admin ép (/ep hu hoặc /ep 1 1 1, /ep 6 6 6)
JP_MIN, JP_MAX = 10, 12   # mỗi người trúng hũ nhận x10 đến x12 tiền cược của mình
HERE = os.path.dirname(os.path.abspath(__file__))

db = sqlite3.connect(os.environ.get("DB_PATH", os.path.join(HERE, "taixiu.db")), check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
create table if not exists users(uid integer primary key, name text, bal integer default 0);
create table if not exists bets(rid integer, uid integer, side text, amt integer);
create table if not exists rounds(id integer primary key, d1 integer, d2 integer, d3 integer);
create table if not exists kv(k text primary key, v text);
""")
G = {"id": 0, "phase": "bet", "end": 0.0, "dice": None, "last": None, "force": None, "jp": None}


def ensure(uid, name="?"):
    db.execute("insert or ignore into users(uid,name,bal) values(?,?,?)", (uid, name, START))
    db.commit()


# ---------- Hũ jackpot ----------
def get_pot():
    r = db.execute("select v from kv where k='pot'").fetchone()
    return int(r[0]) if r else 0


def set_pot(v):
    db.execute("insert or replace into kv(k,v) values('pot',?)", (str(max(0, int(v))),))
    db.commit()


def is_jp_dice(d):
    """Nổ hũ khi ra 3 con 1 hoặc 3 con 6."""
    return d[0] == d[1] == d[2] and d[0] in (1, 6)


def jp_side(d):
    """3 con 1 (tổng 3) = cửa Xỉu, 3 con 6 (tổng 18) = cửa Tài."""
    return "xiu" if d[0] == 1 else "tai"


def jp_sides(rid):
    return [s for s in ("xiu", "tai") if db.execute("select 1 from bets where rid=? and side=?", (rid, s)).fetchone()]


def jp_plan(rid, d):
    """Tính trước tiền nổ hũ của từng người (cược càng nhiều nhận càng nhiều, chỉ người đặt đúng cửa)."""
    if not is_jp_dice(d):
        return None
    pot, side = get_pot(), jp_side(d)
    rows = db.execute(
        "select b.uid uid, sum(b.amt) a, u.name name from bets b left join users u on u.uid=b.uid "
        "where b.rid=? and b.side=? group by b.uid", (rid, side)).fetchall()
    if pot <= 0 or not rows:
        return None
    raw = {r["uid"]: int(r["a"] * random.uniform(JP_MIN, JP_MAX)) for r in rows}
    tot = sum(raw.values())
    if tot > pot:  # hũ không đủ thì chia theo tỉ lệ
        raw = {u: int(a * pot / tot) for u, a in raw.items()}
    pay = {u: a for u, a in raw.items() if a > 0}
    if not pay:
        return None
    return {"id": rid, "dice": d, "side": side, "pay": pay, "total": sum(pay.values()),
            "names": {r["uid"]: (r["name"] or "?") for r in rows}, "bets": {r["uid"]: r["a"] for r in rows}}


def jp_view(p, uid):
    top = sorted(p["pay"].items(), key=lambda x: -x[1])[:5]
    return {"id": p["id"], "side": p["side"], "total": p["total"], "n": len(p["pay"]),
            "me": p["pay"].get(uid, 0),
            "top": [{"name": p["names"][u], "bet": p["bets"][u], "amt": a, "me": u == uid} for u, a in top]}


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


def net_of(my, w):
    """Lãi/lỗ của một người chơi: tiền thắng trả về trừ tổng tiền cược."""
    return (int(my.get(w, 0) * ODDS) if w else 0) - sum(my.values())


def round_net(my, d, plan, uid):
    if plan:  # phiên nổ hũ: tiền hũ trừ tổng tiền cược
        return plan["pay"].get(uid, 0) - sum(my.values())
    return net_of(my, win_side(d))


def settle(rid, d, plan=None):
    db.execute("insert into rounds values(?,?,?,?)", (rid, *d))
    if plan:
        for uid, amt in plan["pay"].items():
            db.execute("update users set bal=bal+? where uid=?", (amt, uid))
        set_pot(get_pot() - plan["total"])
    else:
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


def roll(rid):
    """Tung 3 xúc xắc; nếu admin đã /ep thì dùng kết quả ép (chỉ áp dụng 1 phiên).
    Nổ hũ (3 con 1 / 3 con 6) mặc định KHÔNG BAO GIỜ tự ra (JP_RATE = 0), chỉ nổ khi admin ép."""
    f, G["force"] = G["force"], None
    if isinstance(f, list):
        return f
    if f == "hu":  # admin ép nổ hũ: ra 3 con 1 / 3 con 6 theo cửa đang có người cược
        sides = jp_sides(rid)
        if sides:
            return [1, 1, 1] if random.choice(sides) == "xiu" else [6, 6, 6]
        f = None
    if f == "bao":
        return [random.randint(2, 5)] * 3  # bão thường, không nổ hũ
    sides = jp_sides(rid) if get_pot() > 0 else []
    if f is None and sides and random.random() < JP_RATE:
        return [1, 1, 1] if random.choice(sides) == "xiu" else [6, 6, 6]
    while True:
        d = [random.randint(1, 6) for _ in range(3)]
        if is_jp_dice(d):
            continue  # 3 con 1 / 3 con 6 chỉ ra qua nhánh nổ hũ ở trên
        if f is None or win_side(d) == f:
            return d


async def game_loop():
    while True:
        rid = db.execute("select coalesce(max(id),0)+1 from rounds").fetchone()[0]
        G.update(id=rid, phase="bet", end=time.time() + BET_SEC, dice=None)
        await asyncio.sleep(BET_SEC)
        d = roll(rid)
        G["jp"] = jp_plan(rid, d)  # cược đã đóng nên tính trước được tiền hũ
        G.update(phase="cover", end=time.time() + COVER_SEC, dice=d)  # úp bát
        await asyncio.sleep(COVER_SEC)
        settle(rid, d, G["jp"])
        # Không chờ nữa: vòng lặp sang phiên mới ngay, kết quả phiên cũ gửi kèm trong "last"
        G["last"] = {"id": rid, "dice": d, "t": time.time()}


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
    jp = G["jp"]
    plan = jp if jp and jp["id"] == G["id"] else None
    out = {
        "id": G["id"], "phase": G["phase"], "left": max(0, G["end"] - time.time()),
        "dice": d, "my": my, "tot": {s: tot(s) for s in ("tai", "xiu")},
        "bal": db.execute("select bal from users where uid=?", (uid,)).fetchone()[0],
        "pot": get_pot(),
        "hist": [[r[0], r[1], r[2]] for r in db.execute("select d1,d2,d3 from rounds order by id desc limit 14")],
    }
    if d:
        out["win"] = plan["side"] if plan else win_side(d)
        out["net"] = round_net(my, d, plan, uid)  # để client chớp kết quả ngay khi kéo bát
        if plan:
            out["jp"] = jp_view(plan, uid)
    last = G["last"]
    if last:
        lmy = {r["side"]: r["a"] for r in db.execute(
            "select side,sum(amt) a from bets where rid=? and uid=? group by side", (last["id"], uid))}
        lplan = jp if jp and jp["id"] == last["id"] else None
        out["last"] = {"id": last["id"], "dice": last["dice"],
                       "win": lplan["side"] if lplan else win_side(last["dice"]), "my": lmy,
                       "net": round_net(lmy, last["dice"], lplan, uid), "ago": time.time() - last["t"],
                       "jp": jp_view(lplan, uid) if lplan else None}
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


def parse_amt(s):
    """Chấp nhận 5000000 | 5,000,000 | 5.000.000 | 5m | 500k | 1.5m"""
    s = s.strip().lower().replace(",", "").replace("_", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    mul = 1
    if s.endswith("k"):
        mul, s = 1000, s[:-1]
    elif s.endswith("m"):
        mul, s = 1000000, s[:-1]
    return int(float(s) * mul)


async def hu(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Admin: /hu <số tiền> để đặt số điểm trong hũ jackpot; /hu để xem hũ hiện tại."""
    if u.effective_user.id not in ADMINS:
        return
    if not c.args:
        return await u.message.reply_text(
            f"Hũ jackpot hiện có: {get_pot():,} điểm ảo\nCú pháp: /hu <số tiền> (vd: /hu 5000000, /hu 5m)")
    try:
        v = parse_amt(c.args[0])
        if v < 0:
            raise ValueError
    except Exception:
        return await u.message.reply_text("Cú pháp: /hu <số tiền>  (vd: /hu 5000000, /hu 5m, /hu 500k)")
    set_pot(v)
    await u.message.reply_text(f"Đã đặt hũ jackpot: {v:,} điểm ảo")


async def ep(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Admin: /ep 1 4 3 (ép 3 xúc xắc) | /ep t (Tài) | /ep x (Xỉu) | /ep b (Bão) | /ep hu (nổ hũ) | /ep huy (bỏ ép)."""
    if u.effective_user.id not in ADMINS:
        return
    a = [x.lower() for x in (c.args or [])]
    nxt = G["id"] if G["phase"] == "bet" else G["id"] + 1  # phiên sẽ bị ép
    if len(a) == 3 and all(x in list("123456") for x in a):
        G["force"] = [int(x) for x in a]
        txt = f"Đã ép phiên #{nxt}: {' - '.join(a)} = {sum(map(int, a))}"
        if len(set(a)) == 1 and a[0] in "16":
            txt += "\n(3 con 1 / 3 con 6 = nổ hũ)" + ("" if get_pot() > 0 else "\n⚠ Hũ đang 0, hãy /hu <số tiền> trước, nếu không chỉ tính là bão.")
    elif len(a) == 1 and a[0] in ("t", "tai", "x", "xiu", "b", "bao", "hu", "nohu"):
        G["force"] = {"t": "tai", "x": "xiu", "b": "bao", "nohu": "hu"}.get(a[0], a[0])
        txt = f"Đã ép phiên #{nxt} về {'NỔ HŨ' if G['force'] == 'hu' else G['force'].upper()}"
    elif a and a[0] in ("huy", "off", "0"):
        G["force"] = None
        txt = "Đã bỏ ép."
    else:
        txt = "Cú pháp: /ep 1 4 3 | /ep t | /ep x | /ep b | /ep hu (nổ hũ) | /ep huy"
    await u.message.reply_text(txt)


async def main():
    refund_unsettled()
    app = Application.builder().token(TOKEN).build()
    for n, h in (("start", start), ("id", myid), ("sodu", sodu), ("nap", nap), ("ep", ep), ("hu", hu)):
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
