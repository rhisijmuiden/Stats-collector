# Email (SMTP)

Stats Collector sends notifications and (from phase 4) reports through your own SMTP server. Open **Administration → Email**.

![Email screen](../images/en-email.png)

## Settings

| Field | Explanation |
| --- | --- |
| Send email | Master switch |
| SMTP server, port | e.g. `smtp.office365.com` and `587` |
| Encryption | **STARTTLS** (port 587, recommended), **SSL/TLS** (SMTPS, port 465) or none (only on a trusted local network). TLS 1.2 is the minimum. |
| Verify the server certificate | Leave on. Only switch off for an internal server with a self-signed certificate. |
| Authentication | Username and password, OAuth 2.0 (XOAUTH2) or none |
| From address, name, reply-to | What recipients see |

The buttons **Microsoft 365**, **Google Workspace** and **SMTPS (465)** fill in the server, port and encryption.

Passwords and secrets are stored encrypted. The screen only shows that a value is stored; leave the field empty to keep it.

## Test

Enter an address under **Test** and click **Send test email**. The settings are saved first. If sending fails, the exact error from the mail server is shown, for example `535 Authentication unsuccessful`.

## Microsoft 365 with OAuth 2.0

Microsoft is switching off basic authentication for SMTP. Use OAuth 2.0 instead:

1. In the [Entra admin center](https://entra.microsoft.com) go to **App registrations → New registration**, name it *Stats Collector mail*.
2. **API permissions → Add a permission → APIs my organization uses → Office 365 Exchange Online → Application permissions → SMTP.SendAsApp**. Click **Grant admin consent**.
3. **Certificates & secrets → New client secret**. Copy the value.
4. In Exchange Online PowerShell register the app and give it rights on the sending mailbox:
   ```powershell
   New-ServicePrincipal -AppId <client-id> -ObjectId <enterprise-app-object-id>
   Add-MailboxPermission -Identity stats@example.org -User <enterprise-app-object-id> -AccessRights FullAccess
   ```
5. In Stats Collector choose **OAuth 2.0 (XOAUTH2)**:
   - Username: the mailbox, e.g. `stats@example.org`
   - Token URL: `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token`
   - Scope: `https://outlook.office365.com/.default`
   - Client ID and client secret from steps 1 and 3
6. Send a test email.

Sending through the Microsoft Graph API (instead of SMTP) arrives with the reports in phase 4.
