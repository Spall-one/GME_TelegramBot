
import time
import logging
import requests
import os
import subprocess

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BOT_SCRIPT = "GME_TelegramBot.py"
HEALTH_URL = "http://localhost:8080/health"
CHECK_INTERVAL = 300  # 5 minuti

def is_bot_running():
    try:
        response = requests.get(HEALTH_URL, timeout=10)
        if response.status_code == 200:
            logging.info(f"Bot attivo: {response.json()}")
            return True
    except Exception as e:
        logging.error(f"Errore nel controllo dello stato del bot: {e}")
    return False

def restart_bot():
    logging.warning("Riavvio del bot in corso...")
    try:
        # Trova e termina qualsiasi processo python esistente
        os.system("pkill -f python")
        time.sleep(5)  # Attendi che i processi terminino
        
        # Avvia il bot in background
        subprocess.Popen(["python3", BOT_SCRIPT], 
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
        logging.info("Bot riavviato con successo")
    except Exception as e:
        logging.error(f"Errore nel riavvio del bot: {e}")

def main():
    logging.info("Script di monitoraggio avviato")
    
    while True:
        if not is_bot_running():
            logging.warning("Bot non attivo - avvio riavvio")
            restart_bot()
        
        # Attendi prima del prossimo controllo
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
