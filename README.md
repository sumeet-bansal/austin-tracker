# Austin PCT Tracker

Daily Slack bot that posts Austin Carter's PCT hiking progress to `#austin-tracker`. Runs daily at 11:30am ET — posts whenever there are new trail updates, and always on Fridays.

Scrapes [hike.austinscarter.com](https://hike.austinscarter.com) (Next.js SSR — no public API) and posts miles hiked, day on trail, pace, elevation gain, recent trail updates, and a Mapbox trail progress map.

## Slack App Setup

See [`slack/README.md`](slack/README.md) for creating the Slack app, installing it, and getting the bot token.

## Setup

```sh
cp .env.example .env  # fill in your values
uv sync
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | Yes | `xoxb-...` bot token with `chat:write` scope |
| `SLACK_CHANNEL_ID` | Yes | Target channel (e.g. `C0123456789`) |
| `MAPBOX_TOKEN` | No | Enables trail progress map in the message |

## Running

```sh
uv run python main.py
```

## Deployment

Deployed to Railway with a daily cron schedule (`30 15 * * *` UTC = 11:30am ET).

The cron schedule is defined in `railway.json` and syncs to the Railway dashboard on deploy. If the cron stops firing, check that the schedule still appears in the dashboard (Service Settings > Cron Schedule) — Railway's config-as-code cron sync has been flaky historically.

