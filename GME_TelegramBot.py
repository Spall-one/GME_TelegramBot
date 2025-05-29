import os
import logging
import sqlite3
import requests
import random
import time as time_module  # Rinominato per evitare conflitti
import threading
import asyncio
import nest_asyncio
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo  # Import per il fuso orario dinamico

nest_asyncio.apply()

# Configura logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Orari di apertura e chiusura delle scommesse
START_TIME = time(0, 0)           # Apertura a mezzanotte
CUTOFF_TIME = time(15, 30)         # Chiusura alle 15:30
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GME_TICKER = "GME"
API_KEY = os.getenv("FINNHUB_API_KEY")  # Finnhub API Key
GROUP_TOPIC_CHAT_ID = -1001425180088   # ID del topic (o chat) in cui inviare i reminder
CUTOFF_TIME_STR = f"{CUTOFF_TIME.hour:02d}:{CUTOFF_TIME.minute:02d}" 

# Imposta il fuso orario italiano in modo dinamico (gestisce automaticamente DST)
ITALY_TZ = ZoneInfo("Europe/Rome")
MARKET_CLOSE_TIME = time(22, 10)

ADMIN_CHAT_ID = 68001743  # Il tuo user ID

app = Flask(__name__)


@app.route('/')
def home():
    return "Bot is running!", 200

@app.route('/health')
def health():
    # Verifica stato del bot e ritorna 200 OK se è attivo
    return {"status": "up", "timestamp": time_module.time()}, 200

def run():
    port = int(os.environ.get("PORT", 8080))
    try:
        app.run(host="0.0.0.0", port=port)
    except Exception as e:
        logging.error(f"Keep-alive server error: {e}")
        time_module.sleep(5)  # Wait before retrying
        run()  # Restart server

def start_keep_alive_server():
    t = threading.Thread(target=run, daemon=True)
    t.start()
    logging.info("Keep-alive server started on port 8080")

# Avvia il server di keep-alive
start_keep_alive_server()


# Database setup
DB_FILE = "predictions.db"
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS predictions (
                user_id INTEGER,
                username TEXT,
                prediction REAL,
                date TEXT,
                UNIQUE(user_id, date)
            )''')
conn.commit()

c.execute('''CREATE TABLE IF NOT EXISTS balances (
                user_id INTEGER PRIMARY KEY,
                username TEXT UNIQUE,
                balance INTEGER DEFAULT 0
            )''')
c.execute('''CREATE TABLE IF NOT EXISTS winners (
                date TEXT PRIMARY KEY,
                result TEXT
            )''')
conn.commit()

c.execute('''CREATE TABLE IF NOT EXISTS bans (
                user_id INTEGER PRIMARY KEY,
                ban_until TEXT
            )''')
conn.commit()

# Lista di giorni in cui il mercato è chiuso (festività, chiusure programmate)
CHIUSURE_MERCATO = {
    "2025-01-01", "2025-07-04", "2025-12-25", "2025-12-26", "2025-11-27", "2025-04-18", "2025-05-26"
}

# Funzione per ottenere la variazione percentuale attuale di GME
def get_gme_closing_percentage():

    url = f"https://finnhub.io/api/v1/quote?symbol={GME_TICKER}&token={API_KEY}"

    try:
        response = requests.get(url)
        data = response.json()
        prev_close = data.get("pc", None)
        close = data.get("c", None)

        if prev_close is None or close is None:
            return None

        return round(((close - prev_close) / prev_close) * 100, 2)
    except Exception as e:
        logging.error(f"Errore nel recupero dei dati da Finnhub: {e}")
        return None

# Funzione per ottenere il valore della chiusura di mercato di ieri
def get_gme_closing_percentage_yesterday():

    from datetime import datetime, timedelta

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    url = f"https://finnhub.io/api/v1/quote?symbol={GME_TICKER}&token={API_KEY}"

    try:
        response = requests.get(url)
        data = response.json()
        prev_close = data.get("pc", None)  # Prezzo di chiusura di ieri
        close = data.get("c", None)  # Prezzo di chiusura attuale (oggi)

        if prev_close is None or close is None:
            return None

        return round(((prev_close - close) / close) * 100, 2)
    except Exception as e:
        logging.error(f"Errore nel recupero dei dati di ieri da Finnhub: {e}")
        return None



# Funzione per registrare una scommessa
async def bet(update: Update, context: CallbackContext):
    username = update.message.from_user.username
    user_id = update.message.from_user.id
    now = datetime.now(ITALY_TZ)
    today_date = now.strftime("%Y-%m-%d")
    weekday = now.weekday()  # 0 = Lunedì, 6 = Domenica

    # Controllo se l'utente è bannato
    c.execute("SELECT ban_until FROM bans WHERE user_id = ?", (user_id,))
    ban_record = c.fetchone()
    if ban_record:
        ban_until = datetime.strptime(ban_record[0], "%Y-%m-%d").date()
        today = datetime.now(ITALY_TZ).date()
        if today <= ban_until:
            await update.message.reply_text(f"🚫 Sei bannato fino al {ban_until.strftime('%d/%m/%Y')}. Non puoi scommettere.")
            return

    if not username:
        await update.message.reply_text("⚠️ Non posso registrare la tua scommessa perché non hai un username su Telegram! Impostane uno e riprova.")
        return

    if weekday in [5, 6] or today_date in CHIUSURE_MERCATO:
        await update.message.reply_text(f"❌ Il mercato è chiuso oggi ({today_date}). Le scommesse riapriranno il prossimo giorno utile.")
        return

    if now.time() < START_TIME or now.time() > CUTOFF_TIME:
        await update.message.reply_text(f"❌ Le previsioni sono chiuse. Puoi scommettere tra 00:00 e {CUTOFF_TIME_STR} nei giorni di mercato aperto.")
        return

    try:
        prediction = round(float(context.args[0]), 2)
    except (IndexError, ValueError):
        await update.message.reply_text("❗ Usa il comando così: /bet 2.5 (dove 2.5 è la tua previsione di variazione %)")
        return

    # Controllo scommessa doppia per lo stesso utente
    c.execute("SELECT prediction FROM predictions WHERE user_id = ? AND date = ?", (user_id, today_date))
    existing_bet = c.fetchone()
    if existing_bet:
        try:
            await update.message.delete()
        except Exception as e:
            logging.error(f"Errore nel cancellare il messaggio: {e}")
    
        # Questo messaggio deve uscire SEMPRE
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            message_thread_id=update.message.message_thread_id,
            text="⚠️ Hai già scommesso oggi! Non puoi cambiarla."
        )
        return

    # Controllo per scommesse identiche da utenti diversi
    c.execute("SELECT 1 FROM predictions WHERE prediction = ? AND date = ?", (prediction, today_date))
    same_prediction = c.fetchone()
    if same_prediction:
        try:
            await update.message.delete()
        except Exception as e:
            logging.error(f"Errore nel cancellare il messaggio: {e}")
    
        # Anche qui: deve SEMPRE apparire
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            message_thread_id=update.message.message_thread_id,
            text="⚠️ Questo valore è già stato scommesso da un altro utente! Prova con un valore diverso."
         )
        return

    # Salva la scommessa nel database
    c.execute("INSERT INTO predictions (user_id, username, prediction, date) VALUES (?, ?, ?, ?)",
              (user_id, username, prediction, today_date))
    conn.commit()

    # Messaggio di conferma per il gruppo (senza mostrare il valore)
    confirmation_message = (
        f"✅ <b>Scommessa registrata!</b>\n"
        f"@{username} ha scommesso per la giornata odierna ({today_date})."
    )
    try:
        await update.message.delete()
    except Exception as e:
        logging.error(f"Errore nel cancellare il messaggio: {e}")
    thread_id = getattr(update.message, "message_thread_id", None)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=confirmation_message,
        parse_mode="HTML",
        message_thread_id=thread_id
    )

    # Invia i dettagli completi della scommessa in modo privato all'amministratore
    admin_message = (
        f"📢 Nuova scommessa registrata:\n"
        f"Utente: @{username}\n"
        f"Valore scommesso: <b>{prediction}%</b>\n"
        f"Data: {today_date}"
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Errore nell'invio del messaggio all'amministratore: {e}")


# Funzione per mostrare il bilancio di un utente
async def bilancio(update: Update, context: CallbackContext):
    username = update.message.from_user.username

    logging.info(f"Comando /bilancio richiesto da: @{username}")

    if not username:
        await update.message.reply_text("⚠️ Non posso trovare il tuo bilancio perché non hai un username su Telegram! Impostane uno e riprova.")
        return

    c.execute("SELECT balance FROM balances WHERE username = ?", (username,))
    result = c.fetchone()

    if result is None:
        balance = 0.00
        logging.info(f"@{username} non presente in balances, aggiunto con saldo 0€.")
        c.execute("INSERT INTO balances (user_id, username, balance) VALUES (?, ?, ?)", (update.message.from_user.id, username, balance))
        conn.commit()
    else:
        balance = round(result[0], 2)  # Arrotondiamo a due decimali
        logging.info(f"Bilancio di @{username}: {balance}€")

    await update.message.reply_text(f"💰 Il tuo saldo attuale è: {balance}€")

# Funzione per mostrare la classifica completa
async def classifica(update: Update, context: CallbackContext):
    # Recupera e arrotonda i bilanci a due decimali
    c.execute("SELECT username, ROUND(balance, 2) as balance FROM balances ORDER BY balance DESC")
    rankings = c.fetchall()

    # Costruisci il messaggio con HTML
    message = "<b>🏆 Classifica completa:</b>\n\n"
    for i, (username, balance) in enumerate(rankings, start=1):
        message += f"<b>{i}.</b> @{username}: <b>{balance}€</b>\n"

    # Invia il messaggio con parse_mode HTML
    await update.message.reply_text(message, parse_mode="HTML")



async def chatid(update: Update, context: CallbackContext):
    await update.message.reply_text(f"Il chat_id di questa chat è: {update.effective_chat.id}")



# Funzione per mostrare le scommesse del giorno
async def scommesse(update: Update, context: CallbackContext):
    now = datetime.now(ITALY_TZ)
    today_date = now.strftime("%Y-%m-%d")
    c.execute("SELECT username, prediction FROM predictions WHERE date = ?", (today_date,))
    bets = c.fetchall()

    if not bets:
        await update.message.reply_text("📭 Nessuna scommessa registrata per oggi.")
        return

    # Se sono prima delle 15:30, mostra solo gli username; dopo le 15:30 mostra anche il valore della scommessa.
    message = "🎲 <b>Scommesse di oggi:</b>\n\n"
    if now.time() < CUTOFF_TIME:
        for username, _ in bets:
            message += f"@{username}\n"
    else:
        for username, prediction in bets:
            message += f"@{username}: <b>{prediction}%</b>\n"

    await update.message.reply_text(message, parse_mode="HTML")



from telegram.constants import ParseMode

async def vincitore(update: Update, context: CallbackContext):
    now = datetime.now(ITALY_TZ)
    date_offset = -1 if context.args and context.args[0] == "yesterday" else 0
    target_date = (now + timedelta(days=date_offset)).strftime("%Y-%m-%d")

    # Controllo orario
    if date_offset == 0 and now.time() < MARKET_CLOSE_TIME:
        await update.message.reply_text("⏳ Il mercato è ancora aperto! Puoi controllare il vincitore dopo le 22:10.")
        return

    if target_date in CHIUSURE_MERCATO:
        await update.message.reply_text(f"❌ Il mercato era chiuso il {target_date}. Nessuna vincita calcolata.")
        return

    # Se il vincitore è già stato calcolato, mostra il risultato
    c.execute("SELECT result FROM winners WHERE date = ?", (target_date,))
    existing_result = c.fetchone()
    if existing_result:
        await update.message.reply_text(existing_result[0], parse_mode="HTML")
        return  # ⛔ BLOCCA l'esecuzione: non ricalcolare balances!


    # Previsioni del giorno
    c.execute("SELECT user_id, username, prediction FROM predictions WHERE date = ?", (target_date,))
    predictions = c.fetchall()
    if not predictions:
        await update.message.reply_text(f"Nessuna previsione registrata per il {target_date}.")
        return

    closing_percentage = get_gme_closing_percentage()
    if closing_percentage is None:
        await update.message.reply_text("⚠️ La variazione percentuale di GME non è ancora disponibile. Riprova più tardi.")
        return

    players = [(uid, uname, pred, round(abs(pred - closing_percentage), 2)) for uid, uname, pred in predictions]
    players.sort(key=lambda x: x[3])
    num_players = len(players)

    # Controlla se esiste un perfect guess
    perfect_guesser = next((p for p in players if p[3] == 0.0), None)

    if perfect_guesser:
        # Calcolo parte variabile da perdenti
        middle = num_players // 2
        variable_pool = 0
        losers_info = []

        for i in range(middle):
            diff_top = players[i][3]
            diff_bottom = players[-(i + 1)][3]
            loss = abs(round((diff_bottom - diff_top) * 5, 2))
            variable_pool += loss
            losers_info.append((players[-(i + 1)][0], players[-(i + 1)][1], loss))

        pg_id, pg_uname, _, _ = perfect_guesser
        total_prize = round(300 + variable_pool, 2)

        # Aggiorna bilancio vincitore perfetto
        c.execute("UPDATE balances SET username = ? WHERE user_id = ?", (pg_uname, pg_id))
        c.execute("""
            INSERT INTO balances (user_id, username, balance)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = ROUND(balance + ?, 2),
                username = excluded.username
        """, (pg_id, pg_uname, total_prize, total_prize))

        # Aggiorna perdenti
        for loser_id, loser_uname, loss in losers_info:
            c.execute("UPDATE balances SET username = ? WHERE user_id = ?", (loser_uname, loser_id))
            c.execute("""
                INSERT INTO balances (user_id, username, balance)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    balance = ROUND(balance - ?, 2),
                    username = excluded.username
            """, (loser_id, loser_uname, -loss, loss))

        conn.commit()

        msg = f"<b>📈 Variazione GME ({target_date}): {closing_percentage}%</b>\n\n"
        msg += f"🎯 <b>Perfetto!</b> @{pg_uname} ha indovinato esattamente la chiusura e vince <b>{total_prize}€</b>!\n\n"
        msg += "<b>Perdenti:</b>\n"
        for _, uname, loss in losers_info:
            msg += f"• @{uname} ha perso <i>{loss}€</i>\n"

        c.execute("INSERT INTO winners (date, result) VALUES (?, ?)", (target_date, msg))
        conn.commit()
        await update.message.reply_text(msg, parse_mode="HTML")
        return

    # Altrimenti, ramo standard
    rewards = {1: 150, 2: 100, 3: 50}
    penalties = {-1: -150, -2: -100, -3: -50}
    risk_multiplier = 5
    changes = {uid: [uname, 0.0, 0.0] for uid, uname, _, _ in players}  # {user_id: [username, fisso, variabile]}

    # Premi e penalità fisse
    for i in range(3):
        changes[players[i][0]][1] += rewards[i + 1]
        changes[players[-(i + 1)][0]][1] += penalties[-(i + 1)]

    # Variabile simmetrica
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

    # Aggiornamento balances
    for uid, (uname, fisso, var) in changes.items():
        totale = round(fisso + var, 2)
        # 1. Aggiorna username se è cambiato
        c.execute("UPDATE balances SET username = ? WHERE user_id = ?", (uname, uid))
        c.execute("""
            INSERT INTO balances (user_id, username, balance)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                balance = ROUND(balance + ?, 2),
                username = excluded.username
        """, (uid, uname, totale, totale))

    conn.commit()

    # Output classifica
    msg = f"<b>📈 Variazione GME ({target_date}): {closing_percentage}%</b>\n\n"
    sorted_results = sorted(
        changes.items(),
        key=lambda item: -(item[1][1] + item[1][2])  # fisso + variabile
    )

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

    c.execute("INSERT INTO winners (date, result) VALUES (?, ?)", (target_date, msg))
    conn.commit()
    await update.message.reply_text(msg, parse_mode="HTML")



async def testapi(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Solo l'amministratore può usare questo comando.")
        return

    url = f"https://finnhub.io/api/v1/quote?symbol={GME_TICKER}&token={API_KEY}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        prev_close = data.get("pc")
        close = data.get("c")

        if prev_close is None or close is None:
            msg = f"⚠️ Dati incompleti ricevuti da Finnhub:\n<pre>{data}</pre>"
            logging.warning(msg)
            await update.message.reply_text(msg, parse_mode="HTML")
            return

        variation = round(((close - prev_close) / prev_close) * 100, 2)
        msg = f"✅ <b>Variazione GME:</b> {variation}%\n<pre>pc: {prev_close}, c: {close}</pre>"
        await update.message.reply_text(msg, parse_mode="HTML")
    except Exception as e:
        logging.error(f"❌ Errore nella chiamata a Finnhub: {e}")
        await update.message.reply_text(f"❌ Errore nella richiesta: {e}")


async def istruzioni(update: Update, context: CallbackContext):
    messaggio = (
        "📘 <b>Istruzioni del GME Bot</b>\n\n"
        "Benvenuto nel bot per scommettere sulla variazione giornaliera del titolo GME 📈.\n\n"
        "Ogni giorno di mercato aperto puoi fare la tua previsione sulla variazione % del titolo con il comando <b>/bet</b>.\n"
        "Le previsioni si chiudono alle <b>15:30</b>. I risultati vengono poi calcolati dopo la chiusura del mercato alle <b>22:10</b>.\n\n"
        "<b>🧮 Sistema di punteggio:</b>\n"
        "• <b>Parte fissa</b>:\n"
        "   – 🥇 1° classificato: +150 €\n"
        "   – 🥈 2° classificato: +100 €\n"
        "   – 🥉 3° classificato: +50 €\n"
        "   – 💀 Terzultimo: –50 €\n"
        "   – 💀 Penultimo: –100 €\n"
        "   – 💀 Ultimo: –150 €\n"
        "• <b>Parte variabile</b>:\n"
        "   – Calcolata abbinando chi è più preciso con chi è meno preciso\n"
        "   – Differenza di errore × <b>moltiplicatore di rischio 5×</b>\n\n"
        "<b>🎯 Perfect guess</b>:\n"
        "Se la tua previsione coincide esattamente con la chiusura (diff = 0), vinci:\n"
        "• Tutte le parti fisse (300 € totali)\n"
        "• L’intera parte variabile persa dalla metà inferiore della classifica\n\n"
        "<b>📋 Comandi disponibili</b>:\n"
        "• <b>/bet &lt;percentuale&gt;</b> – Registra la tua scommessa del giorno\n"
        "• <b>/scommesse</b> – Elenca chi ha già piazzato la scommessa oggi\n"
        "• <b>/vincitore [yesterday]</b> – Calcola e mostra i risultati (oggi o ieri)\n"
        "• <b>/bilancio</b> – Mostra il tuo saldo personale\n"
        "• <b>/classifica</b> – Mostra la classifica aggiornata\n"
        "• <b>/istruzioni</b> – Mostra questo messaggio\n"
        "• <b>/id</b> – Restituisce l’ID della chat o dell’utente (per debug)\n"
        "• <b>/ban username giorni</b> – (Solo il re dei bot può usare questo comando) blocca un utente per un numero di giorni\n"
        "• <b>/bannati</b> –  elenca gli utenti attualmente bannati\n\n"
        "Buona fortuna e che vinca il più preciso! 🧠💸"
    )
    await update.message.reply_text(messaggio, parse_mode="HTML")

async def registra_id(update: Update, context: CallbackContext):
    user = update.message.from_user
    user_id = user.id
    username = user.username or "Sconosciuto"

    # Messaggio privato all'utente
    await update.message.reply_text("✅ Ok! ID registrato.")

    # Messaggio nella chat bot admin
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🆔 ID registrato: @{username} → {user_id}"
        )
    except Exception as e:
        logging.error(f"Errore nell'invio dell'ID: {e}")


async def ban(update: Update, context: CallbackContext):
    # Solo l'admin può eseguire il comando
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ Solo il Re dei Bot può bannare gli utenti.")
        return

    if len(context.args) != 2:
        await update.message.reply_text("❗ Usa il comando così: /ban username giorni")
        return

    username = context.args[0].lstrip("@")
    try:
        giorni = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❗ Il numero di giorni deve essere un numero intero.")
        return

    c.execute("SELECT user_id FROM balances WHERE username = ?", (username,))
    result = c.fetchone()
    if not result:
        await update.message.reply_text(f"⚠️ Nessun utente trovato con username @{username}.")
        return

    user_id = result[0]
    ban_until = (datetime.now(ITALY_TZ).date() + timedelta(days=giorni)).strftime("%Y-%m-%d")
    c.execute("INSERT OR REPLACE INTO bans (user_id, ban_until) VALUES (?, ?)", (user_id, ban_until))
    conn.commit()

    await update.message.reply_text(f"✅ L'utente @{username} è stato bannato fino al {ban_until}.")



async def unban(update: Update, context: CallbackContext):
    if update.message.from_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("❌ Non hai i permessi per usare questo comando.")
        return

    try:
        username = context.args[0].lstrip("@")
    except IndexError:
        await update.message.reply_text("⚠️ Usa il comando così: /unban username")
        return

    c.execute("SELECT user_id FROM balances WHERE username = ?", (username,))
    res = c.fetchone()
    if not res:
        await update.message.reply_text("❌ Utente non trovato.")
        return
    user_id = res[0]
    c.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))


    await update.message.reply_text(f"✅ Il ban per @{username} è stato rimosso.")
    
async def bannati(update: Update, context: CallbackContext):
    today = datetime.now(ITALY_TZ).date()

    # Recupera tutti i ban ancora attivi
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
            user_data = c.fetchone()
            username = user_data[0] if user_data else f"ID {user_id}"
            giorni_rimanenti = (ban_date - today).days
            message += f"• @{username} — fino al {ban_date.strftime('%d/%m/%Y')} ({giorni_rimanenti} giorni rimanenti)\n"
            found = True

    if not found:
        message = "✅ Nessun utente è attualmente bannato."

    await update.message.reply_text(message, parse_mode="HTML")



async def admin(update: Update, context: CallbackContext):
    try:
        chat = update.effective_chat
        admins = await context.bot.get_chat_administrators(chat.id)

        mentions = []
        for admin in admins:
            user = admin.user
            if user.username:
                mentions.append(f"@{user.username}")
            else:
                name = user.first_name or "admin"
                mentions.append(f"<i>{name}</i>")

        message = "🔧 <b>Amministratori della chat:</b>\n" + "\n".join(mentions)
        await update.message.reply_text(message, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Errore nel recupero degli admin: {e}")
        await update.message.reply_text("❌ Errore nel recupero degli admin.")


async def testVincitore(update: Update, context: CallbackContext):
    """
    Funzione per testare il calcolo del vincitore con premi e penalità corretti.
    La logica qui segue esattamente quella di /vincitore, utilizzando dati casuali.
    """
    # 1️⃣ Generazione dei dati casuali
    closing_percentage = round(random.uniform(-10, 10), 2)  # Simula un valore di chiusura casuale
    players = [f"Player{i}" for i in range(1, 17)]  # 16 giocatori
    # Genera previsioni casuali per ogni giocatore
    predictions = [(player, round(random.uniform(-10, 10), 2)) for player in players]

    # 2️⃣ Calcolo della differenza assoluta e ordinamento delle previsioni
    predictions = [
        (username, prediction, round(abs(prediction - closing_percentage), 2))
        for username, prediction in predictions
    ]
    predictions.sort(key=lambda x: x[2])  # Ordina per differenza crescente
    num_players = len(predictions)

    # 3️⃣ Definizione di premi, penalità fisse e moltiplicatore per la parte variabile
    rewards = {1: 150, 2: 100, 3: 50}      # Premi per i primi 3
    penalties = {-1: -150, -2: -100, -3: -50}  # Penalità per gli ultimi 3
    risk_multiplier = 5

    # 4️⃣ Inizializzazione della struttura dei risultati: ogni giocatore parte con [fisso, variabile] = [0, 0]
    balance_changes = {username: [0, 0] for username, _, _ in predictions}

    # 5️⃣ Assegnazione dei premi e delle penalità fisse
    for i in range(3):
        # Premi per i primi 3 (migliore accuratezza)
        username_top = predictions[i][0]
        balance_changes[username_top][0] += rewards[i + 1]

        # Penalità per gli ultimi 3 (peggiore accuratezza)
        username_bottom = predictions[-(i + 1)][0]
        balance_changes[username_bottom][0] += penalties[-(i + 1)]

    # 6️⃣ Assegnazione della parte variabile abbinando il giocatore in testa a quello in fondo
    middle_index = num_players // 2
    for i in range(middle_index):
        username_top, prediction_top, diff_top = predictions[i]
        username_bottom, prediction_bottom, diff_bottom = predictions[-(i + 1)]
        variable_bonus = (diff_bottom - diff_top) * risk_multiplier
        balance_changes[username_top][1] += variable_bonus
        balance_changes[username_bottom][1] -= variable_bonus

    # 7️⃣ Se il numero di giocatori è dispari, il giocatore centrale viene resettato a [0, 0]
    if num_players % 2 == 1:
        mid_username = predictions[middle_index][0]
        balance_changes[mid_username] = [0, 0]

    # 8️⃣ Creazione della classifica finale ordinando per punteggio totale (fisso + variabile)
    sorted_results = sorted(balance_changes.items(), key=lambda x: -(x[1][0] + x[1][1]))

    # 9️⃣ Costruzione del messaggio di output simulando la classifica
    message = f"\n📈 Simulazione Test - Variazione GME: {closing_percentage}%\n\n"
    for i, (username, changes) in enumerate(sorted_results):
        # Recupera la previsione originale
        prediction = next(pred for user, pred, _ in predictions if user == username)
        diff = round(abs(prediction - closing_percentage), 2)
        rank = i + 1
        fixed_part, variable_part = changes
        total_score = fixed_part + variable_part

        if rank <= 3:
            message += f"🏆 {rank}° posto: @{username} ha previsto {prediction}% (📏 Diff: {diff}%), Fisso: {fixed_part}€, Variabile: {round(variable_part, 2)}€, Totale: {round(total_score, 2)}€\n"
        elif rank > num_players - 3:
            message += f"💀 {rank}° posto: @{username} ha previsto {prediction}% (📏 Diff: {diff}%), Fisso: {fixed_part}€, Variabile: {round(variable_part, 2)}€, Totale: {round(total_score, 2)}€\n"
        else:
            message += f"⚖️ {rank}° posto: @{username} ha previsto {prediction}% (📏 Diff: {diff}%), Fisso: {fixed_part}€, Variabile: {round(variable_part, 2)}€, Totale: {round(total_score, 2)}€\n"

    # 🔟 Invia il messaggio di output
    await update.message.reply_text(message)


async def betTEST(update: Update, context: CallbackContext):
    # Prova a estrarre il valore della scommessa (verifica la sintassi, ma non lo mostra)
    try:
        _ = float(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("❗ Usa il comando così: /betTEST 1.4")
        return

    # Costruisci il messaggio di conferma senza mostrare il valore
    username = update.message.from_user.username
    today_date = datetime.now(ITALY_TZ).strftime("%Y-%m-%d")
    confirmation_message = (
        f"✅ <b>Scommessa registrata!</b>\n"
        f"@{username} ha scommesso per la giornata odierna ({today_date})."
    )

    # Prova a eliminare il messaggio originale per nascondere il comando
    try:
        await update.message.delete()
    except Exception as e:
        logging.error(f"Errore nel cancellare il messaggio: {e}")

    # Se il messaggio appartiene a un thread, ottieni l'id del thread
    thread_id = getattr(update.message, "message_thread_id", None)

    # Invia il messaggio di conferma nella stessa chat (e thread se presente)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=confirmation_message,
        parse_mode="HTML",
        message_thread_id=thread_id  # Questo lo manda nel thread corretto se esiste
    )

# Reminder scheduler: invia messaggi di reminder alla chat specificata
async def reminder_scheduler(chat_id: int):
    """
    Invia reminder alla chat (chat_id) a 3 ore, 2 ore, 1 ora e 10 minuti 
    prima del cutoff delle scommesse.
    Non invia reminder se oggi è sabato o domenica oppure se la data target è in CHIUSURE_MERCATO.
    Per evitare duplicati, tiene traccia degli offset per cui il reminder è già stato inviato.
    """
    # Dizionario per tracciare gli offset già inviati per ciascuna data target
    sent_reminders = {}

    # Definisci gli offset in minuti e i relativi messaggi
    reminder_offsets = [
        (180, "Mancano 3 ore"),
        (120, "Mancano 2 ore"),
        (60,  "Manca 1 ora"),
        (10,  "Mancano 10 minuti")
    ]

    while True:
        now = datetime.now(ITALY_TZ)

        # Se oggi è sabato (weekday() == 5) o domenica (weekday() == 6), salta i reminder
        if now.weekday() in [5, 6]:
            await asyncio.sleep(60)
            continue

        # Calcola il cutoff per le scommesse per oggi usando CUTOFF_TIME
        cutoff = now.replace(hour=CUTOFF_TIME.hour, minute=CUTOFF_TIME.minute, second=0, microsecond=0)
        # Se siamo già oltre il cutoff, calcola per il giorno successivo
        if now > cutoff:
            tomorrow = now + timedelta(days=1)
            cutoff = tomorrow.replace(hour=CUTOFF_TIME.hour, minute=CUTOFF_TIME.minute, second=0, microsecond=0)
        target_date = cutoff.strftime("%Y-%m-%d")

        # Se il mercato è chiuso per quella data, salta i reminder
        if target_date in CHIUSURE_MERCATO:
            await asyncio.sleep(60)
            continue

        # Inizializza sent_reminders per target_date se non esiste
        if target_date not in sent_reminders:
            sent_reminders[target_date] = set()

        for offset, text in reminder_offsets:
            if offset in sent_reminders[target_date]:
                continue  # Reminder già inviato per questo offset e data
            reminder_time = cutoff - timedelta(minutes=offset)
            # Se siamo entro 1 minuto dalla finestra del reminder
            if reminder_time <= now < reminder_time + timedelta(minutes=1):
                try:
                    c.execute("SELECT COUNT(*) FROM predictions WHERE date = ?", (target_date,))
                    count = c.fetchone()[0]
                except Exception as e:
                    logging.error(f"Errore nell'interrogazione del database per i reminder: {e}")
                    count = "non disponibile"
                cutoff_str = f"{CUTOFF_TIME.hour:02d}:{CUTOFF_TIME.minute:02d}"
                message = (f"🔔 {text}: il termine delle scommesse è fissato per le {cutoff_str}.\n"
                           f"Finora sono state piazzate solo {count} scommesse per il {target_date}.\n"
                           f"Utilizza il comando /scommesse per scoprire chi non è una fighetta!")
                try:
                    await app_instance.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
                except Exception as e:
                    logging.error(f"Errore nell'invio del reminder: {e}")
                sent_reminders[target_date].add(offset)
        await asyncio.sleep(30)



# Funzione per avviare il bot


# Main function
        
# Main async
async def main_async():
    global app_instance
    app_instance = Application.builder().token(TOKEN).build()

    # Aggiunta handler comandi
    app_instance.add_handler(CommandHandler("bet", bet))
    app_instance.add_handler(CommandHandler("vincitore", vincitore))
    app_instance.add_handler(CommandHandler("testapi", testapi))
    app_instance.add_handler(CommandHandler("betTEST", betTEST))
    app_instance.add_handler(CommandHandler("classifica", classifica))
    app_instance.add_handler(CommandHandler("scommesse", scommesse))
    app_instance.add_handler(CommandHandler("bilancio", bilancio))
    app_instance.add_handler(CommandHandler("admin", admin))
    app_instance.add_handler(CommandHandler("testVincitore", testVincitore))
    app_instance.add_handler(CommandHandler("istruzioni", istruzioni))
    app_instance.add_handler(CommandHandler("id", registra_id))
    app_instance.add_handler(CommandHandler("ban", ban))
    app_instance.add_handler(CommandHandler("unban", unban))
    app_instance.add_handler(CommandHandler("bannati", bannati))

    logging.info("Bot avviato con successo!")

    # Avvia reminder in background solo se è una coroutine valida
    try:
        task = reminder_scheduler(GROUP_TOPIC_CHAT_ID)
        if asyncio.iscoroutine(task):
            asyncio.create_task(task)
        else:
            logging.error("reminder_scheduler non ha restituito una coroutine valida.")
    except Exception as e:
        logging.error(f"Errore nell'avvio del reminder scheduler: {e}")

    # Polling del bot
    await app_instance.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False
    )


def main():
    try:
        asyncio.run(main_async())
    except Exception as e:
        logging.exception("Errore fatale nel main:")


if __name__ == "__main__":
    main()


