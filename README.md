# 🎟️ fanSALE Assistant

Un piccolo assistente locale per monitorare le offerte di biglietti su fanSALE e ricevere un avviso su Telegram quando una data o un'offerta diventa disponibile.

Il bot apre un browser visibile, controlla le offerte e può tentare **una sola aggiunta al carrello**. Non completa l'acquisto: pagamento e checkout restano manuali.

> [!IMPORTANT]
> L'aggiunta al carrello è un'azione reale, non una simulazione. Usa il programma solo se ne hai verificato i termini d'uso e controlla sempre i dettagli nel browser. Il bot non aggira CAPTCHA o controlli di sicurezza.

## A cosa serve

È pensato per seguire un evento e avvisarti senza dover aggiornare la pagina continuamente. Quando individua la data o dei biglietti compatibili:

- invia una notifica Telegram;
- apre i dettagli dell'offerta e tenta l'aggiunta al carrello;
- verifica che il carrello mostri una prenotazione attiva e che data e città corrispondano;
- si ferma, lasciando a te il completamento dell'acquisto nella stessa finestra del browser.

## Requisiti

- Windows e Python 3.10 o successivo;
- Google Chrome o Microsoft Edge installato;
- una connessione internet;
- un bot Telegram e il relativo token e chat ID.

Il browser usa un profilo locale dedicato in `browser-profile`: non è il profilo abituale di Chrome/Edge. Accedi a fanSALE e completa eventuali consensi da quella finestra.

## Installazione

Apri PowerShell nella cartella che contiene `bot.py` e `requirements.txt`:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Se il comando `py` non è disponibile, usa `python` al suo posto.

## Configurazione Telegram

Crea un bot con [@BotFather](https://t.me/BotFather), poi apri la chat con il bot e inviagli `/start`. Crea un file `.env` accanto a `bot.py` con:

```dotenv
TELEGRAM_BOT_TOKEN=il_tuo_token
TELEGRAM_CHAT_ID=il_tuo_chat_id
```

Sostituisci i valori di esempio con quelli reali. Non condividere né pubblicare `.env`: contiene le credenziali del bot.

## Avvio e utilizzo

Avvia il programma dalla cartella del progetto:

```powershell
.\.venv\Scripts\python.exe bot.py
```

### 1. Scegli l'evento

Si apre una finestra del browser. Cerca manualmente l'evento su fanSALE e apri la pagina con l'elenco delle date. Le date vengono rilevate automaticamente: non serve premere INVIO per avviare il monitoraggio.

- Se la data è nell'elenco, selezionala inserendo il numero corrispondente nella console.
- Se la data non compare, scegli `0` e inserisci **titolo, data e città**. Non serve copiare o inserire un link: il bot controlla la pagina fanSALE già aperta e attende che compaia una riga corrispondente.
- Se non viene riconosciuta alcuna data, puoi ricaricare la pagina oppure scegliere l'inserimento manuale.

Per l'inserimento manuale, la data deve essere nel formato `GG/MM/AAAA` oppure `AAAA-MM-GG`. Il nome della città viene confrontato senza distinzione tra maiuscole e minuscole; la data viene verificata per giorno, mese e anno.

### 2. Imposta il monitoraggio

La console chiede:

| Impostazione | Significato |
| --- | --- |
| Quantità | Numero massimo di biglietti desiderati |
| Preferenza `1` | Solo categoria Posto Unico |
| Preferenza `2` | Tutte le categorie; privilegia la quantità più alta, poi il prezzo più basso |
| Preferenza `3` | Solo PIT |
| Preferenza `4` | PIT preferito; ripiega su Posto Unico |
| Intervallo | Secondi tra i controlli; minimo 30, predefinito 60 |

Dopo l'ultimo parametro il bot parte senza un altro INVIO. Parti con il carrello vuoto e non usare altre schede per aggiungere biglietti durante il monitoraggio.

### 3. Ricevi l'avviso e completa manualmente

Telegram può avvisarti quando la data richiesta compare, quando vengono trovati biglietti compatibili e quando la prenotazione nel carrello viene confermata. Dopo un tentativo di aggiunta, un esito ambiguo o un errore, il bot si ferma: controlla il browser e completa l'acquisto **nella stessa finestra del PC**. La notifica Telegram non trasferisce la sessione o i cookie al telefono.

Quando il bot si è fermato, la console resta in attesa. Premi INVIO solo quando hai finito di usare il browser.

## Come sceglie un'offerta

- Considera le offerte a prezzo fisso riconosciute dalla pagina.
- Non supera la quantità richiesta e non combina offerte diverse.
- Privilegia l'offerta che consente di acquistare più biglietti entro il limite; a parità di quantità sceglie il prezzo inferiore (la preferenza `4` dà precedenza al PIT).
- Tenta una sola aggiunta al carrello. Non avvia il pagamento e non riprova automaticamente se l'esito non è chiaro.

## Limiti e sicurezza

- I selettori dipendono dalla struttura della pagina fanSALE e possono smettere di funzionare se il sito cambia.
- CAPTCHA, login, consensi e altri controlli devono essere gestiti manualmente. Il browser visibile non garantisce che il sito consenta l'operazione.
- Se il carrello non viene confermato entro 90 secondi, il bot si ferma: verifica la situazione nel browser prima di intervenire.
- Il totale mostrato può non includere spese successive, ad esempio quelle di consegna.
- Il profilo `browser-profile` può contenere cookie e dati di navigazione; `bot.log` può contenere informazioni sull'evento. Non condividere questi file o schermate che espongono dati personali.
- Le notifiche Telegram vengono ritentate fino a tre volte. Un timeout può causare notifiche duplicate.

Questo progetto è un ausilio locale, non un servizio ufficiale fanSALE. Verifica sempre le condizioni del sito e i dettagli prima di procedere con l'acquisto.
