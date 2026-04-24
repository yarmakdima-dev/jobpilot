"""Gmail OAuth 2.0 authentication module for A8 (Inbox Watcher).

First run: opens a browser window for user consent and saves the token.
Subsequent runs: loads the saved token and refreshes it if expired.

Credentials file (downloaded from Google Cloud Console):
    config/gmail_credentials.json  — never committed; see DATA_CONTRACT.md

Token file (written after first consent):
    config/gmail_token.json  — never committed; see DATA_CONTRACT.md

Usage:
    from scripts.gmail_auth import get_gmail_service

    service = get_gmail_service()
    # returns a googleapiclient.discovery.Resource for the Gmail API v1
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


LOGGER = logging.getLogger(__name__)

# Paths are relative to the repo root, resolved at import time.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CREDENTIALS_PATH = _REPO_ROOT / "config" / "gmail_credentials.json"
_TOKEN_PATH = _REPO_ROOT / "config" / "gmail_token.json"

# Scopes required by A8:
#   - gmail.readonly     : read messages and threads
#   - gmail.compose      : create drafts (A8 never sends — drafts only)
#   - gmail.modify       : apply labels / archive (for pipeline state updates)
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]


def get_gmail_service() -> Any:
    """Return an authenticated Gmail API v1 service object.

    On first call: opens a local browser window for OAuth consent and writes
    the resulting token to ``config/gmail_token.json``.

    On subsequent calls: loads the saved token and silently refreshes it if
    it has expired.

    Returns:
        A ``googleapiclient.discovery.Resource`` for the Gmail API (v1).

    Raises:
        FileNotFoundError: if ``config/gmail_credentials.json`` is missing.
        google.auth.exceptions.RefreshError: if the refresh token has been
            revoked and a new consent flow is required.
    """
    credentials = _load_or_acquire_credentials()
    service = build("gmail", "v1", credentials=credentials)
    LOGGER.info("Gmail API service ready (account: %s)", _account_hint(credentials))
    return service


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _load_or_acquire_credentials() -> Credentials:
    """Load saved credentials, refreshing or re-authorizing as needed."""
    credentials: Credentials | None = None

    if _TOKEN_PATH.exists():
        LOGGER.debug("Loading saved token from %s", _TOKEN_PATH)
        credentials = Credentials.from_authorized_user_file(
            str(_TOKEN_PATH), SCOPES
        )

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        LOGGER.info("Token expired — refreshing...")
        credentials.refresh(Request())
        _save_token(credentials)
        return credentials

    # No usable token: run the full consent flow.
    credentials = _run_consent_flow()
    _save_token(credentials)
    return credentials


def _run_consent_flow() -> Credentials:
    """Open a browser window and complete the OAuth 2.0 consent flow."""
    _require_credentials_file()
    LOGGER.info(
        "No valid token found. Opening browser for OAuth consent...\n"
        "  Credentials: %s\n"
        "  Token will be saved to: %s",
        _CREDENTIALS_PATH,
        _TOKEN_PATH,
    )
    flow = InstalledAppFlow.from_client_secrets_file(
        str(_CREDENTIALS_PATH), SCOPES
    )
    # run_local_server binds to a random free port and handles the redirect.
    credentials: Credentials = flow.run_local_server(port=0)
    LOGGER.info("OAuth consent complete.")
    return credentials


def _save_token(credentials: Credentials) -> None:
    """Persist the credentials to ``config/gmail_token.json``."""
    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")
    LOGGER.debug("Token saved to %s", _TOKEN_PATH)


def _require_credentials_file() -> None:
    """Raise a clear error if the credentials file has not been placed yet."""
    if not _CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"Gmail credentials file not found: {_CREDENTIALS_PATH}\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials\n"
            "and save it as config/gmail_credentials.json.\n"
            "See docs/gmail_oauth_setup.md for step-by-step instructions."
        )


def _account_hint(credentials: Credentials) -> str:
    """Return a loggable hint about which account is authenticated."""
    # The credentials object does not expose the email address directly;
    # we surface the client_id as a non-sensitive proxy for log correlation.
    client_id: str = getattr(credentials, "client_id", "unknown")
    if len(client_id) > 20:
        client_id = client_id[:10] + "..." + client_id[-6:]
    return client_id


# ---------------------------------------------------------------------------
# CLI entry point — run `python scripts/gmail_auth.py` to trigger first-run
# ---------------------------------------------------------------------------


def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s  %(message)s",
    )
    try:
        service = get_gmail_service()
        # Smoke test: fetch the authenticated user's profile.
        profile = service.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress", "unknown")
        total = profile.get("messagesTotal", "?")
        print(f"\n✓  Authenticated as: {email}")
        print(f"   Total messages in mailbox: {total}")
        print(f"   Token saved to: {_TOKEN_PATH.relative_to(_REPO_ROOT)}")
        return 0
    except FileNotFoundError as exc:
        LOGGER.error("%s", exc)
        return 1
    except Exception:
        LOGGER.exception("Authentication failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
