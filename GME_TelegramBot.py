import os
import logging
import sqlite3
import requests
import random
import time as time_module  # Rinominato per evitare conflitti
import threading
import asyncio
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext
from datetime import datetime, time, timezone, timedelta

# Configura logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# Imposta il tuo token Telegram
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GME_TICKER = "GME"
API_KEY = os.getenv("FINNHUB_API_KEY")  # Finnhub API Key

# Imposta il fuso orario italiano
ITALY_TZ = timezone(timedelta(hours=1))
MARKET_CLOSE_TIME = time(21, 10)

# Orari di apertura e chiusura delle scommesse
START_TIME = time(0, 0)  # Apertura a mezzanotte
CUTOFF_TIME = time(14, 30)  # Chiusura alle 15:30



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

# Lista di giorni in cui il mercato è chiuso (festività, chiusure programmate)
CHIUSURE_MERCATO = {
    "2025-01-01", "2025-07-04", "2025-12-25", "2025-12-26", "2025-11-27", "2025-04-18"
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

    if not username:
        await update.message.reply_text("⚠️ Non posso registrare la tua scommessa perché non hai un username su Telegram! Impostane uno e riprova.")
        return

    # Controllo se il mercato è chiuso (weekend o festività)
    if weekday in [5, 6] or today_date in CHIUSURE_MERCATO:
        await update.message.reply_text(f"❌ Il mercato è chiuso oggi ({today_date}). Le scommesse riapriranno il prossimo giorno utile.")
        return

    # Controllo se è fuori orario (ammissibile solo tra 00:00 e 14:30)
    if now.time() < START_TIME or now.time() > CUTOFF_TIME:
        await update.message.reply_text("❌ Le previsioni sono chiuse. Puoi scommettere tra 00:00 e 14:30 nei giorni di mercato aperto.")
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
        await update.message.reply_text("⚠️ Hai già scommesso oggi! Non puoi cambiarla.")
        return

    # Controllo per scommesse identiche da utenti diversi
    c.execute("SELECT 1 FROM predictions WHERE prediction = ? AND date = ?", (prediction, today_date))
    same_prediction = c.fetchone()
    if same_prediction:
        try:
            await update.message.delete()
        except Exception as e:
            logging.error(f"Errore nel cancellare il messaggio: {e}")
        await update.message.reply_text("⚠️ Questo valore è già stato scommesso da un altro utente! Prova con un valore diverso.")
        return

    # Salva la scommessa nel database
    c.execute("INSERT INTO predictions (user_id, username, prediction, date) VALUES (?, ?, ?, ?)",
              (user_id, username, prediction, today_date))
    conn.commit()

    # Costruisci il messaggio di conferma senza mostrare il valore della scommessa
    confirmation_message = (
        f"✅ <b>Scommessa registrata!</b>\n"
        f"@{username} ha scommesso per la giornata odierna ({today_date})."
    )

    # Elimina il messaggio originale (già fatto in caso di errori, lo riproviamo qui per sicurezza)
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
    """
    Funzione per determinare il vincitore e aggiornare i bilanci dei giocatori,
    con messaggio finale formattato in HTML.
    """
    now = datetime.utcnow() + timedelta(hours=1)  # Fuso orario italiano
    date_offset = -1 if context.args and context.args[0] == "yesterday" else 0
    target_date = (now + timedelta(days=date_offset)).strftime("%Y-%m-%d")

    # 1. Controllo orari e festività
    if date_offset == 0 and now.time() < MARKET_CLOSE_TIME:
        await update.message.reply_text("⏳ Il mercato è ancora aperto! Puoi controllare il vincitore dopo le 21:10.")
        return

    if target_date in CHIUSURE_MERCATO:
        await update.message.reply_text(f"❌ Il mercato era chiuso il {target_date}. Nessuna vincita calcolata.")
        return

    # 2. Verifica se i vincitori sono già stati calcolati
    c.execute("SELECT result FROM winners WHERE date = ?", (target_date,))
    existing_result = c.fetchone()
    if existing_result:
        await update.message.reply_text(existing_result[0], parse_mode="HTML")
        return

    # 3. Recupera le previsioni dal DB
    c.execute("SELECT user_id, username, prediction FROM predictions WHERE date = ?", (target_date,))
    predictions = c.fetchall()
    if not predictions:
        await update.message.reply_text(f"Nessuna previsione registrata per il {target_date}.")
        return

    # 4. Recupera la variazione di GME
    closing_percentage = get_gme_closing_percentage()
    if closing_percentage is None:
        await update.message.reply_text("⚠️ La variazione percentuale di GME non è ancora disponibile. Riprova più tardi.")
        return

    # 5. Calcolo differenze e ordinamento
    predictions = [
        (user_id, username, prediction, round(abs(prediction - closing_percentage), 2))
        for user_id, username, prediction in predictions
    ]
    predictions.sort(key=lambda x: x[3])  # ordina per differenza crescente
    num_players = len(predictions)

    # 6. Premi/penalità fisse
    rewards = {1: 150, 2: 100, 3: 50}
    penalties = {-1: -150, -2: -100, -3: -50}
    risk_multiplier = 5

    # Inizializzazione risultati: [fisso, variabile]
    balance_changes = {username: [0, 0] for _, username, _, _ in predictions}

    # Assegna premi/penalità fisse
    for i in range(3):
        username_top = predictions[i][1]
        balance_changes[username_top][0] += rewards[i + 1]

        username_bottom = predictions[-(i + 1)][1]
        balance_changes[username_bottom][0] += penalties[-(i + 1)]

    # 7. Bonus variabile (top vs bottom)
    middle_index = num_players // 2
    for i in range(middle_index):
        user_id_top, username_top, pred_top, diff_top = predictions[i]
        user_id_bottom, username_bottom, pred_bottom, diff_bottom = predictions[-(i + 1)]
        variable_bonus = round((diff_bottom - diff_top) * risk_multiplier, 2)
        balance_changes[username_top][1] += variable_bonus
        balance_changes[username_bottom][1] -= variable_bonus

    # Gestione giocatore centrale se dispari
    if num_players % 2 == 1:
        mid_username = predictions[middle_index][1]
        balance_changes[mid_username] = [0, 0]

    # 8. Costruzione classifica finale
    sorted_results = sorted(balance_changes.items(), key=lambda x: -(x[1][0] + x[1][1]))

    # 9. Creazione del messaggio con HTML
    message = f"<b>📈 Variazione GME ({target_date}): {closing_percentage}%</b>\n\n"

    for i, (username, changes) in enumerate(sorted_results):
        user_id = next(u_id for u_id, usr, _, _ in predictions if usr == username)
        prediction = next(pred for _, usr, pred, _ in predictions if usr == username)
        diff = round(abs(prediction - closing_percentage), 2)
        rank = i + 1
        fixed_part, variable_part = changes
        total_score = round(fixed_part + variable_part, 2)

        # Aggiorna il bilancio nel DB
        c.execute(
            "INSERT INTO balances (user_id, username, balance) VALUES (?, ?, ROUND(?, 2)) "
            "ON CONFLICT(username) DO UPDATE SET balance = ROUND(balance + ?, 2)",
            (user_id, username, total_score, total_score)
        )

        # Testo formattato
        if rank <= 3:
            # Primi 3
            message += (
                f"🏆 <b>{rank}° posto</b>: @{username} ha previsto <i>{prediction:.2f}%</i> "
                f"(📏 Diff: <i>{diff:.2f}%</i>), Fisso: <b>{fixed_part}€</b>, "
                f"Variabile: <b>{variable_part}€</b>, Totale: <b>{total_score}€</b>\n"
            )
        elif rank > num_players - 3:
            # Ultimi 3
            message += (
                f"💀 <b>{rank}° posto</b>: @{username} ha previsto <i>{prediction:.2f}%</i> "
                f"(📏 Diff: <i>{diff:.2f}%</i>), Fisso: <b>{fixed_part}€</b>, "
                f"Variabile: <b>{variable_part}€</b>, Totale: <b>{total_score}€</b>\n"
            )
        else:
            # Posizioni intermedie
            message += (
                f"⚖️ <b>{rank}° posto</b>: @{username} ha previsto <i>{prediction:.2f}%</i> "
                f"(📏 Diff: <i>{diff:.2f}%</i>), Fisso: <b>{fixed_part}€</b>, "
                f"Variabile: <b>{variable_part}€</b>, Totale: <b>{total_score}€</b>\n"
            )

    conn.commit()

    # 10. Salvataggio risultati e invio messaggio
    c.execute("INSERT INTO winners (date, result) VALUES (?, ?)", (target_date, message))
    conn.commit()

    await update.message.reply_text(message, parse_mode="HTML")



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



# Funzione per avviare il bot


def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("bet", bet))
    application.add_handler(CommandHandler("vincitore", vincitore))
    application.add_handler(CommandHandler("betTEST", betTEST))
    application.add_handler(CommandHandler("classifica", classifica))
    application.add_handler(CommandHandler("scommesse", scommesse))
    application.add_handler(CommandHandler("bilancio", bilancio))
    application.add_handler(CommandHandler("testVincitore", testVincitore))
    logging.info("Bot avviato con successo!")

    last_attempt_time = time_module.time()
    max_retry_interval = 300  # 5 minuti massimi tra i tentativi
    retry_count = 0

    while True:
        try:
            # Resetta il contatore se è passato troppo tempo dall'ultimo errore
            current_time = time_module.time()
            if current_time - last_attempt_time > 3600:  # 1 ora
                retry_count = 0
            last_attempt_time = current_time

            logging.info(f"Avvio sessione di polling #{retry_count + 1}")

            # Crea un nuovo event loop per questa sessione di polling
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            # run_polling() è una coroutine; usiamo run_until_complete per farla girare
            new_loop.run_until_complete(
                application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
            )
            new_loop.close()

        except Exception as e:
            retry_count += 1
            wait_time = min(5 * (2 ** min(retry_count, 5)), max_retry_interval)
            logging.error(f"Bot bloccato con errore: {e}. Tentativo #{retry_count}. Riavvio tra {wait_time} secondi...")
            try:
                requests.get("http://localhost:8080/", timeout=10)
            except Exception:
                pass
            time_module.sleep(wait_time)

if __name__ == "__main__":
    main()
