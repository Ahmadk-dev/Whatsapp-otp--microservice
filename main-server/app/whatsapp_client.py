import httpx

from app.config import settings


class WhatsAppServiceError(Exception):
    pass


async def send_otp(phone: str, code: str) -> None:
    """Call Server 2 POST /send-whatsapp. Raises WhatsAppServiceError on any failure."""
    url = f"{settings.WHATSAPP_SERVICE_URL.rstrip('/')}/send-whatsapp"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json={"phone": phone, "code": code})
    except httpx.ConnectError:
        raise WhatsAppServiceError(
            f"Cannot reach WhatsApp service at {settings.WHATSAPP_SERVICE_URL}. "
            "Make sure Server 2 is running."
        )
    except httpx.TimeoutException:
        raise WhatsAppServiceError("WhatsApp service timed out.")
    except httpx.RequestError as e:
        raise WhatsAppServiceError(f"WhatsApp service request failed: {e}")

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise WhatsAppServiceError(f"WhatsApp service error {resp.status_code}: {detail}")
