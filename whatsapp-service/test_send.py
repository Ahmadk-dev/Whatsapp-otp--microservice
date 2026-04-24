"""Standalone CLI to test the Playwright WhatsApp sender without running the FastAPI service.

Usage:
    python test_send.py +96181926481 123456
"""

import asyncio
import sys

from whatsapp import WhatsAppError, WhatsAppSender


async def main():
    if len(sys.argv) != 3:
        print("Usage: python test_send.py <phone-e164> <code>")
        print("Example: python test_send.py +96181926481 123456")
        sys.exit(1)

    phone, code = sys.argv[1], sys.argv[2]
    message = f"Your verification code is {code}. It expires in 5 minutes."

    sender = WhatsAppSender(session_dir="./session", headless=False)
    try:
        await sender.start()
        print(f"[test_send] Sending to {phone}...")
        await sender.send(phone, message)
        print("[test_send] ✓ Sent successfully.")
    except WhatsAppError as e:
        print(f"[test_send] ✗ FAILED: {e}")
        sys.exit(2)
    finally:
        await sender.stop()


if __name__ == "__main__":
    asyncio.run(main())
