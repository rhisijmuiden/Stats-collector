# Microsoft 365 (Entra ID)

Colleagues sign in with their Microsoft 365 account (button **Sign in with Microsoft 365** on the sign-in page) and get their role from Microsoft 365: from an app role (easiest) or from a group. Set it up under **Administration → Roles & sign-in**.

![Roles & sign-in](../images/en-sso.png)

## 1. App registration

1. Open the [Entra admin center](https://entra.microsoft.com) → **Identity → Applications → App registrations → New registration**.
2. Name: *Stats Collector*. Supported account types: **Accounts in this organizational directory only (single tenant)**.
3. Redirect URI: platform **Web**, value: copy it from **Roles & sign-in → Redirect URI** in Stats Collector (it looks like `https://stats.example.org/api/auth/entra/callback`).
4. Click **Register**. Copy the **Application (client) ID** and **Directory (tenant) ID** into Stats Collector.
5. **Certificates & secrets → New client secret**, valid for 24 months. Copy the *Value* (not the ID) into **Client secret**. Put a reminder in your calendar to renew it.
6. Only if you use groups instead of app roles (see 2b): **Token configuration → Add groups claim → Security groups**, for the *ID* token, format *Group ID*.
7. **API permissions**: `openid`, `profile`, `email` and `User.Read` (delegated) are enough. Click **Grant admin consent**.

## 2. Roles

### 2a. App roles (recommended)

With app roles you never have to look up an object ID. Stats Collector knows these values by itself:

| Role | Value | Display name |
| --- | --- | --- |
| Admin | `StatsCollector.Admin` | Stats Collector admin |
| Editor-in-chief | `StatsCollector.EditorInChief` | Stats Collector editor-in-chief |
| Editor | `StatsCollector.Editor` | Stats Collector editor |
| Staff | `StatsCollector.Staff` | Stats Collector staff |

1. In the app registration open **App roles → Create app role** and create the four roles: allowed member types **Users/Groups**, display name and value from the table, any description, **Enable** on. The table is also on **Roles & sign-in**, with a copy button next to each value.
   *Faster:* click **Copy manifest JSON** on **Roles & sign-in**, open **Manifest** in the app registration and paste the copied entries between the square brackets of `"appRoles": [ ]`. Click **Save**.
2. Open **Enterprise applications → Stats Collector → Users and groups → Add user/group**, pick people or a group and the role. Assigning a group needs Entra ID P1 or higher; on other plans assign people.
3. Optional: under **Enterprise applications → Stats Collector → Properties** set **Assignment required** to *Yes*, so only people with a role can sign in.

Entra puts the role in the sign-in token, so no extra permission or token setting is needed. The role is read at every sign-in: changing someone's assignment changes their role the next time they sign in. Someone with several roles gets the highest (Admin, then Editor-in-chief, Editor, Staff); someone without a role gets the role under **Role for everyone else in the organisation**.

### 2b. Groups (alternative)

Prefer to work with security groups you already have? Paste each group's **Object ID** (Entra → Groups → the group → Overview) into **Roles & sign-in → Roles from Microsoft 365 groups**; separate several IDs per role with commas. This needs the groups claim from step 6 of part 1. Groups and app roles can be combined; the highest role wins.

When a person is a member of more than about 200 groups, Microsoft leaves the groups out of the sign-in token. Stats Collector then reads them from Microsoft Graph; for that add the delegated permission `GroupMember.Read.All` with admin consent. App roles do not have this limit.

## 3. Switch it on and test

1. Fill in the tenant ID, client ID and client secret (and the group IDs if you use groups), and switch on **Enable Microsoft 365 sign-in**. Click **Save**.
2. Open the sign-in page in a private browser window and click **Sign in with Microsoft 365**.
3. After signing in you land on the dashboard; your role is shown at the bottom of the menu. **Users** lists the account with sign-in method *Microsoft 365*.

Does it fail? The sign-in page shows the reason, for example a wrong client secret or redirect URI. The most common mistake is a redirect URI that does not match exactly: it must be the `https://` address users open, so check `SC_PUBLIC_URL` (see [Reverse proxy](reverse-proxy.md)).

## 4. Local accounts

An existing local account with the same e-mail address is linked on the first Microsoft sign-in. It keeps its password and the role set in Stats Collector, so your first administrator stays a working break-glass account. Accounts created by Microsoft sign-in get their role from Microsoft 365 at every sign-in.

Keep **Also allow local accounts to sign in** on until Microsoft 365 sign-in works. Administrators can always sign in with a local account, so a broken Entra configuration never locks you out.
