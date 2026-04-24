import asyncio
import os
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import Browser, BrowserContext, Page, async_playwright


SEL_CHAT_LIST = '#pane-side, div[aria-label="Chat list"]'
SEL_QR_CODE = 'canvas[aria-label="Scan me!"], div[data-ref]'
SEL_SEND_BTN = 'button[aria-label="Send"], span[data-icon="send"], span[data-icon="wds-ic-send-filled"]'
SEL_DIALOG = 'div[role="dialog"]'

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
        """Launch browser, open WhatsApp Web, wait until logged in."""
        if self._started:
            return

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

        # Wait for either the chat list (logged in) or the QR code (needs scan)
        print("[whatsapp] Waiting for WhatsApp Web to load...")
        try:
            await self._page.wait_for_selector(
                f"{SEL_CHAT_LIST}, {SEL_QR_CODE}", timeout=60_000
            )
        except Exception as e:
            raise WhatsAppError(f"WhatsApp Web did not load in time: {e}") from e

        if await self._is_logged_in():
            print("[whatsapp] Session restored — already logged in.")
        else:
            print(
                "\n" + "=" * 60 +
                "\n[whatsapp] QR CODE DISPLAYED — open WhatsApp on your phone,\n"
                "go to Settings → Linked Devices → Link a Device, and scan\n"
                "the QR code in the browser window.\n" +
                "=" * 60 + "\n"
            )
            try:
                await self._page.wait_for_selector(SEL_CHAT_LIST, timeout=self.login_timeout_ms)
            except Exception as e:
                raise WhatsAppError(
                    f"Did not detect login within {self.login_timeout_ms // 1000}s. "
                    "Delete the session/ folder and try again."
                ) from e
            print("[whatsapp] Login successful — session saved.")

        self._started = True

    async def _is_logged_in(self) -> bool:
        if self._page is None:
            return False
        try:
            el = await self._page.query_selector(SEL_CHAT_LIST)
            return el is not None
        except Exception:
            return False

    async def health(self) -> dict:
        return {"status": "ok", "logged_in": await self._is_logged_in()}

    async def send(self, phone: str, message: str) -> None:
        """Send `message` to `phone` (E.164 with leading '+'). Raises WhatsAppError on failure."""
        if not self.is_running or self._page is None:
            raise WhatsAppError("Sender not started. Call start() first.")

        digits = phone.lstrip("+")
        url = f"https://web.whatsapp.com/send?phone={digits}&text={quote(message)}"

        async with self._lock:
            page = self._page
            await page.goto(url, wait_until="domcontentloaded")

            try:
                # Wait for either the send button (chat ready) or a dialog (error)
                await page.wait_for_selector(
                    f"{SEL_SEND_BTN}, {SEL_DIALOG}",
                    timeout=self.send_timeout_ms,
                )
            except Exception as e:
                raise WhatsAppError(f"Chat did not load for {phone}: {e}") from e

            # Check if an error dialog appeared (invalid phone / not on WhatsApp)
            dialog = await page.query_selector(SEL_DIALOG)
            if dialog is not None:
                try:
                    text = (await dialog.inner_text()).lower()
                except Exception:
                    text = ""
                if "invalid" in text or "isn't" in text or "not on whatsapp" in text or "phone number shared" in text:
                    raise WhatsAppError(f"Phone {phone} is not reachable on WhatsApp: {text.strip()[:200]}")

            # Click the send button
            try:
                await page.click(SEL_SEND_BTN, timeout=self.send_timeout_ms)
            except Exception as e:
                raise WhatsAppError(f"Could not click send button: {e}") from e

            # Give the message a moment to flush to WhatsApp servers
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
