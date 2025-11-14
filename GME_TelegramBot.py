# GME PredictorBot – versione stabile con fallback JobQueue
# Python 3.11 – Librerie: python-telegram-bot, sqlite3, requests, flask, dotenv, asyncio

import os
import logging
import sqlite3
import requests
import random
import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ApplicationBuilder,
)

# ---------------------- CONFIG ----------------------
load_dotenv()
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

START_TIME = time(0, 0)
CUTOFF_TIME = time(15, 30)
MARKET_CLOSE_TIME = time(22, 10)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_KEY = os.getenv("FINNHUB_API_KEY")
GME_TICKER = "GME"

GROUP_TOPIC_CHAT_ID = -1001425180088
ITALY_TZ = ZoneInfo("Europe/Rome")
ADMIN_CHAT_ID = 68001743

CHIUSURE_MERCATO = {
    "2025-01-01", "2025-04-18", "2025-05-26", "2025-06-19",
    "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25", "2025-12-26"
}

# ---------------------- FLASK (UNICO) ----------------------
app = Flask(__name__)

@app.route("/")
def home():
    return {"status": "up", "timestamp": datetime.now().timestamp()}, 200

@app.route("/health")
def health():
    return "ok", 200

def start_keep_alive_server():
    port = int(os.environ.get("PORT", "8080"))  # su Render è 8080
    import threading
    t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port), daemon=True)
    t.start()
    logging.info(f"Keep-alive server started on port {port}")


async def keep_alive_ping():
    url = os.getenv("KEEPALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        logging.info("Keep-alive ping disabilitato: nessuna URL configurata.")
        return

    logging.info(f"Keep-alive ping attivo verso {url}")
    while True:
        try:
            await asyncio.to_thread(requests.get, url, timeout=5)
            logging.debug("Keep-alive ping inviato con successo")
        except Exception as exc:
            logging.warning(f"Errore durante il keep-alive ping: {exc}")
        await asyncio.sleep(180)

# ---------------------- DATABASE ----------------------
DB_FILE = "predictions.db"
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
c = conn.cursor()
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA busy_timeout=5000;")

c.execute("""
    CREATE TABLE IF NOT EXISTS predictions (
        user_id INTEGER,
        username TEXT,
        prediction REAL,
        date TEXT,
        UNIQUE(user_id, date)
    )
""")
c.execute("""
    CREATE TABLE IF NOT EXISTS balances (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0
    )
""")
c.execute("""
    CREATE TABLE IF NOT EXISTS winners (
        date TEXT PRIMARY KEY,
        result TEXT
    )
""")
c.execute("""
    CREATE TABLE IF NOT EXISTS bans (
        user_id INTEGER PRIMARY KEY,
        ban_until TEXT
    )
""")
c.execute("""
    CREATE TABLE IF NOT EXISTS weekly_pot (
        week_start TEXT PRIMARY KEY,
        amount REAL DEFAULT 0
    )
""")
conn.commit()

# ---------------------- DATI GME ----------------------
def get_gme_closing_percentage():
    url = f"https://finnhub.io/api/v1/quote?symbol={GME_TICKER}&token={API_KEY}"
    try:
        data = requests.get(url, timeout=10).json()
        pc, cprice = data.get("pc"), data.get("c")
        if pc is None or cprice is None:
            return None
        return round(((cprice - pc) / pc) * 100, 2)
    except Exception as e:
        logging.error(f"Errore Finnhub: {e}")
        return None

def get_gme_closing_percentage_yesterday():
    try:
        data = requests.get(
            f"https://finnhub.io/api/v1/quote?symbol={GME_TICKER}&token={API_KEY}",
            timeout=10
        ).json()
        pc, cprice = data.get("pc"), data.get("c")
        if pc is None or cprice is None:
            return None
        return round(((pc - cprice) / cprice) * 100, 2)
    except Exception as e:
        logging.error(f"Errore Finnhub (ieri): {e}")
        return None

# ---------------------- HANDLERS ----------------------
async def bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.from_user.username
    user_id = update.message.from_user.id
    now = datetime.now(ITALY_TZ)
    today_date = now.strftime("%Y-%m-%d")
    weekday = now.weekday()

    c.execute("SELECT ban_until FROM bans WHERE user_id = ?", (user_id,))
    ban_record = c.fetchone()
    if ban_record:
        ban_until = datetime.strptime(ban_record[0], "%Y-%m-%d").date()
        if now.date() <= ban_until:
            await update.message.reply_text(f"🚫 Sei bannato fino al {ban_until.strftime('%d/%m/%Y')}.")
            return

    if not username:
        await update.message.reply_text("⚠️ Imposta un username Telegram per scommettere.")
        return

    if weekday in [5, 6] or today_date in CHIUSURE_MERCATO:
        await update.message.reply_text(f"❌ Il mercato è chiuso oggi ({today_date}).")
        return

    if not (START_TIME <= now.time() <= CUTOFF_TIME):
        cutoff_str = f"{CUTOFF_TIME.hour:02d}:{CUTOFF_TIME.minute:02d}"
        await update.message.reply_text(f"❌ Previsioni chiuse. Finestra: 00:00–{cutoff_str}.")
        return

    try:
        prediction = round(float(context.args[0]), 2)
    except (IndexError, ValueError):
        await update.message.reply_text("❗ Usa: /bet 2.5")
        return

    c.execute("SELECT 1 FROM predictions WHERE user_id = ? AND date = ?", (user_id, today_date))
    if c.fetchone():
        try:
            await update.message.delete()
        except Exception as e:
            logging.error(f"Errore delete: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            message_thread_id=getattr(update.message, "message_thread_id", None),
            text="⚠️ Hai già scommesso oggi! Non puoi cambiarla."
        )
        return

    c.execute("SELECT 1 FROM predictions WHERE prediction = ? AND date = ?", (prediction, today_date))
    if c.fetchone():
        try:
            await update.message.delete()
        except Exception as e:
            logging.error(f"Errore delete: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            message_thread_id=getattr(update.message, "message_thread_id", None),
            text="⚠️ Valore già preso da un altro utente. Scegline uno diverso."
        )
        return

    c.execute(
        "INSERT INTO predictions (user_id, username, prediction, date) VALUES (?, ?, ?, ?)",
        (user_id, username, prediction, today_date)
    )
    conn.commit()

    try:
        await update.message.delete()
    except Exception as e:
        logging.error(f"Errore delete: {e}")

    confirmation = (
        f"✅ <b>Scommessa registrata!</b>\n"
        f"@{username} ha scommesso per oggi ({today_date})."
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=confirmation,
        parse_mode=ParseMode.HTML,
        message_thread_id=getattr(update.message, "message_thread_id", None)
    )

    admin_msg = (
        f"📢 Nuova scommessa registrata:\n"
        f"Utente: @{username} (ID: <code>{user_id}</code>)\n"
        f"Valore scommesso: {prediction}%\n"
        f"Data: {today_date}"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Errore invio admin: {e}")

async def bilancio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.from_user.username
    if not username:
        await update.message.reply_text("⚠️ Non hai un username Telegram.")
        return
    c.execute("SELECT balance FROM balances WHERE username = ?", (username,))
    row = c.fetchone()
    if row is None:
        c.execute(
            "INSERT INTO balances (user_id, username, balance) VALUES (?, ?, ?)",
            (update.message.from_user.id, username, 0.0)
        )
        conn.commit()
        balance = 0.0
    else:
        balance = round(row[0], 2)
    await update.message.reply_text(f"💰 Il tuo saldo attuale è: {balance}€")

async def classifica(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        c.execute("""
            SELECT b.user_id, MAX(b.username) as username, ROUND(SUM(b.balance), 2) as total_balance
            FROM balances b
            GROUP BY b.user_id
            ORDER BY total_balance DESC
        """)
        rankings = c.fetchall()
        if not rankings:
            await update.message.reply_text("📭 Nessun bilancio disponibile.")
            return
        msg = "<b>🏆 Classifica completa:</b>\n\n"
        for i, (_, uname, bal) in enumerate(rankings, start=1):
            msg += f"<b>{i}.</b> @{uname}: <b>{bal}€</b>\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Errore classifica: {e}")
        await update.message.reply_text("❌ Errore nel recupero della classifica.")

async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Il chat_id di questa chat è: {update.effective_chat.id}")

async def scommesse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(ITALY_TZ)
    today = now.strftime("%Y-%m-%d")
    current_time = now.time()
    c.execute("SELECT username, prediction FROM predictions WHERE date = ?", (today,))
    bets = c.fetchall()
    if not bets:
        await update.message.reply_text("🎲 Nessuna scommessa registrata per oggi.")
        return
    msg = "🎲 <b>Scommesse di oggi:</b>\n\n"
    if current_time >= CUTOFF_TIME:
        bets = sorted(bets, key=lambda x: x[1])
        for uname, pred in bets:
            msg += f"@{uname}: {pred:.2f}%\n"
    else:
        for uname, _ in bets:
            msg += f"@{uname}\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def tesoretto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(ITALY_TZ).date()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    c.execute("SELECT SUM(amount) FROM weekly_pot WHERE week_start = ?", (week_start,))
    total = c.fetchone()[0] or 0.0
    await update.message.reply_text(f"💰 <b>Tesoretto attuale:</b> {total:.2f}€", parse_mode=ParseMode.HTML)

async def vincitore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(ITALY_TZ)
    date_offset = -1 if (context.args and context.args[0] == "yesterday") else 0
    target_date = (now + timedelta(days=date_offset)).strftime("%Y-%m-%d")
    date_obj = datetime.strptime(target_date, "%Y-%m-%d")

    if date_offset == 0 and now.time() < MARKET_CLOSE_TIME:
        await update.message.reply_text("⏳ Il mercato è ancora aperto! Prova dopo le 22:10.")
        return
    if target_date in CHIUSURE_MERCATO:
        await update.message.reply_text(f"❌ Il mercato era chiuso il {target_date}.")
        return

    c.execute("SELECT result FROM winners WHERE date = ?", (target_date,))
    row = c.fetchone()
    if row:
        await update.message.reply_text(row[0], parse_mode=ParseMode.HTML)
        return

    c.execute("SELECT user_id, username, prediction FROM predictions WHERE date = ?", (target_date,))
    predictions = c.fetchall()
    if not predictions:
        await update.message.reply_text(f"Nessuna previsione per il {target_date}.")
        return

    closing_percentage = await asyncio.to_thread(get_gme_closing_percentage)
    if closing_percentage is None:
        await update.message.reply_text("⚠️ Dato GME non disponibile, riprova più tardi.")
        return

    players = [(uid, uname, pred, round(abs(pred - closing_percentage), 2)) for uid, uname, pred in predictions]
    players.sort(key=lambda x: x[3])
    num_players = len(players)

    c.execute("SELECT user_id, username FROM balances")
    all_users = dict(c.fetchall())
    bettors_today = {p[0] for p in players}
    non_bettors = {uid: uname for uid, uname in all_users.items() if uid not in bettors_today}

    week_start = (date_obj - timedelta(days=date_obj.weekday())).strftime("%Y-%m-%d")
    penalty_total = 10 * len(non_bettors)
    for uid in non_bettors:
        c.execute("UPDATE balances SET balance = ROUND(balance - 10, 2) WHERE user_id = ?", (uid,))
    c.execute("""
        INSERT INTO weekly_pot (week_start, amount)
        VALUES (?, ?)
        ON CONFLICT(week_start) DO UPDATE SET amount = ROUND(amount + ?, 2)
    """, (week_start, penalty_total, penalty_total))

    c.execute("SELECT amount FROM weekly_pot WHERE week_start = ?", (week_start,))
    row = c.fetchone()
    tesoretto_val = round(row[0], 2) if row else 0.0

    perfect = next((p for p in players if p[3] == 0.0), None)
    if perfect:
        middle = num_players // 2
        variable_pool = 0.0
        losers_info = []
        for i in range(middle):
            diff_top = players[i][3]
            diff_bottom = players[-(i + 1)][3]
            loss = abs(round((diff_bottom - diff_top) * 5, 2))
            variable_pool += loss
            losers_info.append((players[-(i + 1)][0], players[-(i + 1)][1], loss))

        fixed_penalties = [(-1, -150), (-2, -100), (-3, -50)]
        fixed_losses = []
        for idx, pen in fixed_penalties:
            uid, uname, *_ = players[idx]
            fixed_losses.append((uid, uname, pen))

        pg_id, pg_uname, _, _ = perfect
        total_prize = round(300 + variable_pool, 2)
        bonus_tesoretto = 0.0

        if date_obj.weekday() == 4 and target_date not in CHIUSURE_MERCATO and tesoretto_val > 0:
            bonus_tesoretto = tesoretto_val
            total_prize = round(total_prize + tesoretto_val, 2)
            c.execute("UPDATE balances SET balance = ROUND(balance + ?, 2) WHERE user_id = ?", (tesoretto_val, pg_id))
            c.execute("DELETE FROM weekly_pot WHERE week_start = ?", (week_start,))

        c.execute("""
            INSERT INTO balances (user_id, username, balance)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = ROUND(balance + ?, 2),
                username = excluded.username
        """, (pg_id, pg_uname, total_prize, total_prize))

        for loser_id, loser_uname, loss in losers_info:
            c.execute("""
                INSERT INTO balances (user_id, username, balance)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    balance = ROUND(balance - ?, 2),
                    username = excluded.username
            """, (loser_id, loser_uname, -loss, loss))

        for uid, uname, fixed_penalty in fixed_losses:
            c.execute("""
                INSERT INTO balances (user_id, username, balance)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    balance = ROUND(balance + ?, 2),
                    username = excluded.username
            """, (uid, uname, fixed_penalty, fixed_penalty))

        conn.commit()

        msg = f"<b>📈 Variazione GME ({target_date}): {closing_percentage}%</b>\n"
        msg += f"<i>Tesoretto attuale: {tesoretto_val}€</i>\n\n"
        msg += f"🎯 <b>Perfect guess!</b> @{pg_uname} ha indovinato esattamente.\n"
        msg += f"🏅 Guadagna: 300€ + {round(variable_pool, 2)}€"
        if bonus_tesoretto > 0:
            msg += f" + {bonus_tesoretto}€ (tesoretto)"
        msg += f" = <b>{round(total_prize, 2)}€</b>\n\n"

        msg += "<b>📊 Partecipanti:</b>\n"
        for uid, uname, pred, diff in players:
            label = "🏆" if uid == pg_id else "•"
            msg += f"{label} @{uname}: {pred:.2f}% (Diff: {diff:.2f}%)\n"

        msg += "\n<b>❌ Perdenti (variabile):</b>\n"
        for _, uname, loss in losers_info:
            msg += f"• @{uname}: -{loss}€\n"

        msg += "\n<b>💀 Penalità fisse:</b>\n"
        for _, uname, fixed in fixed_losses:
            msg += f"• @{uname}: {fixed}€\n"

        if non_bettors:
            msg += "\n<b>😴 Non hanno scommesso e perdono 10€:</b>\n"
            for uname in non_bettors.values():
                msg += f"• @{uname}\n"

        c.execute("INSERT INTO winners (date, result) VALUES (?, ?)", (target_date, msg))
        conn.commit()
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    rewards = {1: 150, 2: 100, 3: 50}
    penalties = {-1: -150, -2: -100, -3: -50}
    risk_multiplier = 5

    changes = {uid: [uname, 0.0, 0.0] for uid, uname, _, _ in players}
    for i in range(3):
        changes[players[i][0]][1] += rewards[i + 1]
        changes[players[-(i + 1)][0]][1] += penalties[-(i + 1)]

    for i in range(num_players // 2):
        top = players[i]
        bottom = players[-(i + 1)]
        delta = round((bottom[3] - top[3]) * risk_multiplier, 2)
        changes[top[0]][2] += delta
        changes[bottom[0]][2] -= delta

    if num_players % 2 == 1:
        mid_uid = players[num_players // 2][0]
        changes[mid_uid][1] = 0.0
        changes[mid_uid][2] = 0.0

    for uid, (uname, fisso, var) in changes.items():
        totale = round(fisso + var, 2)
        c.execute("""
            INSERT INTO balances (user_id, username, balance)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = ROUND(balance + ?, 2),
                username = excluded.username
        """, (uid, uname, totale, totale))

    c.execute("SELECT week_start, amount FROM weekly_pot ORDER BY week_start DESC LIMIT 1")
    row = c.fetchone()
    tesoretto_val = row[1] if row else 0
    tesoretto_week_start = row[0] if row else None

    conn.commit()

    msg = f"<b>📈 Variazione GME ({target_date}): {closing_percentage}%</b>\n"
    msg += f"<i>Tesoretto attuale: {tesoretto_val}€</i>\n\n"

    sorted_results = sorted(changes.items(), key=lambda item: -(item[1][1] + item[1][2]))
    winner_uid, (winner_username, winner_fisso, winner_var) = sorted_results[0]
    winner_tot = round(winner_fisso + winner_var, 2)

    for i, (uid, (uname, fisso, var)) in enumerate(sorted_results):
        pred = next(p for u, n, p, _ in players if u == uid)
        diff = round(abs(pred - closing_percentage), 2)
        total = round(fisso + var, 2)
        rank = i + 1
        label = "🏆" if rank <= 3 else "💀" if rank > num_players - 3 else "⚖️"
        msg += (
            f"{label} <b>{rank}°</b>: @{uname} → {pred:.2f}% "
            f"(Diff: {diff:.2f}%) | Fisso: {fisso}€, Variabile: {var}€, Totale: {total}€\n"
        )

    if non_bettors:
        msg += "\n<b>😴 Non hanno scommesso e perdono 10€:</b>\n"
        for uname in non_bettors.values():
            msg += f"• @{uname}\n"

    if date_obj.weekday() == 4 and target_date not in CHIUSURE_MERCATO and tesoretto_val > 0:
        c.execute("UPDATE balances SET balance = ROUND(balance + ?, 2) WHERE user_id = ?", (tesoretto_val, winner_uid))
        c.execute("DELETE FROM weekly_pot WHERE week_start = ?", (tesoretto_week_start,))
        total_final = round(winner_tot + tesoretto_val, 2)
        msg += (
            f"\n💰 Tesoretto settimanale: @{winner_username} riceve anche <b>{tesoretto_val}€</b> extra!\n"
            f"🤑 Guadagno complessivo del giorno: <b>{total_final}€</b>\n"
        )

    c.execute("INSERT INTO winners (date, result) VALUES (?, ?)", (target_date, msg))
    conn.commit()
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def istruzioni(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Ogni giorno puoi scommettere sulla variazione percentuale di <b>$GME</b>.\n\n"
        "<b>🕒 Orari</b>\n"
        "• Scommesse 00:00–15:30 (ora italiana)\n"
        "• Risultati dopo 22:10\n\n"
        "<b>💰 Punteggio</b>\n"
        "• 1°: +150€ • 2°: +100€ • 3°: +50€\n"
        "• Ultimi 3: -50€, -100€, -150€\n"
        "• Variabile: differenza * 5 contro l'opposto\n\n"
        "<b>🎯 Perfect guess</b> +300€ + parte variabile dei perdenti\n"
        "<b>😴 Inattivi</b> -10€ → tesoretto\n"
        "<b>💎 Tesoretto</b> al vincitore del venerdì\n\n"
        "<b>Comandi:</b> /bet, /vincitore [yesterday], /scommesse, /classifica, /bilancio, "
        "/tesoretto, /id, /bannati, /ban, /unban, /admin, /chatid, /testVincitore, /betTEST"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def registra_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.message.from_user
    await update.message.reply_text("✅ Ok! ID registrato.")
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=f"🆔 ID registrato: @{(u.username or 'Sconosciuto')} → {u.id}")
    except Exception as e:
        logging.error(f"Errore invio ID admin: {e}")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Solo l'admin può bannare.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("❗ Usa: /ban username giorni")
        return
    username = context.args[0].lstrip("@")
    try:
        giorni = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❗ Il numero di giorni deve essere intero.")
        return
    c.execute("SELECT user_id FROM balances WHERE username = ?", (username,))
    res = c.fetchone()
    if not res:
        await update.message.reply_text(f"⚠️ Nessun utente @{username}.")
        return
    user_id = res[0]
    ban_until = (datetime.now(ITALY_TZ).date() + timedelta(days=giorni)).strftime("%Y-%m-%d")
    c.execute("INSERT OR REPLACE INTO bans (user_id, ban_until) VALUES (?, ?)", (user_id, ban_until))
    conn.commit()
    await update.message.reply_text(f"✅ @{username} bannato fino al {ban_until}.")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Non hai i permessi.")
        return
    try:
        username = context.args[0].lstrip("@")
    except IndexError:
        await update.message.reply_text("⚠️ Usa: /unban username")
        return
    c.execute("SELECT user_id FROM balances WHERE username = ?", (username,))
    res = c.fetchone()
    if not res:
        await update.message.reply_text("❌ Utente non trovato.")
        return
    c.execute("DELETE FROM bans WHERE user_id = ?", (res[0],))
    conn.commit()
    await update.message.reply_text(f"✅ Ban rimosso per @{username}.")

async def bannati(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(ITALY_TZ).date()
    c.execute("SELECT user_id, ban_until FROM bans")
    results = c.fetchall()
    if not results:
        await update.message.reply_text("✅ Nessun utente è attualmente bannato.")
        return
    message = "<b>🚫 Utenti attualmente bannati:</b>\n\n"
    found = False
    for user_id, ban_until in results:
        ban_date = datetime.strptime(ban_until, "%Y-%m-%d").date()
        if today <= ban_date:
            c.execute("SELECT username FROM balances WHERE user_id = ?", (user_id,))
            r = c.fetchone()
            username = r[0] if r else f"ID {user_id}"
            giorni_rimanenti = (ban_date - today).days
            message += f"• @{username} — fino al {ban_date.strftime('%d/%m/%Y')} ({giorni_rimanenti} giorni rimanenti)\n"
            found = True
    if not found:
        message = "✅ Nessun utente è attualmente bannato."
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat = update.effective_chat
        admins = await context.bot.get_chat_administrators(chat.id)
        mentions = []
        for a in admins:
            u = a.user
            mentions.append(f"@{u.username}" if u.username else f"<i>{u.first_name or 'admin'}</i>")
        message = "🔧 <b>Amministratori della chat:</b>\n" + "\n".join(mentions)
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Errore admin list: {e}")
        await update.message.reply_text("❌ Errore nel recupero degli admin.")

async def testVincitore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    closing_percentage = round(random.uniform(-10, 10), 2)
    players = [f"Player{i}" for i in range(1, 17)]
    predictions = [(p, round(random.uniform(-10, 10), 2)) for p in players]
    predictions = [(u, pr, round(abs(pr - closing_percentage), 2)) for u, pr in predictions]
    predictions.sort(key=lambda x: x[2])
    num_players = len(predictions)
    rewards = {1: 150, 2: 100, 3: 50}
    penalties = {-1: -150, -2: -100, -3: -50}
    risk_multiplier = 5
    balance_changes = {u: [0, 0] for u, _, _ in predictions}
    for i in range(3):
        balance_changes[predictions[i][0]][0] += rewards[i + 1]
        balance_changes[predictions[-(i + 1)][0]][0] += penalties[-(i + 1)]
    middle_index = num_players // 2
    for i in range(middle_index):
        _, _, diff_top = predictions[i]
        _, _, diff_bottom = predictions[-(i + 1)]
        variable_bonus = (diff_bottom - diff_top) * risk_multiplier
        balance_changes[predictions[i][0]][1] += variable_bonus
        balance_changes[predictions[-(i + 1)][0]][1] -= variable_bonus
    if num_players % 2 == 1:
        balance_changes[predictions[middle_index][0]] = [0, 0]
    sorted_results = sorted(balance_changes.items(), key=lambda x: -(x[1][0] + x[1][1]))
    message = f"\n📈 Simulazione Test - Variazione GME: {closing_percentage}%\n\n"
    for i, (user, changes) in enumerate(sorted_results):
        prediction = next(pr for u, pr, _ in predictions if u == user)
        diff = round(abs(prediction - closing_percentage), 2)
        rank = i + 1
        fixed_part, variable_part = changes
        total = round(fixed_part + variable_part, 2)
        if rank <= 3:
            message += f"🏆 {rank}°: @{user} → {prediction}% (Diff {diff}%) Fisso {fixed_part}€, Var {variable_part:.2f}€, Tot {total}€\n"
        elif rank > num_players - 3:
            message += f"💀 {rank}°: @{user} → {prediction}% (Diff {diff}%) Fisso {fixed_part}€, Var {variable_part:.2f}€, Tot {total}€\n"
        else:
            message += f"⚖️ {rank}°: @{user} → {prediction}% (Diff {diff}%) Fisso {fixed_part}€, Var {variable_part:.2f}€, Tot {total}€\n"
    await update.message.reply_text(message)

async def testapi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("API funzionante!")

async def betTEST(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        _ = float(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("❗ Usa il comando così: /betTEST 1.4")
        return
    username = update.message.from_user.username
    today_date = datetime.now(ITALY_TZ).strftime("%Y-%m-%d")
    msg = f"✅ <b>Scommessa registrata!</b>\n@{username} ha scommesso per la giornata odierna ({today_date})."
    try:
        await update.message.delete()
    except Exception as e:
        logging.error(f"Errore nel cancellare il messaggio: {e}")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=msg,
        parse_mode=ParseMode.HTML,
        message_thread_id=getattr(update.message, "message_thread_id", None)
    )

# ---------------------- REMINDER ----------------------
REMINDER_OFFSETS = [
    (180, "Mancano 3 ore"),
    (120, "Mancano 2 ore"),
    (60,  "Manca 1 ora"),
    (10,  "Mancano 10 minuti"),
]

async def reminder_tick(context: ContextTypes.DEFAULT_TYPE):
    """Usato se JobQueue è disponibile."""
    now = datetime.now(ITALY_TZ)
    if now.weekday() in [5, 6]:
        return
    cutoff = now.replace(hour=CUTOFF_TIME.hour, minute=CUTOFF_TIME.minute, second=0, microsecond=0)
    if now > cutoff:
        tomorrow = now + timedelta(days=1)
        cutoff = tomorrow.replace(hour=CUTOFF_TIME.hour, minute=CUTOFF_TIME.minute, second=0, microsecond=0)
    target_date = cutoff.strftime("%Y-%m-%d")
    if target_date in CHIUSURE_MERCATO:
        return
    bot_state = context.application.bot_data
    sent_reminders = bot_state.setdefault("sent_reminders", {})
    already = sent_reminders.setdefault(target_date, set())
    for offset, label in REMINDER_OFFSETS:
        if offset in already:
            continue
        reminder_time = cutoff - timedelta(minutes=offset)
        if reminder_time <= now < reminder_time + timedelta(minutes=1):
            try:
                c.execute("SELECT COUNT(*) FROM predictions WHERE date = ?", (target_date,))
                count = c.fetchone()[0]
            except Exception as e:
                logging.error(f"Errore DB nel reminder: {e}")
                count = "non disponibile"
            cutoff_str = f"{CUTOFF_TIME.hour:02d}:{CUTOFF_TIME.minute:02d}"
            message = (
                f"🔔 {label}: il termine delle scommesse è alle {cutoff_str}.\n"
                f"Finora {count} scommesse per il {target_date}.\n"
                f"Usa /scommesse per scoprire chi non è una fighetta!"
            )
            try:
                await context.bot.send_message(chat_id=GROUP_TOPIC_CHAT_ID, text=message, parse_mode=ParseMode.HTML)
            except Exception as e:
                logging.error(f"Errore invio reminder: {e}")
            already.add(offset)

async def reminder_scheduler(application: Application):
    """Fallback automatico se JobQueue non è disponibile."""
    while True:
        try:
            now = datetime.now(ITALY_TZ)
            if now.weekday() in [5, 6]:
                await asyncio.sleep(60); continue
            cutoff = now.replace(hour=CUTOFF_TIME.hour, minute=CUTOFF_TIME.minute, second=0, microsecond=0)
            if now > cutoff:
                tomorrow = now + timedelta(days=1)
                cutoff = tomorrow.replace(hour=CUTOFF_TIME.hour, minute=CUTOFF_TIME.minute, second=0, microsecond=0)
            target_date = cutoff.strftime("%Y-%m-%d")
            if target_date in CHIUSURE_MERCATO:
                await asyncio.sleep(60); continue
            sent = application.bot_data.setdefault("sent_reminders", {}).setdefault(target_date, set())
            for offset, label in REMINDER_OFFSETS:
                if offset in sent:
                    continue
                reminder_time = cutoff - timedelta(minutes=offset)
                if reminder_time <= now < reminder_time + timedelta(minutes=1):
                    try:
                        c.execute("SELECT COUNT(*) FROM predictions WHERE date = ?", (target_date,))
                        count = c.fetchone()[0]
                    except Exception as e:
                        logging.error(f"Errore DB nel reminder: {e}")
                        count = "non disponibile"
                    cutoff_str = f"{CUTOFF_TIME.hour:02d}:{CUTOFF_TIME.minute:02d}"
                    message = (
                        f"🔔 {label}: il termine delle scommesse è alle {cutoff_str}.\n"
                        f"Finora {count} scommesse per il {target_date}.\n"
                        f"Usa /scommesse per scoprire chi non è una fighetta!"
                    )
                    try:
                        await application.bot.send_message(chat_id=GROUP_TOPIC_CHAT_ID, text=message, parse_mode=ParseMode.HTML)
                    except Exception as e:
                        logging.error(f"Errore invio reminder: {e}")
                    sent.add(offset)
            await asyncio.sleep(30)
        except Exception as e:
            logging.error(f"Reminder loop error: {e}")
            await asyncio.sleep(5)

async def _post_init(application: Application):
    """Eseguito dopo l'inizializzazione: attiva JobQueue se presente, altrimenti fallback."""
    asyncio.create_task(keep_alive_ping())
    jq = getattr(application, "job_queue", None)
    if jq is None:
        logging.info("JobQueue non disponibile: uso il fallback asyncio.")
        asyncio.create_task(reminder_scheduler(application))
    else:
        try:
            jq.run_repeating(reminder_tick, interval=30, first=0)
            logging.info("Reminder avviato con JobQueue.")
        except Exception as e:
            logging.error(f"Impossibile avviare JobQueue, passo al fallback. Dettagli: {e}")
            asyncio.create_task(reminder_scheduler(application))

# ---------------------- BOOTSTRAP ----------------------
def main():
    application: Application = ApplicationBuilder().token(TOKEN).post_init(_post_init).build()

    application.add_handler(CommandHandler("bet", bet))
    application.add_handler(CommandHandler("vincitore", vincitore))
    application.add_handler(CommandHandler("scommesse", scommesse))
    application.add_handler(CommandHandler("classifica", classifica))
    application.add_handler(CommandHandler("bilancio", bilancio))
    application.add_handler(CommandHandler("istruzioni", istruzioni))
    application.add_handler(CommandHandler("id", registra_id))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("unban", unban))
    application.add_handler(CommandHandler("bannati", bannati))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("testVincitore", testVincitore))
    application.add_handler(CommandHandler("testapi", testapi))
    application.add_handler(CommandHandler("chatid", chatid))
    application.add_handler(CommandHandler("tesoretto", tesoretto))
    application.add_handler(CommandHandler("betTEST", betTEST))

    logging.info("Bot avviato con successo!")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False
    )

if __name__ == "__main__":
    start_keep_alive_server()
    main()