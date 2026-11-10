# Meta: Facebook and Instagram

The Facebook and Instagram connector arrives in phase 3. Meta's App Review takes days to weeks, so start now. You need:

- a **Meta Business portfolio** (Business Manager) that is **verified** (done for this project);
- the **Facebook Page** you want to measure, with you as admin in the Business portfolio;
- the **Instagram professional account** (Business or Creator) linked to that Page.

## 1. Create the app

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps) → **Create app**.
2. Use case: **Other** → app type **Business**.
3. Name: *Stats Collector*, contact email, and select your verified **Business portfolio**.
4. In **App settings → Basic** fill in the privacy policy URL, terms URL, app icon (1024×1024) and category *Business and pages*. Save.

## 2. Add products

- **Facebook Login for Business** (used once by an administrator to grant access to the Page).
- **Instagram Graph API** (via *Add product → Instagram*), choose *API setup with Facebook login*.

## 3. Permissions to request

| Permission | Why |
| --- | --- |
| `pages_show_list` | List the Pages the administrator manages |
| `pages_read_engagement` | Posts, reactions, comments, shares, followers |
| `read_insights` | Page and post insights (reach, views, clicks) |
| `business_management` | Pages owned by the Business portfolio |
| `instagram_basic` | Instagram account and media |
| `instagram_manage_insights` | Instagram reach, views, saves, profile visits |

## 4. App Review

1. **App Review → Permissions and features**: click **Request advanced access** for each permission above.
2. For each, describe how it is used: *"Stats Collector is an internal analytics dashboard for our newsroom. An administrator connects our own Page and Instagram account once; we read insights for our own content and show them to staff in dashboards and monthly reports. No data is shared with third parties."*
3. Upload a short screen recording. Meta wants to see the login flow and where the data appears. Until the connector exists, record the Stats Collector dashboard and explain which numbers will appear; Meta may ask for a new recording once the connector is in place (phase 3).
4. Complete **Data handling questions** and submit.
5. Switch the app to **Live** mode after approval.

Meta changes metric names regularly; Stats Collector keeps them configurable so a rename does not break the connector.

*Screenshots of these steps are added when the connector is built.*
