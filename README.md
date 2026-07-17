# F1 Session Results → Discord Notifier

Posts the full timing/results board to a Discord channel whenever an F1
session finishes. If it was a Race or Sprint (the only sessions that award
championship points), it also posts the updated Drivers' and Constructors'
standings.

Runs entirely on OpenF1's **free** tier — no paid subscription needed,
because it only ever asks about sessions that have already ended.

## 1. Create a Discord webhook

1. Open Discord and go to the server/channel you want results posted to.
   (Tip: if you don't want this cluttering an existing server, create a
   small private server just for yourself and add a `#f1-results` channel.)
2. Channel Settings → Integrations → Webhooks → **New Webhook**.
3. Give it a name/avatar if you like, then **Copy Webhook URL**.

## 2. Install dependencies

Requires Python 3.9+.

```bash
pip install -r requirements.txt
```

## 3. Set your webhook URL

macOS/Linux:
```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

Windows (PowerShell):
```powershell
$env:DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

(Or set it permanently in your OS environment variables / a `.env`-loading
setup of your choice — the script just reads `os.environ`.)

## 4. Bootstrap (important — run this first)

```bash
python main.py
```

The very first run doesn't post anything — it just marks all currently
finished sessions as "already seen" so you don't get a flood of old race
results dumped into Discord at once. After this, only *new* finished
sessions will trigger a message.

## 5. Keep it checking for new results

Pick one:

**Option A — scheduled task (recommended, low resource use)**
Run `python main.py` every 5 minutes via cron or Task Scheduler.

Linux/macOS cron example (`crontab -e`):
```
*/5 * * * * cd /path/to/f1_discord_bot && /usr/bin/python3 main.py >> log.txt 2>&1
```

**Option B — keep it running continuously**
On a machine that's always on (a Raspberry Pi, small VPS, home server, or a
"always on" Replit/Railway/Render deployment):
```bash
python main.py --loop --interval 5
```

## How it decides what to send

- Every session that finishes (Practice, Qualifying, Sprint Qualifying,
  Sprint, Race) gets a results/timing board post.
- Only **Race** and **Sprint** sessions additionally get a standings post,
  since those are the only sessions that award championship points.
- `state.json` keeps track of which sessions have already been posted —
  don't delete it, or you'll get re-notified for old sessions.
- OpenF1 typically publishes results a few minutes after the session ends,
  so expect a short delay rather than an instant post.
- The championship standings endpoints are in beta on OpenF1's side and are
  documented as covering race sessions; if a Sprint's standings aren't
  available yet when checked, the results board still gets posted and the
  standings are simply skipped for that run.

## Customizing

- `LOOKBACK_DAYS` in `main.py` controls how far back a run will look for
  "recently finished" sessions (useful if the script was offline for a
  few days). Default is 4.
- Embed colors, emoji, and table formatting are all in `main.py` —
  straightforward to tweak.
