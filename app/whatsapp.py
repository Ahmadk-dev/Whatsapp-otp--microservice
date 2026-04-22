import httpx

from app.config import settings


class WhatsAppError(Exception):
    pass


async def send_template_otp(phone: str, code: str) -> dict:
    """Send an OTP via Twilio's WhatsApp API.

    `phone` must be E.164 with a leading '+'. Twilio expects both `From` and `To`
    prefixed with `whatsapp:`. For the Twilio sandbox, the recipient must have
    joined the sandbox first (send the join code to the sandbox number).
    """
    to = f"whatsapp:{phone}"
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    )
    auth = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    data = {
        "From": settings.TWILIO_WHATSAPP_FROM,
        "To": to,
        "Body": f"Your verification code is {code}. It expires in 5 minutes.",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, data=data, auth=auth)

    if resp.status_code >= 400:
        try:
            payload = resp.json()
            code = payload.get("code")
            message = payload.get("message") or resp.text
        except Exception:
            code, message = None, resp.text

        if code == 63038:
            raise WhatsAppError("Daily WhatsApp message limit reached. Please try again after midnight UTC.")
        raise WhatsAppError(f"Could not send WhatsApp message. Please try again later.")

    return resp.json()
