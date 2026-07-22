import getpass
import os
from urllib.parse import urlsplit

import httpx


def main() -> None:
    if os.environ.get("MANA_TELEGRAM_AUTH_SMOKE") != "1":
        raise SystemExit("Set MANA_TELEGRAM_AUTH_SMOKE=1 for this explicit manual check")
    raw_user_id = os.environ.get("MANA_TELEGRAM_AUTH_SMOKE_USER_ID", "")
    if not raw_user_id.isdigit() or int(raw_user_id) <= 0:
        raise SystemExit("MANA_TELEGRAM_AUTH_SMOKE_USER_ID must be an explicit Telegram ID")
    base_url = os.environ.get("MANA_TELEGRAM_AUTH_SMOKE_BASE_URL", "http://127.0.0.1:8000")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SystemExit("MANA_TELEGRAM_AUTH_SMOKE_BASE_URL must be an HTTP(S) origin")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    telegram_id = int(raw_user_id)

    with httpx.Client(base_url=origin, timeout=15.0) as client:
        requested = client.post(
            "/api/v1/auth/telegram/request-code",
            headers={"Origin": origin},
            json={"telegram_id": telegram_id},
        )
        requested.raise_for_status()
        print("Code request accepted. Read the message in the configured Telegram bot.")
        code = getpass.getpass("Six-digit code (input is hidden): ").strip()
        if len(code) != 6 or not code.isdigit():
            raise SystemExit("The code must contain exactly six digits")
        verified = client.post(
            "/api/v1/auth/telegram/verify-code",
            headers={"Origin": origin},
            json={"telegram_id": telegram_id, "code": code},
        )
        code = ""
        verified.raise_for_status()
        body = verified.json()
        if not isinstance(body, dict) or body.get("authenticated") is not True:
            raise SystemExit("The server did not establish an authenticated session")
        user = body.get("user")
        if not isinstance(user, dict) or user.get("telegram_id") != telegram_id:
            raise SystemExit("The established session does not match the explicit Telegram ID")
        csrf_token = client.cookies.get("mana_csrf")
        if not csrf_token:
            raise SystemExit("The CSRF cookie was not established")
        session = client.get("/api/v1/auth/session")
        session.raise_for_status()
        logged_out = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": origin, "X-CSRF-Token": csrf_token},
            json={},
        )
        logged_out.raise_for_status()
        print("Telegram delivery, OTP verification, session read, and logout passed.")


if __name__ == "__main__":
    main()
