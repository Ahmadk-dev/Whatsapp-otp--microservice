import asyncio
import shutil
import webbrowser
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import BrowserContext, Page, async_playwright


SEL_CHAT_LIST  = '#pane-side, div[aria-label="Chat list"]'
SEL_QR_CODE    = 'canvas[aria-label="Scan me!"], div[data-ref]'
SEL_SEND_BTN   = 'button[aria-label="Send"], span[data-icon="send"], span[data-icon="wds-ic-send-filled"]'
SEL_DIALOG     = 'div[role="dialog"]'

# Phone-number login flow selectors
SEL_PHONE_LOGIN = (
    '[data-link-target="phone_number"], '
    'div:has-text("Log in with phone number"), '
    'a:has-text("Log in with phone number"), '
    'button:has-text("Log in with phone number")'
)
SEL_PHONE_INPUT   = '[data-testid="phone-number-input"], input[type="tel"]'
SEL_PAIRING_CODE  = '[data-testid="link-device-phone-number-code"], [data-testid*="pairing-code"]'

WA_HOME = "https://web.whatsapp.com/"


class WhatsAppError(Exception):
    pass


class WhatsAppSender:
    def __init__(
        self,
        session_dir: str | Path,
        headless: bool = False,
        login_timeout_seconds: int = 180,
        send_timeout_seconds: int = 45,
    ):
        self.session_dir = Path(session_dir).resolve()
        self.headless = headless
        self.login_timeout_ms = login_timeout_seconds * 1000
        self.send_timeout_ms = send_timeout_seconds * 1000

        self._pw = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None
        self._lock = asyncio.Lock()
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started and self._ctx is not None

    async def start(self) -> None:
        """Launch browser and open WhatsApp Web. Returns immediately — does NOT block for login."""
        if self._started:
            return

        # Wipe any saved session so every startup requires a fresh login
        if self.session_dir.exists():
            shutil.rmtree(self.session_dir)
            print("[whatsapp] Session cleared.")
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()

        self._ctx = await self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.session_dir),
            headless=self.headless,
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )

        self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        await self._page.goto(WA_HOME, wait_until="domcontentloaded")

        print("[whatsapp] Waiting for WhatsApp Web to load...")
        try:
            await self._page.wait_for_selector(
                f"{SEL_CHAT_LIST}, {SEL_QR_CODE}", timeout=120_000
            )
        except Exception as e:
            raise WhatsAppError(f"WhatsApp Web did not load: {e}") from e

        self._started = True

        if await self.is_logged_in():
            print("[whatsapp] Session restored — already logged in.")
        else:
            print("[whatsapp] Not logged in — opening setup page...")
            webbrowser.open("http://localhost:8001/setup")

    async def begin_phone_login(self, phone: str) -> str | None:
        """
        Drive the 'Link with phone number' flow on WhatsApp Web.

        Clicks the phone-login link, enters `phone`, submits, then tries to read
        the pairing code from the page.  Returns the code string if found, or
        None when the code is visible in the browser window but could not be
        scraped (user reads it themselves).
        """
        if not self.is_running or self._page is None:
            raise WhatsAppError("Browser not started.")
        if await self.is_logged_in():
            return None

        page = self._page

        # Return to home if we drifted to a chat URL
        if "send?" in page.url:
            await page.goto(WA_HOME, wait_until="domcontentloaded")
            await page.wait_for_selector(f"{SEL_CHAT_LIST}, {SEL_QR_CODE}", timeout=30_000)

        async with self._lock:
            # Step 1 — click "Link with phone number"
            clicked = False
            for attempt in [
                lambda: page.locator(SEL_PHONE_LOGIN).first.click(timeout=8_000),
                lambda: page.get_by_text("Log in with phone number").first.click(timeout=5_000),
            ]:
                try:
                    await attempt()
                    clicked = True
                    break
                except Exception:
                    pass

            if not clicked:
                raise WhatsAppError(
                    "Could not find 'Link with phone number' button. "
                    "WhatsApp Web may have changed its layout."
                )

            # Step 2 — fill the phone input
            try:
                phone_input = page.locator(SEL_PHONE_INPUT).first
                await phone_input.wait_for(state="visible", timeout=15_000)
                await phone_input.click()

                # The field may already contain the country code (e.g. "+961").
                # Read it, then type only the remaining local digits.
                current = (await phone_input.input_value()).lstrip("+").replace(" ", "")
                phone_digits = phone.lstrip("+").replace(" ", "")

                if current and phone_digits.startswith(current):
                    fill = phone_digits[len(current):]
                else:
                    await phone_input.press("Control+a")
                    await phone_input.press("Delete")
                    fill = phone_digits

                await phone_input.type(fill, delay=30)
            except Exception as e:
                raise WhatsAppError(f"Could not fill phone number input: {e}") from e

            # Step 3 — submit
            try:
                await page.get_by_role("button", name="Next").first.click(timeout=5_000)
            except Exception:
                await page.keyboard.press("Enter")

            # Step 4 — try to read the pairing code
            await asyncio.sleep(1.5)
            try:
                code_el = await page.wait_for_selector(SEL_PAIRING_CODE, timeout=15_000)
                if code_el:
                    text = (await code_el.inner_text()).strip()
                    if text:
                        print(f"[whatsapp] Pairing code: {text}")
                        return text
            except Exception:
                pass

            print("[whatsapp] Pairing code is visible in the browser window.")
            return None

    async def is_logged_in(self) -> bool:
        if self._page is None:
            return False
        try:
            el = await self._page.query_selector(SEL_CHAT_LIST)
            return el is not None
        except Exception:
            return False

    async def health(self) -> dict:
        logged_in = await self.is_logged_in()
        return {"status": "ok", "logged_in": logged_in, "setup_needed": not logged_in}

    async def send(self, phone: str, message: str) -> None:
        """Send `message` to `phone` (E.164). Raises WhatsAppError on any failure."""
        if not self.is_running or self._page is None:
            raise WhatsAppError("Sender not started. Call start() first.")
        if not await self.is_logged_in():
            raise WhatsAppError(
                "Not logged in. Complete setup at http://localhost:8001/setup first."
            )

        digits = phone.lstrip("+")
        url = f"https://web.whatsapp.com/send?phone={digits}&text={quote(message)}"

        async with self._lock:
            page = self._page
            await page.goto(url, wait_until="domcontentloaded")

            try:
                await page.wait_for_selector(
                    f"{SEL_SEND_BTN}, {SEL_DIALOG}",
                    timeout=self.send_timeout_ms,
                )
            except Exception as e:
                raise WhatsAppError(f"Chat did not load for {phone}: {e}") from e

            dialog = await page.query_selector(SEL_DIALOG)
            if dialog is not None:
                try:
                    text = (await dialog.inner_text()).lower()
                except Exception:
                    text = ""
                if "invalid" in text or "isn't" in text or "not on whatsapp" in text or "phone number shared" in text:
                    raise WhatsAppError(
                        f"Phone {phone} is not reachable on WhatsApp: {text.strip()[:200]}"
                    )

            try:
                await page.click(SEL_SEND_BTN, timeout=self.send_timeout_ms)
            except Exception as e:
                raise WhatsAppError(f"Could not click send button: {e}") from e

            await asyncio.sleep(2.0)

    async def stop(self) -> None:
        try:
            if self._ctx is not None:
                await self._ctx.close()
        except Exception:
            pass
        try:
            if self._pw is not None:
                await self._pw.stop()
        except Exception:
            pass
        self._ctx = None
        self._page = None
        self._pw = None
        self._started = False
