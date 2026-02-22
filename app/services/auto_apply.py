"""
Auto Apply Service - Playwright automation per candidature HelpLavoro
"""
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeout

from ..core.config import get_settings
from ..models.application import Application, ApplicationStatus
from .cv_loader import get_cv_loader
from .blob_uploader import get_blob_uploader

settings = get_settings()

# Screenshot steps by mode
_SCREENSHOT_STEPS = {
    "all": {"step0_page_loaded", "step1_after_rispondi", "step2_form_visible", 
            "before_submit", "success", "after_submit", "error",
            "error_no_rispondi_button", "error_no_candidatura_diretta"},
    "minimal": {"before_submit", "success", "after_submit", "error",
                "error_no_rispondi_button", "error_no_candidatura_diretta"},
    "errors": {"error", "error_no_rispondi_button", "error_no_candidatura_diretta", "after_submit"},
}


def _should_take_screenshot(suffix: str) -> bool:
    """Check if screenshot should be taken based on screenshot_mode"""
    if not settings.save_screenshots:
        return False
    mode = settings.screenshot_mode
    allowed = _SCREENSHOT_STEPS.get(mode, _SCREENSHOT_STEPS["all"])
    return suffix in allowed


class AutoApplyService:
    """Servizio per automatizzare candidature su HelpLavoro"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.cv_loader = get_cv_loader()
        
        # Crea directory screenshots se non esiste
        if settings.save_screenshots:
            Path(settings.screenshots_path).mkdir(parents=True, exist_ok=True)
    
    async def start_browser(self):
        """Avvia il browser Playwright"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=settings.headless,
                slow_mo=settings.slow_mo
            )
            print(f"[AUTOAPPLY] Browser started (headless={settings.headless})", flush=True)
        except Exception as e:
            print(f"[AUTOAPPLY] Failed to start browser: {type(e).__name__}: {e}", flush=True)
            raise e
    
    async def stop_browser(self):
        """Chiude il browser"""
        if self.browser:
            await self.browser.close()
            await self.playwright.stop()
            print("[AUTOAPPLY] Browser stopped", flush=True)
    
    async def apply_to_job(self, application: Application) -> Application:
        """
        Esegue la candidatura per un singolo job.
        
        Args:
            application: Application record con tutti i dati
            
        Returns:
            Application aggiornata con status/error
        """
        application.status = ApplicationStatus.PROCESSING
        application.started_at = datetime.now()
        application.attempts += 1
        
        print(f"[AUTOAPPLY] Processing: {application.job_url}", flush=True)
        print(f"[AUTOAPPLY] Candidate: {application.candidate_nome} {application.candidate_cognome} ({application.candidate_email})", flush=True)
        
        page = None
        try:
            # Crea nuova pagina
            page = await self.browser.new_page()
            await page.set_viewport_size({"width": 1280, "height": 800})
            
            # Naviga alla pagina del job
            print(f"[AUTOAPPLY] Navigating to job page...", flush=True)
            await page.goto(application.job_url, wait_until="domcontentloaded", timeout=settings.timeout)
            
            # Attendi che gli script async (CMP, ads) si carichino
            await asyncio.sleep(1)
            
            # Gestisci cookie/consent banner se presente
            await self._handle_cookie_banner(page)
            
            # Screenshot iniziale
            if _should_take_screenshot("step0_page_loaded"):
                await self._take_screenshot(page, application, "step0_page_loaded")
            
            # Estrai info job se non presenti
            if not application.job_title:
                application.job_title = await self._extract_job_title(page)
            if not application.company_name:
                application.company_name = await self._extract_company_name(page)
            
            print(f"[AUTOAPPLY] Job: {application.job_title} @ {application.company_name}", flush=True)
            
            # STEP 1: Clicca "Rispondi all'offerta" o "CANDIDATI SUBITO"
            print(f"[AUTOAPPLY] Step 1: Looking for 'Rispondi all'offerta' button...", flush=True)
            
            rispondi_button = await self._find_rispondi_button(page)
            if not rispondi_button:
                if _should_take_screenshot("error_no_rispondi_button"):
                    application.screenshot_path = await self._take_screenshot(page, application, "error_no_rispondi_button")
                application.status = ApplicationStatus.SKIPPED
                application.error_message = "Rispondi all'offerta button not found"
                print(f"[AUTOAPPLY] ⚠️ 'Rispondi all'offerta' button not found, skipping", flush=True)
                return application
            
            await rispondi_button.click()
            print(f"[AUTOAPPLY] Clicked 'Rispondi all'offerta'", flush=True)
            await asyncio.sleep(0.5)  # Attendi popup
            
            # Screenshot dopo click
            if _should_take_screenshot("step1_after_rispondi"):
                await self._take_screenshot(page, application, "step1_after_rispondi")
            
            # STEP 2: Clicca "Candidatura diretta" nel popup
            print(f"[AUTOAPPLY] Step 2: Looking for 'Candidatura diretta' option...", flush=True)
            
            candidatura_diretta = await self._find_candidatura_diretta(page)
            if not candidatura_diretta:
                if _should_take_screenshot("error_no_candidatura_diretta"):
                    application.screenshot_path = await self._take_screenshot(page, application, "error_no_candidatura_diretta")
                application.status = ApplicationStatus.SKIPPED
                application.error_message = "Candidatura diretta option not found"
                print(f"[AUTOAPPLY] ⚠️ 'Candidatura diretta' option not found, skipping", flush=True)
                return application
            
            await candidatura_diretta.click()
            print(f"[AUTOAPPLY] Clicked 'Candidatura diretta'", flush=True)
            await asyncio.sleep(1.0)  # Attendi apertura collapse Bootstrap
            
            # Wait for form to be fully visible
            try:
                await page.wait_for_selector("#frmOfferta input[name='nome']", state="visible", timeout=5000)
                print(f"[AUTOAPPLY] Form fields are now visible", flush=True)
            except:
                print(f"[AUTOAPPLY] ⚠️ Form fields visibility check timed out, proceeding anyway", flush=True)
            
            # Screenshot dopo candidatura diretta
            if _should_take_screenshot("step2_form_visible"):
                await self._take_screenshot(page, application, "step2_form_visible")
            
            # Compila il form
            print(f"[AUTOAPPLY] Filling application form...", flush=True)
            await self._fill_application_form(page, application)
            
            # Screenshot prima dell'invio
            if _should_take_screenshot("before_submit"):
                screenshot_path = await self._take_screenshot(page, application, "before_submit")
            
            # DRY RUN MODE - non inviare realmente
            if settings.dry_run:
                print(f"[AUTOAPPLY] 🧪 DRY RUN MODE - Skipping actual submit", flush=True)
                application.status = ApplicationStatus.SUCCESS
                application.error_message = "DRY RUN - Form filled but not submitted"
                if _should_take_screenshot("before_submit"):
                    application.screenshot_path = screenshot_path
                print(f"[AUTOAPPLY] ✅ DRY RUN completed successfully!", flush=True)
                return application
            
            # Invia candidatura
            print(f"[AUTOAPPLY] Submitting application...", flush=True)
            await self._submit_application(page)
            
            # Cleanup temp CV file after submit
            self._cleanup_temp_cv()
            
            # Attendi conferma (fetch already got the response)
            await asyncio.sleep(0.5)
            
            # Verifica successo
            success = await self._verify_submission(page)
            
            # Screenshot dopo l'invio (cattura il popup di successo/errore)
            if success and _should_take_screenshot("success"):
                await asyncio.sleep(1)
                application.screenshot_path = await self._take_screenshot(page, application, "success")
                print(f"[AUTOAPPLY] 📸 Success screenshot saved", flush=True)
            elif not success and _should_take_screenshot("after_submit"):
                application.screenshot_path = await self._take_screenshot(page, application, "after_submit")
            
            if success:
                application.status = ApplicationStatus.SUCCESS
                print(f"[AUTOAPPLY] ✅ Application submitted successfully!", flush=True)
            else:
                application.status = ApplicationStatus.FAILED
                application.error_message = "Submission verification failed"
                print(f"[AUTOAPPLY] ❌ Submission verification failed", flush=True)
            
        except PlaywrightTimeout as e:
            application.status = ApplicationStatus.FAILED
            application.error_message = f"Timeout: {str(e)}"
            print(f"[AUTOAPPLY] ❌ Timeout error: {e}", flush=True)
            
        except Exception as e:
            application.status = ApplicationStatus.FAILED
            application.error_message = f"{type(e).__name__}: {str(e)}"
            print(f"[AUTOAPPLY] ❌ Error: {type(e).__name__}: {e}", flush=True)
            
            # Screenshot dell'errore
            if _should_take_screenshot("error") and page:
                try:
                    await self._take_screenshot(page, application, "error")
                except:
                    pass
        
        finally:
            application.completed_at = datetime.now()
            if page:
                await page.close()
        
        return application
    
    async def _extract_job_title(self, page: Page) -> Optional[str]:
        """Estrae il titolo del job dalla pagina"""
        selectors = [
            "h1.job-title",
            "h1",
            ".titolo-offerta",
            "[class*='title']"
        ]
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    if text and len(text) > 3:
                        return text.strip()[:200]
            except:
                continue
        return None
    
    async def _extract_company_name(self, page: Page) -> Optional[str]:
        """Estrae il nome dell'azienda dalla pagina"""
        selectors = [
            ".azienda",
            ".company-name",
            "[class*='company']",
            "[class*='azienda']"
        ]
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    text = await element.inner_text()
                    if text and len(text) > 2:
                        return text.strip()[:200]
            except:
                continue
        return None
    
    async def _handle_cookie_banner(self, page: Page):
        """Accetta i cookie/consent se presente il banner - gestisce Google Funding Choices CMP + Snigel"""
        
        # === 1. Google Funding Choices CMP (fc-consent-root) ===
        # Questo è il consent manager principale su HelpLavoro.it
        # Carica async via fundingchoicesmessages.google.com, può impiegare diversi secondi
        try:
            print(f"[AUTOAPPLY] Waiting for Google FC consent dialog...", flush=True)
            fc_dialog = await page.wait_for_selector(
                "div.fc-consent-root .fc-dialog",
                state="visible",
                timeout=3000
            )
            if fc_dialog:
                print(f"[AUTOAPPLY] Google Funding Choices consent dialog detected", flush=True)
                
                # Cerca il bottone "Accetta tutto" / "Consent" (è il primary button)
                fc_accept_selectors = [
                    "div.fc-consent-root .fc-primary-button",
                    "div.fc-consent-root .fc-cta-consent",
                    "div.fc-consent-root button.fc-primary-button",
                    "div.fc-consent-root .fc-button-label",
                ]
                
                for sel in fc_accept_selectors:
                    try:
                        btn = await page.wait_for_selector(sel, state="visible", timeout=3000)
                        if btn:
                            await btn.click(force=True)
                            print(f"[AUTOAPPLY] Clicked FC consent: {sel}", flush=True)
                            await asyncio.sleep(2)
                            
                            # Verifica che il dialog sia scomparso
                            try:
                                await page.wait_for_selector(
                                    "div.fc-consent-root",
                                    state="hidden",
                                    timeout=5000
                                )
                                print(f"[AUTOAPPLY] FC consent dialog dismissed", flush=True)
                            except:
                                # Prova a rimuoverlo via JS come fallback
                                await page.evaluate("document.querySelector('div.fc-consent-root')?.remove()")
                                await page.evaluate("document.body.style.overflow = 'auto'")
                                print(f"[AUTOAPPLY] FC consent removed via JS fallback", flush=True)
                            return
                    except:
                        continue
                
                # Se nessun bottone trovato, rimuovi forzatamente il dialog
                print(f"[AUTOAPPLY] No FC button found, removing dialog via JS", flush=True)
                await page.evaluate("document.querySelector('div.fc-consent-root')?.remove()")
                await page.evaluate("document.body.style.overflow = 'auto'")
                return
        except Exception as e:
            print(f"[AUTOAPPLY] No Google FC dialog found ({type(e).__name__}), trying other methods...", flush=True)
        
        # === 2. Snigel CMP (#snigel-cmp-framework) ===
        try:
            snigel_banner = await page.wait_for_selector(
                "#snigel-cmp-framework",
                state="visible",
                timeout=3000
            )
            if snigel_banner:
                print(f"[AUTOAPPLY] Snigel CMP banner detected", flush=True)
                accept_btn = await page.wait_for_selector(
                    "#accept-choices",
                    state="visible",
                    timeout=3000
                )
                if accept_btn:
                    await accept_btn.click(force=True)
                    print(f"[AUTOAPPLY] Clicked #accept-choices", flush=True)
                    await asyncio.sleep(2)
                    return
        except:
            pass
        
        # === 3. Fallback generico ===
        cookie_selectors = [
            "#accept-choices",
            ".sn-b-def.sn-blue",
            "button:has-text('Accetta')",
            "button:has-text('Accept')",
            "button:has-text('Accetto')",
            "button:has-text('OK')",
            "button:has-text('Accetta tutti')",
            "button:has-text('Accept all')",
            "a:has-text('Accetta')",
            "a:has-text('Accept')",
            ".cookie-accept",
            "#cookie-accept",
        ]
        
        for selector in cookie_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    await element.click(force=True)
                    print(f"[AUTOAPPLY] Accepted cookies: {selector}", flush=True)
                    await asyncio.sleep(1.5)
                    return
            except:
                continue
        
        # === 4. Ultima risorsa: rimuovi qualsiasi overlay noto via JS ===
        try:
            removed = await page.evaluate("""() => {
                let removed = [];
                // FC consent
                const fc = document.querySelector('div.fc-consent-root');
                if (fc) { fc.remove(); removed.push('fc-consent-root'); }
                // Snigel
                const sn = document.querySelector('#snigel-cmp-framework');
                if (sn) { sn.remove(); removed.push('snigel-cmp'); }
                // Ripristina scroll
                document.body.style.overflow = 'auto';
                document.body.style.overflowY = 'auto';
                return removed;
            }""")
            if removed:
                print(f"[AUTOAPPLY] Removed overlays via JS: {removed}", flush=True)
                await asyncio.sleep(1)
                return
        except:
            pass
        
        print(f"[AUTOAPPLY] No cookie/consent banner found or already accepted", flush=True)

    async def _find_rispondi_button(self, page: Page):
        """Trova il bottone 'Rispondi all'offerta' o 'CANDIDATI SUBITO'"""
        selectors = [
            # Selettore esatto da HelpLavoro
            "a.btn-inviacandidatura",
            "a[data-target='#modalInviaCandidatura']",
            ".btn-inviacandidatura",
            # Fallback
            "a:has-text('Rispondi all\\'offerta')",
            "button:has-text('Rispondi all\\'offerta')",
            "a:has-text('CANDIDATI SUBITO')",
            "button:has-text('CANDIDATI SUBITO')",
            "a:has-text('Candidati subito')",
        ]
        
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    return element
            except:
                continue
        
        return None
    
    async def _find_candidatura_diretta(self, page: Page):
        """Trova l'opzione 'Candidatura diretta' nel popup"""
        selectors = [
            # Selettore esatto da HelpLavoro
            "a[href='#collapseDiretta']",
            "a[aria-controls='collapseDiretta']",
            ".label-login:has-text('Candidatura diretta')",
            # Fallback
            "text=Candidatura diretta",
            "a:has-text('Candidatura diretta')",
            "div:has-text('Candidatura diretta')",
        ]
        
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    return element
            except:
                continue
        
        return None

    async def _find_apply_button(self, page: Page):
        """Trova il bottone di candidatura"""
        selectors = [
            "a:has-text('Candidati')",
            "button:has-text('Candidati')",
            "a:has-text('Invia CV')",
            "button:has-text('Invia CV')",
            "a:has-text('Applica')",
            ".btn-candidati",
            "[class*='apply']",
            "a[href*='candidati']",
        ]
        
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    return element
            except:
                continue
        
        return None
    
    async def _is_form_visible(self, page: Page) -> bool:
        """Verifica se il form di candidatura è già visibile nella pagina"""
        # Cerca campi tipici del form
        form_indicators = [
            "input[name*='nome']",
            "input[name*='cognome']",
            "input[name*='email']",
            "button:has-text('Invia candidatura')",
            "input[type='file']",
        ]
        
        for selector in form_indicators:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    print(f"[AUTOAPPLY] Found form indicator: {selector}", flush=True)
                    return True
            except:
                continue
        
        return False
    
    async def _fill_application_form(self, page: Page, application: Application):
        """Compila il form di candidatura HelpLavoro"""
        
        # All selectors are scoped to #frmOfferta to avoid matching login modal fields
        FORM = "#frmOfferta"
        
        # Nome
        await self._fill_field(page, [f"{FORM} input[name='nome']", "input[name*='nome']"], application.candidate_nome)
        
        # Cognome
        await self._fill_field(page, [f"{FORM} input[name='cognome']", "input[name*='cognome']"], application.candidate_cognome)
        
        # Email - scoped to form to avoid matching login modal email fields
        await self._fill_field(page, [f"{FORM} input[name='email']", f"{FORM} input[type='email']"], application.candidate_email)
        
        # Sesso (radio button) - HelpLavoro uses value="1" for Maschio, value="2" for Femmina
        if application.candidate_sesso == "M":
            await self._click_radio(page, ["#sessoM", f"{FORM} input[name='sesso'][value='1']", "input[value='M']"])
        else:
            await self._click_radio(page, ["#sessoF", f"{FORM} input[name='sesso'][value='2']", "input[value='F']"])
        
        # Data di nascita - HelpLavoro has a visible datepicker (#datanascita) and a hidden field (#hiddendatanascita)
        # The visible field uses dd/mm/yyyy format, the hidden field uses yyyy-mm-dd
        await self._fill_date_nascita(page, application.candidate_data_nascita)
        
        # Comune - uses jQuery typeahead, must type and select from dropdown
        await self._fill_comune_typeahead(page, application.candidate_comune)
        
        # Indirizzo (opzionale)
        if application.candidate_indirizzo:
            await self._fill_field(page, [f"{FORM} input[name='indirizzo']", "#indirizzo"], application.candidate_indirizzo)
        
        # CAP
        await self._fill_field(page, [f"{FORM} input[name='cap']", "input[name*='cap']"], application.candidate_cap)
        
        # Telefono
        await self._fill_field(page, [f"{FORM} input[name='cellulare']", f"{FORM} input[type='tel']", "input[name*='cellulare']"], application.candidate_telefono)
        
        # Studi (dropdown)
        await self._select_dropdown(page, [f"{FORM} select[name='studi']", "#studi"], application.candidate_studi)
        
        # Occupazione attuale (dropdown)
        await self._select_dropdown(page, [f"{FORM} select[name='occupazione']", "#occupazione"], application.candidate_occupazione)
        
        # Area di competenza (dropdown)
        await self._select_dropdown(page, [f"{FORM} select[name='area']", "#area", "select[name*='area']"], application.candidate_area_competenza)
        
        # Presentazione (textarea)
        if application.candidate_presentazione:
            await self._fill_field(page, [f"{FORM} textarea[name='presentazione']", "#presentazione_offerta", "textarea[name*='presentazione']"], application.candidate_presentazione)
        
        # Upload CV
        await self._upload_cv(page, application.cv_reference)
        
        # Privacy/consenso checkbox (obbligatorio) - field name is "consenso" on HelpLavoro
        if application.accetto_privacy:
            await self._check_checkbox(page, [f"{FORM} input[name='consenso']", "#consenso", "input[name*='consenso']"])
        
        # Marketing radio (consensonl) - HelpLavoro uses name="consensonl"
        if application.accetto_marketing:
            await self._click_radio(page, ["#consensonlA", f"{FORM} input[name='consensonl'][value='1']"])
        else:
            await self._click_radio(page, ["#consensonlN", f"{FORM} input[name='consensonl'][value='0']"])
        
        # Terze parti radio (consensoterzi) - HelpLavoro uses name="consensoterzi"
        if application.accetto_terze_parti:
            await self._click_radio(page, ["#consensoterziA", f"{FORM} input[name='consensoterzi'][value='1']"])
        else:
            await self._click_radio(page, ["#consensoterziN", f"{FORM} input[name='consensoterzi'][value='0']"])
        
        # Banca dati / deposito CV radio - HelpLavoro uses name="deposito"
        if application.accetto_banca_dati:
            await self._click_radio(page, ["#depositoA", f"{FORM} input[name='deposito'][value='1']"])
        else:
            await self._click_radio(page, ["#depositoN", f"{FORM} input[name='deposito'][value='0']"])
    
    async def _fill_date_nascita(self, page: Page, data_nascita: str):
        """Fill the birth date field on HelpLavoro.
        
        HelpLavoro has a visible datepicker input (#datanascita) and a hidden field (#hiddendatanascita).
        The datepicker triggers dp.change event to populate the hidden field.
        We fill both and trigger the event.
        
        Accepts data_nascita in formats: dd/mm/yyyy, yyyy-mm-dd, or similar.
        """
        try:
            # Normalize date format
            date_display = data_nascita  # dd/mm/yyyy for visible field
            date_hidden = data_nascita   # yyyy-mm-dd for hidden field
            
            if "-" in data_nascita and len(data_nascita) == 10:
                # Input is yyyy-mm-dd, convert to dd/mm/yyyy for display
                parts = data_nascita.split("-")
                date_display = f"{parts[2]}/{parts[1]}/{parts[0]}"
                date_hidden = data_nascita
            elif "/" in data_nascita and len(data_nascita) == 10:
                # Input is dd/mm/yyyy, convert to yyyy-mm-dd for hidden
                parts = data_nascita.split("/")
                date_hidden = f"{parts[2]}-{parts[1]}-{parts[0]}"
                date_display = data_nascita
            
            # Fill the visible datepicker input
            datepicker = await page.query_selector("#datanascita")
            if datepicker:
                await datepicker.fill(date_display)
                print(f"[AUTOAPPLY] Filled #datanascita: {date_display}", flush=True)
            else:
                # Fallback: try other selectors
                datepicker = await page.query_selector("#frmOfferta input.datepicker")
                if datepicker:
                    await datepicker.fill(date_display)
                    print(f"[AUTOAPPLY] Filled datepicker: {date_display}", flush=True)
            
            # Fill the hidden field directly
            hidden = await page.query_selector("#hiddendatanascita")
            if hidden:
                await hidden.evaluate(f'(el) => {{ el.value = "{date_hidden}"; }}')
                print(f"[AUTOAPPLY] Set #hiddendatanascita: {date_hidden}", flush=True)
            else:
                # Fallback: try name-based selector
                hidden = await page.query_selector("#frmOfferta input[name='datanascita']")
                if hidden:
                    await hidden.evaluate(f'(el) => {{ el.value = "{date_hidden}"; }}')
                    print(f"[AUTOAPPLY] Set input[name='datanascita']: {date_hidden}", flush=True)
            
            # Trigger change event on datepicker to sync with any JS handlers
            if datepicker:
                await datepicker.dispatch_event("change")
                await datepicker.dispatch_event("blur")
                
        except Exception as e:
            print(f"[AUTOAPPLY] ⚠️ Error filling date: {e}", flush=True)
    
    async def _fill_comune_typeahead(self, page: Page, comune_value: str):
        """Fill the Comune field which uses jQuery typeahead autocomplete.
        Must type characters, wait for dropdown, then click matching option."""
        try:
            selector = "#comune"
            element = await page.query_selector(selector)
            if not element or not await element.is_visible():
                selector = "input[name='comune']"
                element = await page.query_selector(selector)
            
            if not element:
                print(f"[AUTOAPPLY] ⚠️ Could not find Comune field", flush=True)
                return
            
            # Clear any existing value
            await element.click()
            await element.fill("")
            await asyncio.sleep(0.3)
            
            # Type the first 3+ chars to trigger typeahead
            search_text = comune_value[:4] if len(comune_value) > 3 else comune_value
            await element.type(search_text, delay=100)
            print(f"[AUTOAPPLY] Typed '{search_text}' in Comune field, waiting for typeahead...", flush=True)
            
            # Wait for typeahead dropdown to appear
            dropdown_found = False
            for attempt in range(10):
                await asyncio.sleep(0.5)
                # Check for typeahead dropdown items
                items = await page.query_selector_all("ul.typeahead.dropdown-menu li")
                visible_items = []
                for item in items:
                    if await item.is_visible():
                        visible_items.append(item)
                
                if visible_items:
                    dropdown_found = True
                    print(f"[AUTOAPPLY] Typeahead dropdown appeared with {len(visible_items)} items", flush=True)
                    
                    # Try to find exact match first, then partial match
                    clicked = False
                    for item in visible_items:
                        item_text = await item.inner_text()
                        if item_text.strip().lower() == comune_value.lower():
                            await item.click()
                            print(f"[AUTOAPPLY] Clicked exact match: '{item_text.strip()}'", flush=True)
                            clicked = True
                            break
                    
                    if not clicked:
                        # Click first item that contains the comune name
                        for item in visible_items:
                            item_text = await item.inner_text()
                            if comune_value.lower() in item_text.strip().lower():
                                await item.click()
                                print(f"[AUTOAPPLY] Clicked partial match: '{item_text.strip()}'", flush=True)
                                clicked = True
                                break
                    
                    if not clicked:
                        # Just click the first item
                        first_text = await visible_items[0].inner_text()
                        await visible_items[0].click()
                        print(f"[AUTOAPPLY] Clicked first available: '{first_text.strip()}'", flush=True)
                    
                    break
            
            if not dropdown_found:
                print(f"[AUTOAPPLY] ⚠️ Typeahead dropdown did not appear, trying JS fallback", flush=True)
                # Fallback: set value via JS and trigger the needed events
                await page.evaluate(f"""() => {{
                    const el = document.querySelector('#comune');
                    if (el) {{
                        el.value = '{comune_value}';
                        $(el).data('defaultComune', '{comune_value}');
                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                        el.dispatchEvent(new Event('blur', {{bubbles: true}}));
                    }}
                }}""")
                print(f"[AUTOAPPLY] Set Comune via JS fallback: {comune_value}", flush=True)
            
            await asyncio.sleep(0.5)
            
            # Verify the field has a value
            final_value = await page.evaluate("() => document.querySelector('#comune')?.value || ''")
            print(f"[AUTOAPPLY] Comune field final value: '{final_value}'", flush=True)
            
        except Exception as e:
            print(f"[AUTOAPPLY] ⚠️ Error filling Comune: {e}", flush=True)

    async def _fill_field(self, page: Page, selectors: list, value: str):
        """Compila un campo cercando tra diversi selettori"""
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    await element.fill(value)
                    print(f"[AUTOAPPLY] Filled field: {selector}", flush=True)
                    return
            except:
                continue
        print(f"[AUTOAPPLY] ⚠️ Could not find field for: {selectors[0]}", flush=True)
    
    async def _click_radio(self, page: Page, selectors: list):
        """Clicca un radio button cercando tra diversi selettori"""
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    # Radio buttons may be styled/hidden, use force click
                    try:
                        await element.click(force=True)
                    except:
                        # Fallback: use JavaScript to click
                        await element.evaluate('(el) => el.click()')
                    print(f"[AUTOAPPLY] Clicked radio: {selector}", flush=True)
                    return
            except:
                continue
        print(f"[AUTOAPPLY] ⚠️ Could not find radio for: {selectors[0]}", flush=True)
    
    async def _check_checkbox(self, page: Page, selectors: list):
        """Spunta un checkbox cercando tra diversi selettori"""
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    if not await element.is_checked():
                        try:
                            await element.check(force=True)
                        except:
                            await element.evaluate('(el) => { el.checked = true; el.dispatchEvent(new Event("change")); }')
                    print(f"[AUTOAPPLY] Checked: {selector}", flush=True)
                    return
            except:
                continue
        print(f"[AUTOAPPLY] ⚠️ Could not find checkbox for: {selectors[0]}", flush=True)
    
    async def _select_dropdown(self, page: Page, selectors: list, value: str):
        """Seleziona un'opzione da dropdown - ottimizzato per velocità via JS"""
        for selector in selectors:
            try:
                element = await page.query_selector(selector)
                if element and await element.is_visible():
                    # Direct JS selection - fastest approach
                    result = await page.evaluate("""(args) => {
                        const [sel, val] = args;
                        const select = document.querySelector(sel);
                        if (!select) return null;
                        const valLower = val.toLowerCase();
                        // Try exact value match first
                        for (let opt of select.options) {
                            if (opt.value === val || opt.text === val) {
                                select.value = opt.value;
                                select.dispatchEvent(new Event('change', {bubbles: true}));
                                return opt.text;
                            }
                        }
                        // Then partial match
                        for (let opt of select.options) {
                            if (opt.text.toLowerCase().includes(valLower)) {
                                select.value = opt.value;
                                select.dispatchEvent(new Event('change', {bubbles: true}));
                                return opt.text;
                            }
                        }
                        return null;
                    }""", [selector, value])
                    
                    if result:
                        print(f"[AUTOAPPLY] Selected dropdown {selector} partial match: {result}", flush=True)
                        return
            except:
                continue
        print(f"[AUTOAPPLY] ⚠️ Could not find/select dropdown for: {selectors[0]} with value: {value}", flush=True)
    
    async def _upload_cv(self, page: Page, cv_reference: str):
        """Carica il CV nel form"""
        file_selectors = [
            "input[type='file']",
            "input[name*='cv']",
            "input[name*='curriculum']",
            "input[accept*='pdf']"
        ]
        
        # Carica il contenuto del CV
        cv_content, cv_filename = self.cv_loader.load(cv_reference)
        
        # Salva temporaneamente il file - NON cancellare prima del submit!
        # Il file deve esistere quando il form fa POST con multipart/form-data
        temp_path = Path(settings.screenshots_path) / f"temp_{cv_filename}"
        with open(temp_path, 'wb') as f:
            f.write(cv_content)
        
        # Store temp path for cleanup after submit
        self._temp_cv_path = temp_path
        
        for selector in file_selectors:
            try:
                file_input = await page.query_selector(selector)
                if file_input:
                    await file_input.set_input_files(str(temp_path))
                    print(f"[AUTOAPPLY] Uploaded CV: {cv_filename}", flush=True)
                    return
            except:
                continue
        print(f"[AUTOAPPLY] ⚠️ Could not find file upload field", flush=True)
    
    def _cleanup_temp_cv(self):
        """Remove temporary CV file after submit"""
        if hasattr(self, '_temp_cv_path') and self._temp_cv_path and self._temp_cv_path.exists():
            os.remove(self._temp_cv_path)
            self._temp_cv_path = None
    

    
    async def _submit_application(self, page: Page):
        """Invia il form di candidatura via JavaScript fetch (evita navigazione browser)"""
        
        # First, trigger jQuery validation and add the encodedpresentazione field
        # exactly like the original submitHandler does
        validation_result = await page.evaluate("""() => {
            // Add encodedpresentazione hidden field like the original handler
            var input = $("<input>").attr("type", "hidden").attr("name", "encodedpresentazione")
                .val(escape($(document.getElementById("presentazione_offerta")).val()));
            $("#frmOfferta").append($(input));
            
            // Check if form is valid
            if ($("#frmOfferta").valid()) {
                return { valid: true };
            } else {
                return { valid: false, errors: $("#frmOfferta").validate().errorList.map(e => e.message) };
            }
        }""")
        
        print(f"[AUTOAPPLY] Form validation result: {validation_result}", flush=True)
        
        if not validation_result.get('valid'):
            print(f"[AUTOAPPLY] ❌ Form validation failed: {validation_result.get('errors')}", flush=True)
            return
        
        # Submit via fetch to avoid browser navigation issues
        submit_result = await page.evaluate("""() => {
            return new Promise((resolve) => {
                var form = document.getElementById('frmOfferta');
                var formData = new FormData(form);
                var actionUrl = form.getAttribute('action') || '';
                
                // Ensure absolute URL
                if (!actionUrl.startsWith('http')) {
                    actionUrl = window.location.origin + actionUrl;
                }
                
                fetch(actionUrl, {
                    method: 'POST',
                    body: formData,
                    credentials: 'same-origin'
                })
                .then(response => {
                    return response.text().then(text => {
                        resolve({
                            ok: response.ok,
                            status: response.status,
                            statusText: response.statusText,
                            url: response.url,
                            bodyLength: text.length,
                            bodyPreview: text.substring(0, 500),
                            hasGrazie: text.toLowerCase().includes('grazie'),
                            hasConferm: text.toLowerCase().includes('conferm'),
                            hasErrore: text.toLowerCase().includes('errore'),
                            hasInviata: text.toLowerCase().includes('inviata')
                        });
                    });
                })
                .catch(error => {
                    resolve({ ok: false, error: error.toString() });
                });
            });
        }""")
        
        print(f"[AUTOAPPLY] Submit response: status={submit_result.get('status')}, ok={submit_result.get('ok')}, bodyLength={submit_result.get('bodyLength')}", flush=True)
        print(f"[AUTOAPPLY] Response URL: {submit_result.get('url')}", flush=True)
        
        if submit_result.get('bodyPreview'):
            print(f"[AUTOAPPLY] Response preview: {submit_result.get('bodyPreview', '')[:300]}", flush=True)
        
        if submit_result.get('error'):
            print(f"[AUTOAPPLY] ❌ Submit error: {submit_result.get('error')}", flush=True)
        
        # Store result for verification
        self._submit_result = submit_result
    
    async def _verify_submission(self, page: Page) -> bool:
        """Verifica che la candidatura sia stata inviata"""
        # Check fetch result if available
        if hasattr(self, '_submit_result') and self._submit_result:
            result = self._submit_result
            if result.get('ok') and result.get('status') == 200:
                # Check for success indicators in response
                if result.get('hasGrazie') or result.get('hasConferm') or result.get('hasInviata'):
                    print(f"[AUTOAPPLY] ✅ Server response contains success indicator", flush=True)
                    return True
                # Even without success keywords, 200 OK is likely success
                print(f"[AUTOAPPLY] ✅ Server responded 200 OK (bodyLength={result.get('bodyLength')})", flush=True)
                return True
            elif result.get('error'):
                print(f"[AUTOAPPLY] ❌ Submit had error: {result.get('error')}", flush=True)
                return False
            elif result.get('hasErrore'):
                print(f"[AUTOAPPLY] ❌ Server response contains error indicator", flush=True)
                return False
        
        # Fallback: check page content
        try:
            success_indicators = ["grazie", "thank", "ricevuta", "conferm", "success", "inviata"]
            content = await page.content()
            content_lower = content.lower()
            for indicator in success_indicators:
                if indicator in content_lower:
                    print(f"[AUTOAPPLY] ✅ Success indicator in page: '{indicator}'", flush=True)
                    return True
        except:
            pass
        
        print(f"[AUTOAPPLY] ⚠️ Could not verify submission", flush=True)
        return False
    
    async def _take_screenshot(self, page: Page, application: Application, suffix: str) -> str:
        """Salva uno screenshot e l'HTML della pagina, opzionalmente uploada su Blob"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"app_{application.id}_{suffix}_{timestamp}"
        
        # Salva screenshot localmente
        screenshot_path = Path(settings.screenshots_path) / f"{base_filename}.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"[AUTOAPPLY] Screenshot saved: {base_filename}.png", flush=True)
        
        # Salva HTML localmente
        html_path = Path(settings.screenshots_path) / f"{base_filename}.html"
        html_content = await page.content()
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"[AUTOAPPLY] HTML saved: {base_filename}.html", flush=True)
        
        # Upload su Azure Blob Storage se configurato
        if settings.upload_screenshots_to_blob:
            uploader = get_blob_uploader()
            if uploader.is_available:
                uploader.upload_file(str(screenshot_path), "screenshots")
                uploader.upload_file(str(html_path), "screenshots")
        
        return str(screenshot_path)
