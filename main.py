import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

OPENF1_BASE = "https://api.openf1.org/v1"
WEBHOOK_URLS = [
    url.strip()
    for url in os.environ.get("DISCORD_WEBHOOK_URL", "").split(",")
    if url.strip()
]
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# Session types that award championship points -> trigger a standings update.
# ("Sprint Qualifying" sets the sprint grid and does NOT award points, so
# it's deliberately excluded here.)
STANDINGS_SESSION_TYPES = {"Race", "Sprint"}

# Only look at sessions that ended within this window, so a first run (or a
# run after downtime) doesn't try to process the entire season's history.
LOOKBACK_DAYS = 4


class OpenF1AccessRestrictedError(RuntimeError):
    """Raised when OpenF1 returns 401 Unauthorized.
    This happens when a session is currently live: OpenF1 restricts most
    endpoints to paid subscribers while a session is in progress.
    """
    pass


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"notified_session_keys": [], "bootstrapped": False}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def api_get(path, **params):
    resp = requests.get(f"{OPENF1_BASE}/{path}", params=params, timeout=15)
    if resp.status_code == 401:
        raise OpenF1AccessRestrictedError(
            f"OpenF1 returned 401 Unauthorized for '{path}' -- a session is "
            "likely live right now."
        )
    resp.raise_for_status()
    return resp.json()


def get_recent_finished_sessions():
    pht = timezone(timedelta(hours=8), name="PHT")
    now = datetime.now(pht)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    sessions = api_get("sessions", year=now.year)
    finished = []
    for session in sessions:
        end = datetime.fromisoformat(session["date_end"])
        if cutoff <= end <= now:
            finished.append(session)
    finished.sort(key=lambda session: session["date_end"])
    return finished


def get_sessions_by_keys(session_keys):
    sessions = []
    missing = []
    for key in session_keys:
        matches = api_get("sessions", session_key=key)
        if matches:
            sessions.append(matches[0])
        else:
            missing.append(key)
    return sessions, missing


def get_drivers_by_number(session_key):
    drivers = api_get("drivers", session_key=session_key)
    return {d["driver_number"]: d for d in drivers}


def get_final_intervals(session_key):
    """Gap to the car ahead, at the end of the session, per driver.

    The /intervals endpoint is a firehose of readings taken roughly every
    4 seconds for the whole session, so this can be a sizeable request for
    a full race distance - fine for a once-per-session lookup, just not
    something to call more often than that. Only meaningful for Race/Sprint
    sessions; OpenF1 doesn't populate this for Practice/Qualifying.
    """
    records = api_get("intervals", session_key=session_key)
    latest_by_driver = {}
    for rec in records:
        driver = rec["driver_number"]
        if driver not in latest_by_driver or rec["date"] > latest_by_driver[driver]["date"]:
            latest_by_driver[driver] = rec
    return {driver: rec.get("interval") for driver, rec in latest_by_driver.items()}


def fmt_value(value, none_label="--"):
    if value is None:
        return none_label
    if isinstance(value, list):
        return " / ".join(fmt_value(v, none_label) for v in value)
    if isinstance(value, str):
        return value  # e.g. "+1 LAP"
    return f"+{value:.3f}"


def fmt_gap(value):
    return fmt_value(value, none_label="--")


def build_results_table(results, drivers, intervals=None):
    rows = []
    ranked = sorted(results, key=lambda r: (r["position"] is None, r["position"] or 999))
    if intervals is not None:
        rows.append(f"{'Pos':>2}  {'Drv':<2} {'Team':<16} {'Gap':<8} Interval")
    else:
        rows.append(f"{'Pos':>2}  {'Drv':<4} {'Team':<16} Gap")
    for result in ranked:
        driver = drivers.get(result["driver_number"], {})
        code = driver.get("name_acronym", "UNK")
        team = (driver.get("team_name") or "")[:16]
        pos = result.get("position")
        pos_str = f"{pos:>2}" if pos else "--"
        flag = ""
        if result.get("dsq"):
            flag = " (DSQ)"
        elif result.get("dnf"):
            flag = " (DNF)"
        elif result.get("dns"):
            flag = " (DNS)"
        gap = fmt_gap(result.get("gap_to_leader"))
        if intervals is not None:
            interval = fmt_value(intervals.get(result["driver_number"]))
            rows.append(f"{pos_str}  {code:<4} {team:<16} {gap:<10} {interval}{flag}")
        else:
            rows.append(f"{pos_str}  {code:<4} {team:<16} {gap}{flag}")
    return "\n".join(rows)


def build_standings_table(standings, name_lookup):
    ranked = sorted(standings, key=lambda s: s["position_current"])
    rows = []
    rows.append(f"{'Pos':>2} {'Name':<22} {'Points(diff)':<7}")
    for standing in ranked:
        name = name_lookup(standing)
        pts = standing["points_current"]
        delta = pts - standing["points_start"]
        delta_str = f"+{delta}" if delta else "+0"
        rows.append(f"{standing['position_current']:>2}  {name:<20} {pts:>5} pts ({delta_str})")
    return "\n".join(rows)


def post_webhook(embeds):
    if not WEBHOOK_URLS:
        raise RuntimeError(
            "DISCORD_WEBHOOK_URL is not set. Create a webhook in your Discord "
            "channel settings and set it as an environment variable."
        )
    failures = []
    for url in WEBHOOK_URLS:
        resp = requests.post(url, json={"embeds": embeds}, timeout=15)
        if resp.status_code >= 300:
            masked = url[:50] + "..." if len(url) > 50 else url
            print(f"Webhook post failed for {masked} ({resp.status_code}): {resp.text}", file=sys.stderr)
            failures.append(url)
    if failures:
        raise RuntimeError(f"{len(failures)}/{len(WEBHOOK_URLS)} webhook post(s) failed.")


def process_session(session, state=None, mark_notified=True):
    key = session["session_key"]
    results = api_get("session_result", session_key=key)
    if not results:
        return False

    drivers = get_drivers_by_number(key)
    is_race_or_sprint = session["session_type"] in STANDINGS_SESSION_TYPES
    intervals = get_final_intervals(key) if is_race_or_sprint else None
    table = build_results_table(results, drivers, intervals=intervals)
    title = (
        f"\U0001F3C1 {session['session_name']} Results - "
        f"{session['location']} {session['year']}"
    )

    embeds = [{
        "title": title,
        "description": f"```\n{table}\n```",
        "color": 0xE10600,
    }]

    if is_race_or_sprint:
        champ_drivers = api_get("championship_drivers", session_key=key)
        champ_teams = api_get("championship_teams", session_key=key)

        if champ_drivers:
            table_d = build_standings_table(
                champ_drivers,
                lambda s: drivers.get(s["driver_number"], {}).get(
                    "full_name", str(s["driver_number"])
                ),
            )
            embeds.append({
                "title": "\U0001F3C6 Drivers' Championship - Updated",
                "description": f"```\n{table_d}\n```",
                "color": 0xFFD700,
            })

        if champ_teams:
            table_t = build_standings_table(champ_teams, lambda s: s["team_name"])
            embeds.append({
                "title": "\U0001F3C6 Constructors' Championship - Updated",
                "description": f"```\n{table_t}\n```",
                "color": 0x1E90FF,
            })
        # Note: the championship endpoints are in beta and only cover race
        # sessions on OpenF1's side, so a Sprint may finish without a
        # standings update being available yet - that's expected.

    post_webhook(embeds)
    if mark_notified and state is not None:
        state["notified_session_keys"].append(key)
        save_state(state)
    return True


def parse_session_keys(args):
    keys = []
    for value in args.session_key:
        keys.extend(value)
    for value in args.session_keys:
        keys.extend(part.strip() for part in value.split(","))

    parsed = []
    for value in keys:
        if not value:
            continue
        try:
            parsed.append(int(value))
        except ValueError as exc:
            raise SystemExit(f"Invalid session key {value!r}; expected an integer.") from exc

    # Preserve user-supplied order while deduplicating.
    return list(dict.fromkeys(parsed))


def run_for_session_keys(session_keys, mark_notified=False):
    state = load_state() if mark_notified else None
    try:
        sessions, missing = get_sessions_by_keys(session_keys)

        for key in missing:
            print(f"Session key {key}: not found.")

        for session in sessions:
            sent = process_session(session, state=state, mark_notified=mark_notified)
            status = "posted to Discord" if sent else "results not published yet"
            print(
                f"{session['session_key']} - "
                f"{session['session_name']} ({session['location']} {session['year']}): "
                f"{status}"
            )
    except OpenF1AccessRestrictedError as exc:
        print(f"Can't fetch right now: {exc}", file=sys.stderr)


def run_once():
    try:
        state = load_state()
        notified = set(state["notified_session_keys"])
        sessions = get_recent_finished_sessions()

        if not state.get("bootstrapped"):
            state["notified_session_keys"] = [s["session_key"] for s in sessions]
            state["bootstrapped"] = True
            save_state(state)
            print(f"Bootstrapped. {len(sessions)} recent session(s) marked as already seen.")
            return

        new_sessions = [s for s in sessions if s["session_key"] not in notified]
        if not new_sessions:
            print("No new finished sessions.")
            return

        for session in new_sessions:
            sent = process_session(session, state)
            status = "posted to Discord" if sent else "results not published yet, will retry"
            print(f"{session['session_name']} ({session['location']} {session['year']}): {status}")
    except OpenF1AccessRestrictedError as exc:
        print(f"Skipping this check: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Post finished F1 session results to Discord.")
    parser.add_argument("--loop", action="store_true", help="Run continuously instead of once.")
    parser.add_argument("--interval", type=int, default=5, help="Minutes between checks (with --loop).")
    parser.add_argument(
        "--session-key",
        action="append",
        nargs="+",
        default=[],
        help="OpenF1 session key(s) to post immediately for testing. Can be repeated.",
    )
    parser.add_argument(
        "--session-keys",
        action="append",
        default=[],
        help="Comma-separated OpenF1 session keys to post immediately for testing.",
    )
    parser.add_argument(
        "--mark-notified",
        action="store_true",
        help="With --session-key/--session-keys, also record posted sessions in state.json.",
    )
    args = parser.parse_args()

    session_keys = parse_session_keys(args)
    if session_keys:
        if args.loop:
            raise SystemExit("--loop cannot be combined with explicit session keys.")
        run_for_session_keys(session_keys, mark_notified=args.mark_notified)
        return

    if args.mark_notified:
        raise SystemExit("--mark-notified only applies when using explicit session keys.")

    if args.loop:
        print(f"Starting loop, checking every {args.interval} minute(s)... (Ctrl+C to stop)")
        while True:
            try:
                run_once()
            except Exception as exc:
                print(f"Error during check: {exc}", file=sys.stderr)
            time.sleep(args.interval * 60)
    else:
        run_once()


if __name__ == "__main__":
    main()
