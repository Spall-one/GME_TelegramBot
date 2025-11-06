# GME_TelegramBot
Questo progetto è un bot Telegram che consente agli utenti di scommettere sulla variazione percentuale giornaliera del titolo GME (GameStop). Il bot raccoglie le previsioni, calcola i risultati e aggiorna automaticamente i bilanci dei giocatori in base alle loro performance.

Table of Contents
Overview
Features
Prerequisites
Installation
Configuration
Usage
Deployment
Database
Troubleshooting
License
Overview
Il bot permette agli utenti di effettuare scommesse sulla variazione percentuale del titolo GME.
Le scommesse vengono registrate in un database SQLite e, una volta chiuso il mercato, il bot calcola i vincitori, aggiorna i bilanci e mostra la classifica.
Per garantire che il bot rimanga attivo anche su ambienti cloud, è stato implementato un server Flask (con endpoint / e /health) per il keep-alive, insieme a un meccanismo di watchdog nel loop di polling.

Features
Scommesse giornaliere:
Gli utenti possono piazzare una scommessa tramite il comando /bet <valore> (es. /bet 2.5).
Il comando registra la scommessa senza mostrare il valore in chat, per evitare copie.

Visualizzazione delle scommesse:

Prima delle 15:30: Mostra solo gli username degli utenti che hanno scommesso.
Dopo le 15:30: Mostra anche l'ammontare scommesso.
Calcolo dei vincitori:
Dopo la chiusura del mercato, il comando /vincitore calcola e mostra i vincitori, aggiornando i bilanci con premi fissi, penalità e un bonus variabile basato sull'accuratezza della previsione.

Comandi aggiuntivi:

/classifica: Visualizza la classifica aggiornata dei giocatori in base ai loro bilanci.
/bilancio: Mostra il bilancio personale dell'utente.
/betTEST: Funzione di prova che registra una scommessa "nascosta" senza rivelarne il valore.
/testVincitore: Funzione di test per simulare il calcolo dei vincitori con dati casuali.
Keep-Alive:
Il bot integra un piccolo server Flask per fornire un endpoint HTTP, utile per configurare servizi di ping (es. UptimeRobot) e mantenere attivo il servizio su piattaforme cloud.
Un task asincrono effettua automaticamente richieste GET all'URL indicato da `KEEPALIVE_URL` (o
da `RENDER_EXTERNAL_URL`) ogni pochi minuti per impedire lo standby del servizio.

Prerequisites
Python 3.10+ (o una versione compatibile)
Git
SQLite3
Installation
Clonare il repository:

bash
Copia
git clone https://github.com/Spall-one/GME_TelegramBot.git
cd GME_TelegramBot
Installare le dipendenze:

Assicurati di avere un file requirements.txt (vedi Configuration). Poi esegui:

bash
Copia
pip install -r requirements.txt
Configuration
Crea un file .env nella root del progetto per configurare le variabili d'ambiente necessarie. Esempio:

ini
Copia
TELEGRAM_BOT_TOKEN=il_tuo_token_telegram
FINNHUB_API_KEY=la_tua_chiave_finnhub
PORT=8080
KEEPALIVE_URL=https://<nome-servizio>.onrender.com/
Il bot utilizza il pacchetto python-dotenv per caricare automaticamente queste variabili.

Se `KEEPALIVE_URL` non è impostata, il bot proverà a usare `RENDER_EXTERNAL_URL` (variabile
impostata automaticamente da Render) per eseguire i ping periodici.

Usage
Avvia il bot con il comando:

bash
Copia
python3 GME_TelegramBot.py
Comandi Principali
/bet <valore>
Registra una scommessa per la giornata odierna.
Esempio: /bet 2.5

/betTEST <valore>
Funzione di prova per registrare una scommessa (senza salvare il valore in chat).

/scommesse
Visualizza l'elenco degli utenti che hanno scommesso.
Prima delle 15:30 mostra solo gli username; dopo le 15:30 mostra anche il valore scommesso.

/classifica
Visualizza la classifica completa con i bilanci aggiornati.

/bilancio
Mostra il bilancio personale dell'utente.

/vincitore [yesterday]
Calcola i vincitori e aggiorna i bilanci, in base alle previsioni e al valore reale di chiusura di GME.
Aggiungi "yesterday" per visualizzare i risultati del giorno precedente.

/testVincitore
Funzione di test per simulare il calcolo dei vincitori con dati casuali.

Deployment
Su Render configura il servizio come web service, esponendo la porta specificata dalla
variabile `PORT` (di default 8080). Imposta inoltre la variabile d'ambiente `KEEPALIVE_URL`
al tuo URL pubblico, ad esempio `https://<nome-servizio>.onrender.com/`. In alternativa puoi
affidarti alla variabile `RENDER_EXTERNAL_URL` già fornita da Render, ma impostare
esplicitamente `KEEPALIVE_URL` garantisce che il task di ping utilizzi l'indirizzo corretto
per mantenere l'app attiva.

