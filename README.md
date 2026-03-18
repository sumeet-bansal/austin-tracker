# Austin PCT Tracker

Weekly Slack bot that posts Austin Carter's PCT hiking progress to `#austin-tracker` every Friday at 4pm ET.

Scrapes [hike.austinscarter.com](https://hike.austinscarter.com) (Next.js SSR — no public API) and posts miles hiked, day on trail, pace, elevation gain, recent trail updates, and a Mapbox trail progress map.

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

Deployed to Railway (Traba workspace) with a cron schedule (`0 20 * * 5` = Fridays 8pm UTC / 4pm ET). Config lives in `railway.json`.

Build uses nixpacks with uv (`nixpacks.toml`).
