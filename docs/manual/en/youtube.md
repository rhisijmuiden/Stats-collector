# YouTube

The YouTube connector arrives in phase 2. It uses the **YouTube Data API v3** (videos, subscribers) and the **YouTube Analytics API** (views, watch time, average view duration, subscribers gained and lost). Google requires verification for the Analytics scope, so prepare the project now.

## 1. Google Cloud project

1. Open [console.cloud.google.com](https://console.cloud.google.com) with the Google account that owns (or manages) the YouTube channel → **New project** *Stats Collector*.
2. **APIs & Services → Library**: enable **YouTube Data API v3** and **YouTube Analytics API**.

## 2. OAuth consent screen

1. **APIs & Services → OAuth consent screen**. User type: **External** (unless the channel is in your Google Workspace; then *Internal* needs no verification).
2. App name *Stats Collector*, support email, logo, home page (`https://stats.example.org`), privacy policy URL, authorised domain `example.org`.
3. Scopes: `https://www.googleapis.com/auth/youtube.readonly` and `https://www.googleapis.com/auth/yt-analytics.readonly`.
4. Add yourself as a test user so you can connect before verification.
5. **Publish app** and click **Prepare for verification**. Google asks for a video of the consent flow and an explanation; use the same wording as for Meta.

## 3. Credentials

**APIs & Services → Credentials → Create credentials → OAuth client ID**, type **Web application**, redirect URI `https://stats.example.org/api/connectors/youtube/callback`. Keep the client ID and secret for phase 2.

## Limits

- The Data API has a daily quota of 10,000 units; Stats Collector stays well within it.
- Analytics numbers lag one to two days; recent views on the live wall are estimated from view-count changes.
