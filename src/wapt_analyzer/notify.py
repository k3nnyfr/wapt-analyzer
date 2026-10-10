"""Send the report summary by e-mail and to webhooks (JSON, Slack/Mattermost, Microsoft Teams)."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

import requests

from .config import read_secret_file, resolve_smtp_password
from .fetch import USER_AGENT, Cache
from .packages import OS_LABELS

log = logging.getLogger(__name__)

STATE_KEY = "notify-state"
MAX_ITEMS = 10

COUNTS = [  # summary key, label
    ("missing_packages", "paquets WAPT manquants dans le dépôt"),
    ("software_to_import", "logiciels à importer depuis le store"),
    ("software_unmanaged", "logiciels installés hors WAPT alors qu'un paquet existe"),
    ("software_unmatched", "logiciels sans équivalent"),
    ("outdated", "mises à jour disponibles dans le store"),
]


class NotifyError(RuntimeError):
    pass


def report_items(data: dict) -> dict[str, dict[str, str]]:
    """Notable report entries per section, keyed so that two runs can be compared, with a display label."""
    def os_(item):
        return OS_LABELS.get(item["os"], item["os"])

    return {
        "outdated": {f"{o['os']}|{o['local']['package']}|{o['store']['version']}":
                     f"{o['local']['package']} {o['local']['version']} → {o['store']['version']} ({os_(o)})"
                     for o in data["outdated"]},
        "missing_packages": {f"{m['os']}|{m['base']}":
                             f"{m['base']} ({os_(m)}, {m['host_count']} poste(s))" for m in data["missing_packages"]},
        "software_to_import": {f"{s['os']}|{s['key']}":
                               f"{s['names'][0]} → {s['match']['package']} ({os_(s)}, {s['host_count']} poste(s))"
                               for s in data["software_to_import"] if s.get("match")},
    }


CHANGE_LABELS = {
    "outdated": "Mises à jour",
    "missing_packages": "Paquets manquants",
    "software_to_import": "Logiciels à importer",
}


def new_items(previous: dict | None, current: dict[str, dict[str, str]]) -> dict[str, list[str]]:
    """Entries of ``current`` absent from the previous run (everything on the first run)."""
    previous = previous or {}
    return {section: [label for key, label in items.items() if key not in previous.get(section, {})]
            for section, items in current.items()}


def _bullets(items: list[str], bullet: str = "•") -> list[str]:
    lines = [f"{bullet} {i}" for i in items[:MAX_ITEMS]]
    if len(items) > MAX_ITEMS:
        lines.append(f"{bullet} … et {len(items) - MAX_ITEMS} autre(s)")
    return lines


def title(data: dict) -> str:
    ctx, sm = data["context"], data["summary"]
    prefix = f" (préfixe {ctx['prefix']})" if ctx.get("prefix") else ""
    return f"Rapport WAPT — {ctx.get('server_url', '')}{prefix}, {sm['hosts']} postes"


def summary_text(data: dict, changes: dict[str, list[str]], report_url: str = "", first_run: bool = False) -> str:
    sm = data["summary"]
    lines = [title(data), ""]
    lines += [f"• {sm[key]} {label}" for key, label in COUNTS]
    if any(changes.values()) and not first_run:
        lines += ["", "Nouveautés depuis le dernier envoi :"]
        for section, items in changes.items():
            if items:
                lines += ["", f"{CHANGE_LABELS[section]} :", *_bullets(items, "  -")]
    if report_url:
        lines += ["", f"Rapport complet : {report_url}"]
    return "\n".join(lines)


def subject(template: str, data: dict) -> str:
    sm = data["summary"]
    return template.format(**sm, server=data["context"].get("server_url", ""))


def send_email(mail: dict, cfg: dict, subject_: str, text: str, report_html: str | None) -> None:
    to = mail.get("to") or []
    if isinstance(to, str):
        to = [to]
    if not mail.get("smtp_host") or not to:
        raise NotifyError("e-mail: smtp_host and to are required in [notify.email]")
    msg = EmailMessage()
    msg["Subject"] = subject_
    msg["From"] = mail.get("from") or f"wapt-analyzer@{mail['smtp_host']}"
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    if report_html is not None and mail.get("attach_report", True):
        msg.add_attachment(report_html.encode("utf-8"), maintype="text", subtype="html",
                           filename="wapt-report.html")
    security = mail.get("security", "starttls")
    port = int(mail.get("smtp_port") or (465 if security == "ssl" else 587 if security == "starttls" else 25))
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            smtp = smtplib.SMTP_SSL(mail["smtp_host"], port, timeout=30, context=context)
        else:
            smtp = smtplib.SMTP(mail["smtp_host"], port, timeout=30)
        with smtp:
            if security == "starttls":
                smtp.starttls(context=context)
            if mail.get("user"):
                smtp.login(mail["user"], resolve_smtp_password(cfg))
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise NotifyError(f"e-mail via {mail['smtp_host']}:{port}: {e}") from e
    log.info("Report sent by e-mail to %s", ", ".join(to))


def webhook_payload(fmt: str, data: dict, changes: dict[str, list[str]], text: str, report_url: str) -> dict:
    if fmt == "slack":  # also Mattermost, Rocket.Chat and other Slack-compatible endpoints
        return {"text": text}
    if fmt == "teams":  # Microsoft Teams Workflows ("Post to a channel when a webhook request is received")
        sm = data["summary"]
        body = [
            {"type": "TextBlock", "text": title(data), "weight": "Bolder", "size": "Medium", "wrap": True},
            {"type": "FactSet", "facts": [{"title": str(sm[key]), "value": label} for key, label in COUNTS]},
        ]
        for section, items in changes.items():
            if items:
                body.append({"type": "TextBlock", "text": f"**{CHANGE_LABELS[section]}** (nouveau)", "wrap": True,
                             "spacing": "Medium"})
                body.append({"type": "TextBlock", "text": "\n".join(_bullets(items, "-")), "wrap": True})
        card = {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "version": "1.4", "body": body}
        if report_url:
            card["actions"] = [{"type": "Action.OpenUrl", "title": "Ouvrir le rapport", "url": report_url}]
        return {"type": "message", "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}
    if fmt == "json":
        return {"event": "wapt-analyzer.report", "generator": data["generator"],
                "generated_at": data["generated_at"], "context": data["context"], "summary": data["summary"],
                "new": changes, "report_url": report_url, "text": text}
    raise NotifyError(f"webhook: unknown format {fmt!r} (expected json, slack or teams)")


def send_webhook(hook: dict, data: dict, changes: dict[str, list[str]], text: str, report_url: str) -> None:
    url = hook.get("url") or (read_secret_file(hook["url_file"]) if hook.get("url_file") else "")
    if not url:
        raise NotifyError("webhook: url or url_file is required")
    fmt = hook.get("format", "json")
    payload = webhook_payload(fmt, data, changes, text, report_url)
    headers = {"User-Agent": USER_AGENT, **(hook.get("headers") or {})}
    name = hook.get("name") or fmt
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise NotifyError(f"webhook {name}: {e}") from e
    if resp.status_code >= 300:
        raise NotifyError(f"webhook {name}: HTTP {resp.status_code} {resp.text[:200]}")
    log.info("Report sent to webhook %s", name)


def notify(cfg: dict, data: dict, cache: Cache, report_html: str | None) -> int:
    """Send the summary to every configured destination; returns the number of failed destinations."""
    conf = cfg["notify"]
    mail, hooks = conf.get("email") or {}, conf.get("webhook") or []
    if isinstance(hooks, dict):
        hooks = [hooks]
    if not mail and not hooks:
        raise NotifyError("--notify: no destination configured ([notify.email] or [[notify.webhook]])")
    when = conf.get("when", "always")
    if when not in ("always", "changes"):
        raise NotifyError(f"[notify] when: {when!r} (expected always or changes)")

    current = report_items(data)
    state = cache.read_json(STATE_KEY)
    changes = new_items(state, current)
    if when == "changes" and state is not None and not any(changes.values()):
        log.info("Nothing new since the last notification: nothing sent")
        return 0

    report_url = conf.get("report_url", "")
    text = summary_text(data, changes, report_url, first_run=state is None)
    failures = 0
    destinations = ([("e-mail", lambda: send_email(mail, cfg, subject(conf["subject"], data),
                                                    text, report_html))] if mail else [])
    destinations += [(h.get("name") or h.get("format", "json"),
                      lambda h=h: send_webhook(h, data, changes, text, report_url)) for h in hooks]
    for _, send in destinations:
        try:
            send()
        except NotifyError as e:
            log.error("%s", e)
            failures += 1
    if failures < len(destinations):  # at least one delivery: the next "changes" run compares with this one
        cache.write_json(STATE_KEY, current)
    return failures

