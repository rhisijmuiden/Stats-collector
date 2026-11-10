# Microsoft 365 (Entra ID)

From phase 1, colleagues sign in with their Microsoft 365 account and get their role from a Microsoft 365 group. You can create the app registration and fill in the settings now under **Administration → Roles & sign-in**.

## 1. App registration

1. Open the [Entra admin center](https://entra.microsoft.com) → **Identity → Applications → App registrations → New registration**.
2. Name: *Stats Collector*. Supported account types: **Accounts in this organizational directory only (single tenant)**.
3. Redirect URI: platform **Web**, value: copy it from **Roles & sign-in → Redirect URI** in Stats Collector (it looks like `https://stats.example.org/api/auth/entra/callback`).
4. Click **Register**. Copy the **Application (client) ID** and **Directory (tenant) ID** into Stats Collector.
5. **Certificates & secrets → New client secret**, valid for 24 months. Copy the *Value* (not the ID) into **Client secret**. Put a reminder in your calendar to renew it.
6. **Token configuration → Add groups claim → Security groups**, for the *ID* token, format *Group ID*.
7. **API permissions**: `openid`, `profile`, `email` and `User.Read` (delegated) are enough. Click **Grant admin consent**.

## 2. Groups for roles

Create four security groups in Microsoft 365 (names are an example):

| Role | Group |
| --- | --- |
| Admin | `SC-Admins` |
| Editor-in-chief | `SC-EditorsInChief` |
| Editor | `SC-Editors` |
| Staff | everyone else in the organisation (no group needed) |

Copy each group's **Object ID** into **Roles & sign-in → Roles from Microsoft 365 groups**. Membership is read at every sign-in, so adding or removing someone in Microsoft 365 changes their role the next time they sign in.

## 3. Local accounts

Keep **Also allow local accounts to sign in** on until Microsoft 365 sign-in works. Administrators can always sign in with a local account, so a broken Entra configuration never locks you out.
