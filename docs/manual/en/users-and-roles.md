# First sign-in, users and roles

## Signing in

Sign in with your email address and password. After ten wrong attempts from the same address within five minutes, the login is blocked for a few minutes.

## Two-factor authentication

Every local account can turn on two-factor authentication: **My profile** (click your initials at the bottom of the menu) → **Two-factor authentication → Turn on**. Add the key to an authenticator app such as Microsoft Authenticator, Google Authenticator or 1Password and enter the code it shows. From then on, sign-in asks for the 6-digit code.

Lost your phone? An administrator on the server can reset the password, which also switches two-factor authentication off:

```bash
stats-collector reset-password name@example.org
```

## Users

Administrators manage accounts in **Administration → Users**: add, change role, disable, reset a password or delete. There is always at least one active administrator; the app refuses to remove the last one.

## Roles

| Role | Sees | Can |
| --- | --- | --- |
| Admin | Everything | Sources, users, branding, email, backup, updates, live walls |
| Editor-in-chief | Everything, including numbers per editor | Dashboards, reports and goals; send reports |
| Editor | All items and channels, plus their own editor numbers | Own dashboards, on-demand reports |
| Staff | All items, channels, followers and goals without editor names | View only |

Editor names and per-editor numbers are removed on the server before data reaches the browser of Staff and Editors.

## Microsoft 365

From phase 1 colleagues can sign in with their Microsoft 365 account and get their role from a Microsoft 365 group. The settings can already be prepared: see [Microsoft 365](microsoft-365.md).
