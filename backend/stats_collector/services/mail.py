"""Outgoing email: Microsoft Graph sendMail from one mailbox, or a configurable SMTP server
(STARTTLS / implicit TLS, password or XOAUTH2). With Graph chosen, SMTP is the fallback when set up."""

from __future__ import annotations

import base64
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

import httpx

from ..security import decrypt_secret


class MailError(Exception):
    pass


GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
GRAPH_ATTACHMENT_LIMIT = 3 * 1024 * 1024  # larger attachments need an upload session; reports stay below


@dataclass
class OutgoingMail:
    to: list[str]
    subject: str
    text: str
    html: str | None = None
    attachments: list[tuple[str, str, bytes]] = field(default_factory=list)  # (file name, mime type, content)


def tls_context(verify: bool = True) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_oauth_token(cfg: dict) -> str:
    """Client-credentials token for SMTP XOAUTH2 (e.g. Microsoft 365 or Google Workspace)."""
    secret = decrypt_secret(cfg.get("oauth_client_secret_enc"))
    if not (cfg.get("oauth_token_url") and cfg.get("oauth_client_id") and secret):
        raise MailError("oauth_not_configured")
    resp = httpx.post(
        cfg["oauth_token_url"],
        data={
            "grant_type": "client_credentials",
            "client_id": cfg["oauth_client_id"],
            "client_secret": secret,
            "scope": cfg.get("oauth_scope") or "",
        },
        timeout=cfg.get("timeout", 20),
    )
    if resp.status_code != 200:
        raise MailError(f"oauth_token_failed: HTTP {resp.status_code}")
    token = resp.json().get("access_token")
    if not token:
        raise MailError("oauth_token_failed: no access_token")
    return token


def build_message(cfg: dict, mail: OutgoingMail) -> EmailMessage:
    if not cfg.get("from_address"):
        raise MailError("from_address_missing")
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.get("from_name") or "", cfg["from_address"]))
    msg["To"] = ", ".join(mail.to)
    if cfg.get("reply_to"):
        msg["Reply-To"] = cfg["reply_to"]
    msg["Subject"] = mail.subject
    msg["Date"] = formatdate(localtime=False)
    domain = cfg["from_address"].rsplit("@", 1)[-1]
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.set_content(mail.text)
    if mail.html:
        msg.add_alternative(mail.html, subtype="html")
    for name, mime, content in mail.attachments:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(content, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
    return msg


def configured(cfg: dict) -> bool:
    """Whether any route is set up."""
    graph = cfg.get("transport") == "graph" and cfg.get("graph_tenant_id") and cfg.get("graph_client_id")
    return bool(graph or cfg.get("host"))


def send(cfg: dict, mail: OutgoingMail) -> None:
    """Send through the chosen route; with Graph, fall back to SMTP when a server is set up."""
    if cfg.get("transport") == "graph":
        try:
            send_graph(cfg, mail)
            return
        except MailError:
            if not cfg.get("host"):
                raise
    send_smtp(cfg, mail)


def graph_token(cfg: dict) -> str:
    tenant = (cfg.get("graph_tenant_id") or "").strip()
    secret = decrypt_secret(cfg.get("graph_client_secret_enc"))
    if not (tenant and (cfg.get("graph_client_id") or "").strip() and secret):
        raise MailError("graph_not_configured")
    try:
        resp = httpx.post(
            f"{LOGIN}/{tenant}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": cfg["graph_client_id"].strip(),
                "client_secret": secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=cfg.get("timeout", 20),
        )
    except httpx.HTTPError as exc:
        raise MailError(f"graph_token_failed: {exc}") from exc
    if resp.status_code != 200:
        raise MailError(f"graph_token_failed: HTTP {resp.status_code}")
    token = resp.json().get("access_token")
    if not token:
        raise MailError("graph_token_failed: no access_token")
    return token


def graph_message(cfg: dict, mail: OutgoingMail) -> dict:
    sender = (cfg.get("graph_mailbox") or cfg.get("from_address") or "").strip()
    if not sender:
        raise MailError("graph_mailbox_missing")
    body = {"contentType": "HTML", "content": mail.html} if mail.html else {"contentType": "Text", "content": mail.text}
    message: dict = {
        "subject": mail.subject,
        "body": body,
        "toRecipients": [{"emailAddress": {"address": a}} for a in mail.to],
        "from": {"emailAddress": {"address": sender, "name": cfg.get("from_name") or ""}},
    }
    if cfg.get("reply_to"):
        message["replyTo"] = [{"emailAddress": {"address": cfg["reply_to"]}}]
    if mail.attachments:
        if sum(len(c) for _, _, c in mail.attachments) > GRAPH_ATTACHMENT_LIMIT:
            raise MailError("attachment_too_large")
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": name,
                "contentType": mime,
                "contentBytes": base64.b64encode(content).decode(),
            }
            for name, mime, content in mail.attachments
        ]
    return {"sender": sender, "body": {"message": message, "saveToSentItems": True}}


def send_graph(cfg: dict, mail: OutgoingMail) -> None:
    """Microsoft Graph sendMail as the mailbox (application permission Mail.Send, limited to that
    mailbox by an application access policy)."""
    built = graph_message(cfg, mail)
    token = graph_token(cfg)
    try:
        resp = httpx.post(
            f"{GRAPH}/users/{built['sender']}/sendMail",
            json=built["body"],
            headers={"Authorization": f"Bearer {token}"},
            timeout=cfg.get("timeout", 20) + 20,
        )
    except httpx.HTTPError as exc:
        raise MailError(f"graph_send_failed: {exc}") from exc
    if resp.status_code != 202:
        try:
            detail = resp.json().get("error", {}).get("code") or ""
        except ValueError:
            detail = ""
        raise MailError(f"graph_send_failed: HTTP {resp.status_code} {detail}".strip())


def send_smtp(cfg: dict, mail: OutgoingMail) -> None:
    if not cfg.get("host"):
        raise MailError("smtp_host_missing")
    msg = build_message(cfg, mail)
    ctx = tls_context(cfg.get("verify_tls", True))
    timeout = cfg.get("timeout", 20)
    port = int(cfg.get("port") or (465 if cfg.get("security") == "ssl" else 587))
    try:
        if cfg.get("security") == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(cfg["host"], port, timeout=timeout, context=ctx)
        else:
            client = smtplib.SMTP(cfg["host"], port, timeout=timeout)
        with client:
            client.ehlo()
            if cfg.get("security") == "starttls":
                client.starttls(context=ctx)
                client.ehlo()
            auth = cfg.get("auth", "password")
            if auth == "password" and cfg.get("username"):
                client.login(cfg["username"], decrypt_secret(cfg.get("password_enc")) or "")
            elif auth == "xoauth2":
                token = fetch_oauth_token(cfg)
                raw = f"user={cfg['username']}\x01auth=Bearer {token}\x01\x01"
                code, resp = client.docmd("AUTH", "XOAUTH2 " + base64.b64encode(raw.encode()).decode())
                if code != 235:
                    raise MailError(f"xoauth2_failed: {code} {resp.decode(errors='replace')}")
            client.send_message(msg)
    except MailError:
        raise
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise MailError(f"{type(exc).__name__}: {exc}") from exc


TEST_MAIL = {
    "en": (
        "Stats Collector test email",
        "This is a test email from Stats Collector. Your mail server settings work.",
    ),
    "nl": (
        "Testmail van Stats Collector",
        "Dit is een testmail van Stats Collector. Je mailserverinstellingen werken.",
    ),
}


def test_mail(to: str, language: str) -> OutgoingMail:
    subject, body = TEST_MAIL.get(language, TEST_MAIL["en"])
    html = f'<p style="font-family:Inter,Arial,sans-serif">{body}</p>'
    return OutgoingMail(to=[to], subject=subject, text=body, html=html)
