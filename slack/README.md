# Slack App Setup

## Create the app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From a manifest**
2. Select your workspace, paste the contents of `manifest.yaml`, and create the app
3. Under **Basic Information** → **Display Information**, upload `icon.png` as the app icon

## Install the app

1. Go to **OAuth & Permissions** → **Install to Workspace**
2. Copy the **Bot User OAuth Token** (`xoxb-...`)

## Configure environment variables

Set the following in Railway (or your `.env` for local runs):

```
SLACK_BOT_TOKEN=xoxb-...      # from the step above
SLACK_CHANNEL_ID=C...          # right-click the channel in Slack → Copy Link → last segment
MAPBOX_TOKEN=pk...             # optional — enables trail progress map
```

## Invite the bot

In Slack, invite the bot to your channel:
```
/invite @Austin PCT Tracker
```
