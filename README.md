# arena_message — text your are.na channel via a Telegram bot

Send a **link, photo, or note** to a private Telegram bot from your phone, and it lands as a
block in your are.na `staging` channel to organize later.

Originally scoped around Twilio SMS; switched to a Telegram bot because it's **free** (no phone
number, no per-message charge) and natively carries text, links, photos, and captions.

```
Your phone (Telegram)  ──message──▶  Telegram  ──webhook──▶  this Flask server  ──API──▶  are.na
                                                                   │
                          photo bytes downloaded with bot token, re-hosted at /media/<random>
                          so are.na can fetch it (are.na then keeps its own copy)
```

## How a message becomes a block

| You send…            | are.na block created                                  |
|----------------------|-------------------------------------------------------|
| plain text           | **Text** block (markdown)                             |
| a single URL         | **Link** block (are.na fetches a preview)             |
| a photo              | **Image** block; any caption becomes the description  |
| a photo sent as file | same as a photo (uncompressed)                        |

## Project layout

| File | Role |
|------|------|
| `config.py` | Reads + validates all settings from environment variables |
| `arena_client.py` | are.na API: create block, update title/description |
| `telegram_client.py` | Telegram API: download a file, send a reply |
| `app.py` | Flask server: `/telegram` webhook + `/media/<name>` serving + `/health` |
| `scripts/test_arena.py` | Standalone check that your are.na token/slug work |
| `scripts/set_webhook.py` | Registers the webhook URL + secret with Telegram |
| `Dockerfile` | Build recipe for the cloud host |
| `render.yaml` | Render Blueprint: declares the web service for one-click deploy |

The code is heavily commented and calls out idiomatic-Python choices (vs TS/Kotlin) as it goes.

## Security model (why this can't leak your are.na account)

An are.na Personal Access Token is **account-wide write** — it can't be scoped to a single
channel. So the protection is in locking down who can reach the bot:

- **Webhook secret** — Telegram echoes a secret header on every call; `/telegram` rejects
  anything without the exact match (constant-time compare).
- **Sender allowlist** — only messages from *your* numeric Telegram user id are processed.
- **Secrets stay out of git** — tokens live in `.env` (gitignored) locally, or platform
  secrets in prod. Never committed.
- **Bot token never leaves the server** — Telegram's download URL embeds the bot token, so we
  download photos server-side and re-host them at an **unguessable** `/media/<random>` URL.
  are.na makes its own permanent copy on ingest (verified: are.na image blocks serve from
  `images.are.na` / cloudfront, not the source), so those files only matter briefly.
- **HTTPS** — provided by the cloud host; required by Telegram webhooks anyway.

---

## One-time setup

### 1. Create the bot
1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the **bot token**.
2. (Optional) `/setprivacy` → keep privacy mode **on** so the bot only sees messages sent
   directly to it.

### 2. Find your Telegram user id
DM **@userinfobot** and it replies with your numeric id. (Or skip this — message your bot once
after deploy and read the id from the server logs, then set it.)

### 3. Create the are.na token
Go to <https://www.are.na/settings/oauth>, create a Personal Access Token **with write scope**,
and copy it.

### 4. Configure
```bash
cp .env.example .env
# then edit .env and fill in every value.
# generate the webhook secret with:
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Run locally (with a tunnel)

Telegram webhooks need a public HTTPS URL, so for local testing expose your machine with a
tunnel (e.g. `cloudflared tunnel --url http://localhost:8080` or `ngrok http 8080`).

```bash
python3 -m venv .venv && source .venv/bin/activate   # create + activate a virtualenv
pip install -r requirements.txt

# Sanity-check are.na on its own (no server needed):
python scripts/test_arena.py

# Start the server:
python app.py
```

Put the tunnel's https URL in `.env` as `PUBLIC_BASE_URL`, then register the webhook:
```bash
python scripts/set_webhook.py          # register
python scripts/set_webhook.py info     # verify what's registered
```
Now message your bot a link, a note, and a photo, and watch them appear in your channel.

> Tip: a tunnel URL changes each time you restart it — re-run `set_webhook.py` after it does.

---

## Deploy (Render)

Render has a permanent free tier and deploys this repo straight from its `Dockerfile`. Unlike a
push-a-local-folder CLI, Render builds from a **connected Git repo** and redeploys automatically
on every push. The included [`render.yaml`](render.yaml) Blueprint describes the whole service so
setup is reproducible.

**Prerequisite:** the code must live in a Git repo on GitHub/GitLab/Bitbucket (Render pulls from
there). If you haven't yet: `git init && git add . && git commit -m "init"` and push it up.

```
1. Render dashboard → "New +" → "Blueprint" → pick this repo.
2. Render reads render.yaml and prompts for each env var (all are `sync: false`, so nothing
   secret is ever committed). Fill in everything EXCEPT PUBLIC_BASE_URL for now — you can put a
   placeholder; you'll correct it in step 4.
3. Let it build + deploy. Note the live URL shown in the dashboard, e.g.
   https://arena-message.onrender.com  (Render adds a suffix if the name was taken).
4. Set PUBLIC_BASE_URL to that exact URL: dashboard → service → Environment → edit
   PUBLIC_BASE_URL → save (this triggers a redeploy).
5. Register the webhook against the live URL:
     PUBLIC_BASE_URL=https://<your-service>.onrender.com python scripts/set_webhook.py
```

After this, every `git push` to the connected branch redeploys automatically. You only re-run
`set_webhook.py` if the public URL changes.

> Note on the free tier: Render free services **sleep after 15 minutes idle** and take ~30–50s to
> cold-start. That's fine here — are.na fetches a re-hosted photo *while your webhook handler is
> still running* (the server is warm, having just received the message), and the 15-minute idle
> window is far longer than that fetch. The only visible effect of sleep is that the *first*
> message after a long quiet spell is slow; Telegram retries the webhook, so nothing is lost. If
> you'd rather never cold-start, Render's paid Starter plan keeps it always-on.

---

## Costs

| Thing | Cost |
|-------|------|
| Telegram Bot API | free |
| are.na API | free |
| Hosting | free tier, or a few $/mo for always-on |

## Troubleshooting

- **Bot doesn't respond** → `python scripts/set_webhook.py info`; check `url` and that
  `last_error_message` is empty. Confirm `PUBLIC_BASE_URL` is correct and HTTPS.
- **403 in logs** → the webhook secret didn't match, or the sender isn't your allowlisted id.
- **Photo block has no image** → the host was unreachable when are.na tried to fetch
  `/media/...`. On Render's free tier this is rare (the server is warm right after handling your
  message); if it persists, the paid Starter plan stays always-on.
- **401 from are.na** → token missing **write** scope, or wrong/expired token.
