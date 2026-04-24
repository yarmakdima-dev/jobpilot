# Gmail OAuth Setup

A8 (Inbox Watcher) uses the Gmail API with OAuth 2.0. You complete this setup once; after that the token refreshes automatically.

**Time required:** ~10 minutes.

---

## What you'll end up with

| File | What it is | Committed? |
|------|-----------|-----------|
| `config/gmail_credentials.json` | OAuth client ID + secret from Google Cloud Console | **No — never commit** |
| `config/gmail_token.json` | Your access + refresh token, written by the auth script | **No — never commit** |

Both files are already in `.gitignore`.

---

## Step 1 — Create a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Click the project dropdown at the top → **New Project**.
3. Name: `JobPilot` (or anything you'll recognize). Click **Create**.
4. Make sure the new project is selected in the dropdown before continuing.

---

## Step 2 — Enable the Gmail API

1. In the left sidebar: **APIs & Services → Library**.
2. Search for `Gmail API`. Click it.
3. Click **Enable**.

---

## Step 3 — Configure the OAuth consent screen

1. **APIs & Services → OAuth consent screen**.
2. User Type: **External**. Click **Create**.
3. Fill in the required fields:
   - App name: `JobPilot`
   - User support email: your Gmail address
   - Developer contact email: your Gmail address
4. Click **Save and Continue** through the Scopes and Test Users screens (no changes needed at this stage).
5. Back on the summary screen, click **Publish App** → **Confirm** if you see a prompt asking you to move out of testing. (If you leave it in testing mode, tokens expire after 7 days.)

   > **Alternative:** stay in testing mode and add your Gmail address as a test user under **Test Users**. Tokens will still expire after 7 days and need a re-auth, but everything works locally.

---

## Step 4 — Create OAuth 2.0 credentials

1. **APIs & Services → Credentials**.
2. Click **+ Create Credentials → OAuth client ID**.
3. Application type: **Desktop app**.
4. Name: `JobPilot Desktop` (or any label).
5. Click **Create**.
6. In the confirmation dialog, click **Download JSON**.
7. Save the downloaded file as:
   ```
   config/gmail_credentials.json
   ```
   inside the JobPilot repo root.

---

## Step 5 — Run the auth script

```bash
python scripts/gmail_auth.py
```

What happens:
- A browser window opens with Google's consent screen.
- Sign in with the Gmail account you want A8 to watch.
- Grant the requested permissions (read, compose drafts, modify labels).
- The browser redirects to `localhost` — this is expected; the script handles it.
- The script prints a confirmation line with your email address and saves `config/gmail_token.json`.

---

## Step 6 — Verify

The script prints something like:

```
✓  Authenticated as: yourname@gmail.com
   Total messages in mailbox: 14382
   Token saved to: config/gmail_token.json
```

If you see that, you're done. A8 will call `get_gmail_service()` from `scripts/gmail_auth.py` and get a live API handle.

---

## Troubleshooting

**`FileNotFoundError: Gmail credentials file not found`**
→ The credentials JSON is not in `config/gmail_credentials.json`. Re-check Step 4.

**`Access blocked: JobPilot has not completed the Google verification process`**
→ You're trying to authorize with an account that isn't a listed test user, and the app is still in testing mode. Add your account under **OAuth consent screen → Test Users**, or publish the app (Step 3).

**`Token has been expired or revoked`**
→ Delete `config/gmail_token.json` and re-run the script. This happens if you revoke access in your Google account settings or if a testing-mode token passes its 7-day TTL.

**Port conflict on `localhost`**
→ The script uses `port=0` (OS picks a free port). If this still fails, check whether a firewall is blocking loopback connections.

---

## Scopes granted

| Scope | Why |
|-------|-----|
| `gmail.readonly` | Read messages and threads |
| `gmail.compose` | Create drafts (A8 never sends — drafts only, per Hard Rule 2) |
| `gmail.modify` | Apply labels and archive processed messages |

---

## Security notes

- `config/gmail_credentials.json` and `config/gmail_token.json` are listed in `.gitignore` and must never be committed. Treat them like passwords.
- If you accidentally commit either file, rotate the credentials immediately in Google Cloud Console → Credentials → delete and recreate the OAuth client.
- The refresh token has no hard expiry (unless the app is in testing mode). Revoking access at [myaccount.google.com/permissions](https://myaccount.google.com/permissions) invalidates it immediately.
