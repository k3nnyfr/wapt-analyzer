import copy
import http.server
import json
import threading

import pytest

from wapt_analyzer.config import DEFAULTS
from wapt_analyzer.fetch import Cache
from wapt_analyzer.notify import NotifyError, notify, report_items, summary_text, webhook_payload


def report(outdated=("tsi-firefox",), missing=("keepassxc",)):
    return {
        "generator": "wapt-analyzer test", "generated_at": "2026-10-10T08:00:00+02:00",
        "context": {"server_url": "https://wapt.example.org", "prefix": "tsi"},
        "summary": {"hosts": 12, "missing_packages": len(missing), "software_to_import": 1,
                    "software_unmanaged": 0, "software_unmatched": 3, "software_folded": 0,
                    "outdated": len(outdated)},
        "outdated": [{"os": "windows", "local": {"package": p, "version": "1.0-1"}, "store": {"version": "2.0-1"}}
                     for p in outdated],
        "missing_packages": [{"os": "windows", "base": b, "host_count": 2} for b in missing],
        "software_to_import": [{"os": "macos", "key": "gimp", "names": ["GIMP"], "host_count": 1,
                                "match": {"package": "tis-gimp"}}],
    }


@pytest.fixture
def cfg():
    return copy.deepcopy(DEFAULTS)


@pytest.fixture
def hook_server():
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, dict(self.headers), json.loads(body)))
            self.send_response(500 if self.path == "/broken" else 200)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", received
    httpd.shutdown()


def test_summary_and_payloads():
    data = report()
    changes = {"outdated": ["tsi-firefox 1.0-1 → 2.0-1 (Windows)"], "missing_packages": [], "software_to_import": []}
    text = summary_text(data, changes, "https://intranet/wapt-report.html")
    assert text.startswith("Rapport WAPT — https://wapt.example.org (préfixe tsi), 12 postes")
    assert "• 1 mises à jour disponibles dans le store" in text
    assert "Mises à jour :\n  - tsi-firefox 1.0-1 → 2.0-1 (Windows)" in text
    assert "Paquets manquants :" not in text                      # nothing new in this section
    assert text.endswith("Rapport complet : https://intranet/wapt-report.html")
    assert "Nouveautés" not in summary_text(data, changes, first_run=True)

    assert webhook_payload("slack", data, changes, text, "") == {"text": text}
    card = webhook_payload("teams", data, changes, text, "https://r")["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard" and card["actions"][0]["url"] == "https://r"
    payload = webhook_payload("json", data, changes, text, "")
    assert payload["summary"]["hosts"] == 12 and payload["new"] == changes
    with pytest.raises(NotifyError, match="unknown format"):
        webhook_payload("xml", data, changes, text, "")


def test_report_items_keys():
    items = report_items(report())
    assert list(items["outdated"]) == ["windows|tsi-firefox|2.0-1"]
    assert items["software_to_import"]["macos|gimp"] == "GIMP → tis-gimp (macOS, 1 poste(s))"


def test_webhooks_and_changes(cfg, tmp_path, hook_server):
    url, received = hook_server
    secret_url = tmp_path / "hook-url"
    secret_url.write_text(f"{url}/secret\n")
    secret_url.chmod(0o600)
    cfg["notify"].update(when="changes", webhook=[
        {"url": f"{url}/json", "headers": {"Authorization": "Bearer t0ken"}},
        {"url_file": str(secret_url), "format": "slack", "name": "chat"},
    ])
    cache = Cache(tmp_path / "cache")

    assert notify(cfg, report(), cache, None) == 0                # first run: always sent
    assert [r[0] for r in received] == ["/json", "/secret"]
    assert received[0][1]["Authorization"] == "Bearer t0ken"
    assert "Nouveautés" not in received[1][2]["text"]

    received.clear()
    assert notify(cfg, report(), cache, None) == 0                # nothing new: nothing sent
    assert received == []

    assert notify(cfg, report(outdated=("tsi-firefox", "tsi-vlc")), cache, None) == 0
    assert "tsi-vlc 1.0-1 → 2.0-1" in received[1][2]["text"] and "tsi-firefox" not in received[1][2]["text"]
    assert received[0][2]["new"]["outdated"] == ["tsi-vlc 1.0-1 → 2.0-1 (Windows)"]


def test_failed_delivery_keeps_previous_state(cfg, tmp_path, hook_server):
    url, received = hook_server
    cfg["notify"].update(when="changes", webhook={"url": f"{url}/broken"})
    cache = Cache(tmp_path / "cache")
    assert notify(cfg, report(), cache, None) == 1
    assert notify(cfg, report(), cache, None) == 1                # not marked as sent: tried again
    assert len(received) == 2

    cfg["notify"]["webhook"] = []
    with pytest.raises(NotifyError, match="no destination"):
        notify(cfg, report(), cache, None)


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.calls = host, port, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        FakeSMTP.sent.append((self.host, self.port, self.calls, msg))


def test_email(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    monkeypatch.setenv("WAPT_SMTP_PASSWORD", "smtp-pw")
    cfg["notify"]["email"] = {"smtp_host": "smtp.example.org", "user": "bot", "from": "wapt@example.org",
                              "to": ["admin@example.org", "team@example.org"]}
    assert notify(cfg, report(), Cache(tmp_path / "cache"), "<html>rapport</html>") == 0
    host, port, calls, msg = FakeSMTP.sent[-1]
    assert (host, port) == ("smtp.example.org", 587)
    assert calls == ["starttls", ("login", "bot", "smtp-pw")]
    assert msg["Subject"] == "Rapport WAPT : 1 paquets manquants, 1 mises à jour"
    assert msg["To"] == "admin@example.org, team@example.org"
    attachment = next(msg.iter_attachments())
    assert attachment.get_filename() == "wapt-report.html" and attachment.get_content() == "<html>rapport</html>"

    cfg["notify"]["email"] = {"smtp_host": "smtp.example.org"}
    assert notify(cfg, report(), Cache(tmp_path / "cache2"), None) == 1   # no recipient: reported as failed
