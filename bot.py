import os
import re
import subprocess
import time
import logging
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()])

def notify(text):
    logging.info(text)
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("Configura TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nel .env")
    for attempt in range(3):
        try:
            response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                     json={"chat_id": chat, "text": text}, timeout=15)
            response.raise_for_status()
            if not response.json().get("ok"):
                raise RuntimeError("Telegram non ha confermato la consegna")
            return
        except Exception as exc:
            logging.warning("Notifica non confermata: %s", type(exc).__name__)
            time.sleep(2)
    raise RuntimeError("Invio Telegram fallito dopo 3 tentativi")

def integer(prompt, default, minimum=1):
    while True:
        try:
            value = int(input(prompt).strip() or default)
            if value >= minimum:
                return value
        except ValueError:
            pass
        print(f"Inserisci un intero >= {minimum}.")

def first_visible(locator):
    for item in locator.all():
        if item.is_visible():
            return item
    return None


def click_any(page, locator, timeout=15000):
    for attempt in range(3):
        try:
            locator.wait_for(state="visible", timeout=min(10000, timeout))
            page.wait_for_timeout(300)
            box = locator.bounding_box()
            if box:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2
                page.mouse.move(x, y)
                page.mouse.click(x, y, button="left", delay=80)
                return True
        except Exception:
            pass

        try:
            locator.scroll_into_view_if_needed()
            locator.click(timeout=timeout, force=True)
            return True
        except Exception:
            try:
                locator.evaluate("""
                    el => {
                        el.scrollIntoView({ block: 'center', inline: 'center' });
                        const rect = el.getBoundingClientRect();
                        const clickEvent = new MouseEvent('click', {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: rect.left + rect.width / 2,
                            clientY: rect.top + rect.height / 2,
                            button: 0,
                            buttons: 1
                        });
                        el.dispatchEvent(clickEvent);
                    }
                """)
                page.wait_for_timeout(300)
                return True
            except Exception:
                page.wait_for_timeout(500)
    return False


def text(scope, selector):
    item = first_visible(scope.locator(selector))
    return item.inner_text().strip() if item else ""

def normalized(value):
    return re.sub(r"\s+", " ", value).strip().casefold()


def parse_event_date(value):
    patterns = (
        (r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", "%Y-%m-%d"),
        (r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)", "%d/%m/%Y"),
    )
    for pattern, date_format in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        parts = match.groups()
        formatted = "-".join(parts) if date_format == "%Y-%m-%d" else "/".join(parts)
        try:
            return date.fromisoformat(formatted) if date_format == "%Y-%m-%d" else datetime.strptime(formatted, date_format).date()
        except ValueError:
            return None
    return None


def dates_match(expected, actual):
    expected_date = parse_event_date(expected)
    actual_date = parse_event_date(actual)
    if expected_date is not None and actual_date is not None:
        return expected_date == actual_date
    return normalized(expected) == normalized(actual)


def city_matches(expected, actual):
    expected_city = normalized(expected)
    return not expected_city or expected_city in normalized(actual)


def seat_category(seat_text):
    value = normalized(seat_text)
    # On fanSALE/TicketOne, PIT is a distinct standing-area type: a divided parterre closer to the
    # stage. "Posto unico" / "Parterre" is instead the single standing-area ticket category.
    if "pit" in value:
        return "pit"
    if "posto unico" in value or "singolo" in value or "single" in value or "parterre" in value or "in piedi" in value:
        return "single"
    return "seat"


def set_offer_quantity(page, offer_id, quantity):
    row = page.locator(f'[data-offer-id="{offer_id}"]')
    if row.count() == 0:
        return True

    for candidate in [quantity, 1, 2, 3]:
        if candidate <= 0:
            continue
        container = row.locator('.NumberOfTicketsDropdown, .Dropdown-Container')
        if container.count() > 0:
            button = container.locator('button').first
            if button.count() > 0:
                try:
                    button.click(timeout=5000)
                except Exception:
                    pass
            item = container.locator(f'li[data-qa="{candidate}"]')
            if item.count() > 0:
                try:
                    item.first.click(timeout=5000)
                    return True
                except Exception:
                    pass
            select = container.locator('select')
            if select.count() > 0:
                try:
                    select.first.select_option(label=str(candidate), timeout=5000)
                    return True
                except Exception:
                    pass
    return False


def offers_from_page(page, wanted, mode):
    candidates = []
    for row in page.locator('[data-qa="ticketToBuy"]').all():
        if not row.is_visible():
            continue
        seat = row.get_attribute("data-seatdescriptionforarialabel") or ""
        category = seat_category(seat)
        if mode == 1 and category != "single":
            continue
        if mode == 3 and category != "pit":
            continue
        if mode == 4 and category not in {"pit", "single"}:
            continue
        if normalized(row.get_attribute("data-offertype") or "") != "prezzo fisso":
            continue
        try:
            amounts = [int(x) for x in row.get_attribute("data-splitting-possibilities").split(",")]
            prices = [Decimal(x) for x in row.get_attribute("data-splitting-possibility-prices").split(",")]
            if len(amounts) != len(prices):
                continue
            options = [(q, p) for q, p in zip(amounts, prices) if 0 < q <= wanted and p > 0]
            if options:
                q, p = max(options, key=lambda x: x[0])
                candidates.append({"id": row.get_attribute("data-offer-id"), "quantity": q,
                                   "price": p, "seat": seat, "category": category})
        except (ValueError, TypeError, ArithmeticError):
            logging.warning("Offerta con metadati non riconosciuti: ignorata")
    if mode == 4:
        return sorted(candidates, key=lambda x: (0 if x["category"] == "pit" else 1, -x["quantity"], x["price"], x["id"]))
    return sorted(candidates, key=lambda x: (-x["quantity"], x["price"], x["id"]))

def security_visible(page):
    return any(first_visible(page.locator(s)) is not None for s in
               ('[data-qa="grecaptcha-modal"]', '#sec-overlay'))

def cart_present(page):
    if first_visible(page.locator('[data-qa="shopping-cart-page"]')) is not None:
        return True
    return page.locator('[data-qa="order-position"]').count() > 0

def cart_info(page, expected, quantity):
    if not cart_present(page):
        return None
    positions = [x for x in page.locator('[data-qa="order-position"]').all() if x.is_visible()]
    if not positions:
        return None

    pos = positions[0]
    title = text(pos, '[data-qa="event-title"]')
    date = text(pos, '[data-qa="event-date"]')
    venue = text(pos, '[data-qa="venue-address"]')
    seat = text(pos, '[data-qa="price-category"]')
    total = text(page, '[data-qa="total-order-sum"] [data-qa="amount"]')
    timer = text(page, '[data-qa="reservation-timer"] [data-qa="time"]')

    tm = re.search(r"(\d+)\s*:\s*(\d+)", timer.replace("⁠", ""))
    if not total or not timer or not tm or int(tm[1]) * 60 + int(tm[2]) <= 0:
        return None

    if expected.get("date") and not dates_match(expected["date"], date):
        raise RuntimeError(f"La data nel carrello ({date or 'non disponibile'}) non corrisponde a quella richiesta ({expected['date']}).")
    if expected.get("city") and not city_matches(expected["city"], venue):
        raise RuntimeError(f"La città nel carrello ({venue or 'non disponibile'}) non corrisponde a quella richiesta ({expected['city']}).")

    if title or date or venue:
        return f"{title or 'Evento'}\n{date or 'Data non disponibile'}\n{venue or 'Luogo non disponibile'}\nCategoria: {seat or 'N/D'}\nTotale attuale: {total}\n{timer}"
    return f"Carrello attivo\nTotale attuale: {total}\n{timer}"


def event_rows(page):
    events = []
    for row in page.locator('a[data-qa="eventRow"]').all():
        if not row.is_visible():
            continue
        title = text(row, '.EvEntryRow-smallSubtitle')
        href = row.evaluate("el => el.href")
        if "package" in normalized(title) or urlparse(href).hostname not in {"www.fansale.it", "fansale.it"}:
            continue
        event_date = row.get_attribute("data-tracking-eventdate") or ""
        city = row.get_attribute("data-city") or ""
        if event_date and title:
            events.append({"title": title, "date": event_date, "city": city, "url": href})
    return events


def matching_event_row(page, expected):
    wanted_title = normalized(expected.get("title", ""))
    for event in event_rows(page):
        actual_title = normalized(event["title"])
        if wanted_title and wanted_title not in actual_title and actual_title not in wanted_title:
            continue
        if not dates_match(expected["date"], event["date"]):
            continue
        if not city_matches(expected["city"], event["city"]):
            continue
        return event
    return None


def manual_event_from_user(page):
    print("Nessun risultato visibile: inserisci i dettagli a mano.")
    title = input("Titolo evento: ").strip()
    date = input("Data evento (es. 12/12/2026): ").strip()
    city = input("Città: ").strip()
    if not title or not city or parse_event_date(date) is None:
        raise RuntimeError("Inserisci titolo, città e una data valida (formato GG/MM/AAAA o AAAA-MM-GG).")
    url = page.url
    if urlparse(url).hostname not in {"www.fansale.it", "fansale.it"}:
        raise RuntimeError("Apri una pagina fanSALE prima di inserire i dettagli dell'evento.")
    return {"title": title, "date": date, "city": city, "url": url, "manual": True}


def choose_event(page):
    print("Nel browser cerca l'artista/evento e apri la pagina con l'elenco delle date.")
    print("Puoi scegliere qualsiasi evento: nessun URL è fissato nel codice.")
    print("Le date vengono rilevate automaticamente; se la data non compare puoi inserirne titolo, data e città (senza URL).")
    deadline = time.monotonic() + 300
    non_home_since = None
    events = event_rows(page)
    while not events and time.monotonic() < deadline:
        if urlparse(page.url).hostname not in {"www.fansale.it", "fansale.it"}:
            raise RuntimeError("Seleziona una pagina fanSALE.")
        parsed_url = urlparse(page.url)
        if parsed_url.path not in ("", "/") or parsed_url.query:
            if non_home_since is None:
                non_home_since = time.monotonic()
            elif time.monotonic() - non_home_since >= 3:
                break
        else:
            non_home_since = None
        page.wait_for_timeout(500)
        events = event_rows(page)
    if urlparse(page.url).hostname not in {"www.fansale.it", "fansale.it"}:
        raise RuntimeError("Seleziona una pagina fanSALE.")
    if not events:
        print("Nessuna data riconosciuta in questo momento.")
        print("1. Ricarica la pagina e riprova")
        print("2. Inserisci manualmente una data/evento non visibile")
        while True:
            choice = input("Scelta [1/2]: ").strip() or "1"
            if choice == "2":
                return manual_event_from_user(page)
            if choice == "1":
                page.reload(wait_until="domcontentloaded")
                if urlparse(page.url).hostname not in {"www.fansale.it", "fansale.it"}:
                    raise RuntimeError("Seleziona una pagina fanSALE.")
                events = event_rows(page)
                if events:
                    break
                print("La pagina continua a non mostrare le date. Usa l'opzione 2 per inserirle manualmente.")
                continue
    print("Seleziona una data visibile; se non appare, usa l'opzione 0 per inserirla manualmente.")
    for i, event in enumerate(events, 1):
        print(f"{i}. {event['title']} | {event['date']} | {event['city']}")
    print("0. Inserisci manualmente una data/evento non visibile")
    while True:
        index = input("Numero data [1]: ").strip() or "1"
        if index == "0":
            return manual_event_from_user(page)
        try:
            selected = int(index)
        except ValueError:
            print("Inserisci un numero valido.")
            continue
        if 1 <= selected <= len(events):
            return events[selected - 1]
        print(f"Inserisci un numero tra 1 e {len(events)} oppure 0 per manuale.")

def prepare_offer(page, offer, only_unique):
    set_offer_quantity(page, offer['id'], offer['quantity'])
    page.locator(f"#detailBShowOfferButton-{offer['id']}").click()
    form = page.locator('#detailCSectionForm')
    form.wait_for(state="visible", timeout=20000)
    page.wait_for_function("id => document.querySelector('#offerId')?.value === id", arg=offer['id'])

    quantity = int(offer['quantity'])
    quantity_selected = False

    # Prefer the exact quantity when the offer exposes it. If not possible,
    # fall back to a more permissive strategy: choose any available quantity and,
    # if the site still lets us continue, click Acquista anyway instead of
    # blocking the flow on a detailC mismatch.
    if form.locator('.js-ticketCount').count() > 0:
        try:
            ticket_count_text = form.locator('.js-ticketCount').first.inner_text()
            parsed_count = int(re.search(r"\d+", ticket_count_text).group())
            if parsed_count == quantity:
                quantity_selected = True
        except Exception:
            pass

    if not quantity_selected:
        for candidate_quantity in [quantity, 1, 2, 3]:
            if candidate_quantity <= 0:
                continue
            for selector in [
                f'input[name="tickets"][value="{candidate_quantity}"]',
                f'input[name="tickets"][data-value="{candidate_quantity}"]',
                f'input[name="tickets"][value="{candidate_quantity}"] + label',
                f'input[name="tickets"][value="{candidate_quantity}"] ~ label',
                f'[data-qa="ticketQty-{candidate_quantity}"]',
                f'button:has-text("{candidate_quantity}")',
                f'li[data-qa="{candidate_quantity}"]',
            ]:
                candidate = form.locator(selector)
                if candidate.count() == 0:
                    continue
                try:
                    candidate.first.click(timeout=5000)
                    quantity_selected = True
                    break
                except Exception:
                    pass
            if quantity_selected:
                break

    if not quantity_selected:
        container = page.locator(f"#numberOfTickets{offer['id']}-Container")
        if container.count() == 0:
            container = page.locator(f"#cnumberOfTickets{offer['id']}-Container")
        if container.count() > 0:
            try:
                container.locator('button').click(timeout=10000)
                for candidate_quantity in [1, quantity, 2, 3]:
                    if candidate_quantity <= 0:
                        continue
                    dropdown_item = container.locator(f'li[data-qa="{candidate_quantity}"]')
                    if dropdown_item.count() > 0:
                        dropdown_item.first.click(timeout=10000)
                        quantity_selected = True
                        break
            except Exception:
                pass

    if not quantity_selected:
        try:
            page.wait_for_function(
                "(n) => { const items = [...document.querySelectorAll('input[name=\"tickets\"]')]; return items.some(el => el.checked || el.value == String(n)); }",
                arg=quantity,
                timeout=15000,
            )
        except Exception:
            pass

    actual_checked = form.locator('input[name="tickets"]:checked').count()
    actual_ticket_count = None
    if form.locator('.js-ticketCount').count() > 0:
        try:
            actual_ticket_count = int(re.search(r"\d+", form.locator('.js-ticketCount').first.inner_text()).group())
        except Exception:
            actual_ticket_count = None

    resolved_count = actual_ticket_count if actual_ticket_count is not None else actual_checked
    if resolved_count and resolved_count != quantity:
        logging.warning(
            "Quantità finale non corrispondente al target (richiesto=%s, trovato=%s): procedo comunque con il checkout del fallback.",
            quantity,
            resolved_count,
        )

    detail_seat = text(page, '.js-DetailC-SeatDescription')
    if only_unique and normalized(detail_seat) != "posto unico":
        logging.warning("Categoria dettagli non corrispondente (target=%s, trovato=%s): procedo comunque.", "posto unico", detail_seat)
    total = text(form, '.js-totalPrice')
    numeric = re.sub(r"[^0-9,]", "", total).replace(",", ".")
    if not numeric:
        logging.warning("Prezzo totale non presente: procedo comunque con il checkout.")
    elif Decimal(numeric) != offer['price']:
        logging.warning(
            "Prezzo diverso da quello selezionato (target=%s, trovato=%s): procedo comunque.",
            offer['price'],
            Decimal(numeric),
        )
    return form.locator('[data-qa="buyNowButton"]')

def run(context):
    page = context.pages[0] if context.pages else context.new_page()
    if not page.url or page.url == "about:blank":
        page.goto("https://www.fansale.it", wait_until="domcontentloaded")
    event = choose_event(page)
    wanted = integer("Quantità desiderata [1]: ", "1")
    mode = integer("Preferenza: 1 Solo Posto Unico, 2 Più economico, 3 PIT, 4 Parterre/PIT (PIT se disponibile, altrimenti posto unico) [2]: ", "2")
    if mode not in (1, 2, 3, 4):
        raise RuntimeError("Modalità non valida")
    interval = integer("Intervallo refresh in secondi (minimo 30) [60]: ", "60", 30)
    if event.get("manual"):
        notify(f"Monitoraggio avviato — attendo la data richiesta:\n{event['title']} | {event['date']} | {event['city']}\nObiettivo: {wanted}")
        event_page_open = False
    else:
        notify(f"Data disponibile — {event['title']} | {event['date']} | {event['city']}\nBot pronto. Obiettivo: {wanted}; modalità reale")
        page.goto(event['url'], wait_until="domcontentloaded")
        event_page_open = True
    while True:
        if cart_present(page) or security_visible(page):
            raise RuntimeError("Carrello o controllo di sicurezza già aperto: intervento manuale necessario")
        page.wait_for_timeout(2500)
        if not event_page_open:
            available_event = matching_event_row(page, event)
            if available_event:
                notify(f"Data disponibile — {available_event['title']} | {available_event['date']} | {available_event['city']}")
                page.goto(available_event['url'], wait_until="domcontentloaded")
                event_page_open = True
                continue
        offers = offers_from_page(page, wanted, mode)
        if offers:
            offer = offers[0]
            notify(f"Biglietti disponibili — {event['title']} | {event['date']} | {event['city']}\nQuantità disponibile: {offer['quantity']}/{wanted}\nSto verificando il carrello.")
            button = prepare_offer(page, offer, mode == 1)
            page.wait_for_timeout(800)
            # The final buy button sometimes becomes clickable slightly later than the DOM is ready.
            # Keep a small delay and retry before deciding the click is impossible.
            if not click_any(page, button, timeout=15000):
                raise RuntimeError("Impossibile attivare il click su Acquista: il pulsante non è cliccabile o è nascosto da un overlay.")
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                info = cart_info(page, event, offer['quantity'])
                if info:
                    notify(f"Biglietti riservati nel carrello\nQuantità: {offer['quantity']}/{wanted}\n{info}\nCompleta l'acquisto nel browser lasciato aperto su questo computer. Il link da solo non trasferisce la sessione.")
                    return
                page.wait_for_timeout(1000)
            raise RuntimeError("Esito non confermato entro 90 secondi. Controlla il browser; nessun nuovo tentativo automatico.")
        logging.info("Nessuna offerta compatibile; prossimo controllo tra %s secondi", interval)
        page.wait_for_timeout(interval * 1000)
        response = page.reload(wait_until="domcontentloaded")
        if response and response.status >= 400:
            raise RuntimeError(f"HTTP {response.status}: monitoraggio sospeso")

def find_chrome_executable():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    user_dir = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe"
    if user_dir.exists():
        candidates.insert(0, str(user_dir))
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    raise RuntimeError("Chrome/Edge non trovato. Installa Google Chrome o Microsoft Edge e riavvia il bot.")


def launch_real_browser(profile_root: Path, port: int = 9222):
    profile_root.mkdir(parents=True, exist_ok=True)
    user_data_dir = profile_root / "user-data"
    user_data_dir.mkdir(parents=True, exist_ok=True)

    chrome_path = find_chrome_executable()
    chrome_args = [
        chrome_path,
        f"--user-data-dir={user_data_dir}",
        "--profile-directory=Default",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "about:blank",
    ]
    subprocess.Popen(chrome_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
            if response.ok:
                return port
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Chrome reale non risponde su localhost:{port}. Controlla che il browser venga aperto correttamente.")


def main():
    profile_root = Path('browser-profile').resolve()
    with sync_playwright() as p:
        port = launch_real_browser(profile_root)
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        context = browser.contexts[0] if browser.contexts else browser.new_context(no_viewport=True)
        try:
            run(context)
        except KeyboardInterrupt:
            logging.info("Interrotto dall'utente")
        except Exception as exc:
            logging.error("Bot sospeso: %s", exc)
            try:
                notify(f"Bot sospeso: {exc}\nControlla il browser. Non verranno eseguiti altri click.")
            except Exception:
                logging.error("Notifica non consegnata: controlla il browser e la console")
        finally:
            try:
                input("Automazione ferma. Premi INVIO solo dopo aver finito di usare il browser: ")
            except (KeyboardInterrupt, EOFError):
                pass
            try:
                context.close()
            except Exception:
                pass

if __name__ == '__main__':
    main()
