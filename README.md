# F1 Session Results → Discord Notifier

Posts the full timing/results board to a Discord channel whenever an F1
session finishes. If it was a Race or Sprint (the only sessions that award
championship points), it also posts the updated Drivers' and Constructors'
standings.

Runs entirely on OpenF1's **free** tier — no paid subscription needed,
because it only ever asks about sessions that have already ended.

## 1. Create a Discord webhook

1. Open Discord and go to the channel you want results posted to.
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

**Posting to more than one channel or server?** Set `DISCORD_WEBHOOK_URL` to
a comma-separated list of webhook URLs instead of a single one — the same
results/standings get posted to every URL in the list:
```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/AAA/xxx,https://discord.com/api/webhooks/BBB/yyy"
```
Spaces around the commas are fine. If one webhook fails to post (e.g. it
was deleted in Discord), the others still get posted — the failure is
just reported at the end so it doesn't go unnoticed.

## 4. Bootstrap (important — run this first, locally)

```bash
python main.py
```

The very first run doesn't post anything — it just marks all currently
finished sessions as "already seen" so you don't get a flood of old race
results dumped into Discord at once. After this, only *new* finished
sessions will trigger a message. Commit the resulting `state.json` if
you're using the GitHub Actions option below.

## 5. Keep it checking for new results — without needing your PC on

**Recommended: GitHub Actions (free, runs in the cloud)**

1. Create a new GitHub repo (private is fine) and push these files to it:
   `main.py`, `requirements.txt`, `state.json`, and
   `.github/workflows/f1-notify.yml`.
2. In the repo: **Settings → Secrets and variables → Actions → New
   repository secret**. Name it `DISCORD_WEBHOOK_URL` and paste your
   webhook URL as the value.
3. That's it — the workflow runs every 10 minutes automatically, checks
   OpenF1, posts to Discord when something new finished, and commits the
   updated `state.json` back to the repo so state persists between runs.
4. You can trigger a run manually any time from the repo's **Actions** tab
   (useful for testing) via the "Run workflow" button.

Notes:
- GitHub schedules can run a few minutes late during high load (e.g. right
  at the top of the hour) — not a problem here, since results already lag
  OpenF1 by a few minutes anyway.
- GitHub auto-disables scheduled workflows after 60 days with no repo
  activity. Since this workflow commits to the repo whenever it posts a
  result, an active F1 season should keep it alive on its own; if it ever
  does get disabled during a long off-season, just re-enable it from the
  Actions tab.

**Alternative: run it yourself on an always-on machine**

If you'd rather not use GitHub Actions, any machine that's on 24/7 works —
a Raspberry Pi, a cheap VPS, or a free-tier cloud VM (e.g. Oracle Cloud's
Always Free tier). On that machine, either:

a) Schedule it via cron / Task Scheduler every ~5 minutes:
```bash
python main.py
```
Linux/macOS cron example (`crontab -e`):
```
*/5 * * * * cd /path/to/f1_discord_bot && /usr/bin/python3 main.py >> log.txt 2>&1
```

b) Or run it continuously with its own internal loop:
```bash
python main.py --loop --interval 5
```

Either way, this only needs to run somewhere that stays on — your regular
PC works too, but only while it's actually powered on and awake.

**Alternative: Docker, if you're self-hosting**

Docker doesn't remove the need for an always-on host, but if you're
already going the VPS/Raspberry Pi/home-server route, it's a cleaner way
to run this than installing Python directly on the box.

```bash
docker compose up -d
```

This builds the image, starts the notifier in `--loop` mode, and (thanks
to `restart: unless-stopped`) brings it back automatically if it crashes or
the host reboots. `state.json` is bind-mounted so your notified-session
history survives restarts. Set `DISCORD_WEBHOOK_URL` in a `.env` file next
to `docker-compose.yml`:
```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

For a one-off run instead of the persistent loop (e.g. if you're driving it
from cron on the host, or a cloud scheduled-container service like Cloud
Run Jobs):
```bash
docker build -t f1-notifier .
docker run --rm -e DISCORD_WEBHOOK_URL -v $(pwd)/state.json:/app/state.json f1-notifier python main.py
```
Note that fully serverless container schedulers typically don't persist a
local filesystem between runs, so `state.json` would need to live
somewhere external (e.g. a small cloud storage bucket) in that setup —
same limitation as the GitHub Actions approach, just solved differently
there via committing the file back to the repo.

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
