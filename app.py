"""Button page for the user. Start via the 'eBay Buchhaltung.command' file.

Runs only on this Mac (127.0.0.1); every form carries a random token so
other websites can't trigger actions.
"""
import secrets
import socket
import sys
import threading
import traceback
import webbrowser
from datetime import date

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

from ebay_tool import service
from ebay_tool.config import ConfigError, ebay_missing, load_config, sevdesk_configured
from ebay_tool.csv_import import ImportError_, template_csv
from ebay_tool.ebay_api import EbayError
from ebay_tool.ebay_auth import AuthError, consent_url, finish_login, login_state
from ebay_tool.sevdesk import SevdeskError
from ebay_tool.summary import month_label

PORT = 8765
KNOWN_ERRORS = (ConfigError, AuthError, EbayError, SevdeskError, ImportError_, ValueError)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
CSRF = secrets.token_urlsafe(24)


@app.template_filter("eur")
def eur(d):
    s = "{:,.2f}".format(d)
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


@app.template_filter("monthname")
def monthname(key):
    return month_label(key)


def _check_csrf():
    if request.form.get("csrf") != CSRF:
        abort(403)


def _period():
    f = request.values.get("from_month") or service.last_month()
    t = request.values.get("to_month") or f
    return f, t


def _page(messages=None, **extra):
    from_month, to_month = _period()
    ctx = {"csrf": CSRF, "from_month": from_month, "to_month": to_month,
           "messages": messages or [], "this_year": date.today().year}
    try:
        cfg = load_config(require_ebay=False)
        ctx["ebay_ready"] = ebay_missing(cfg) is None
        ctx["ebay_login"] = login_state() if ctx["ebay_ready"] else "none"
        ctx["sevdesk_ready"] = sevdesk_configured(cfg)
        if ctx["ebay_ready"]:
            ctx["consent_url"] = consent_url(cfg["ebay"])
        start, end = service.month_range(from_month, to_month)
        ctx["period_label"] = "%s – %s" % (start.strftime("%d.%m.%Y"), end.strftime("%d.%m.%Y"))
        ctx["overview"] = service.overview(cfg, start, end)
    except KNOWN_ERRORS as e:
        if ("danger", str(e)) not in ctx["messages"]:
            ctx["messages"].append(("danger", str(e)))
    ctx.update(extra)
    return render_template("index.html", **ctx)


def _run(action):
    try:
        return action()
    except KNOWN_ERRORS as e:
        return _page([("danger", str(e))])
    except Exception as e:  # unexpected: show it, log details
        traceback.print_exc()
        return _page([("danger", "Unerwarteter Fehler: %s (Details im Terminal-Fenster)" % e)])


@app.get("/")
def index():
    return _page()


@app.post("/login")
def login():
    _check_csrf()

    def go():
        cfg = load_config()
        finish_login(cfg["ebay"], request.form.get("pasted", ""))
        return _page([("ok", "eBay-Anmeldung gespeichert.")])
    return _run(go)


@app.post("/fetch")
def fetch():
    _check_csrf()

    def go():
        cfg = load_config()
        start, end = service.month_range(*_period())
        r = service.fetch_from_ebay(cfg, start, end)
        msg = ("Von eBay geholt: %d Verkäufe, %d Käufe, %d Gebühren-Posten (%d neu)."
               % (r["found"]["sales"], r["found"]["purchases"], r["found"]["fees"], sum(r["new"].values())))
        return _page([("ok", msg)] + [("warn", w) for w in r["warnings"]])
    return _run(go)


@app.post("/excel")
def excel():
    _check_csrf()

    def go():
        cfg = load_config(require_ebay=False)
        start, end = service.month_range(*_period())
        path = service.export_excel(cfg, start, end)
        return send_file(path, as_attachment=True, download_name=path.name)
    return _run(go)


@app.post("/import")
def import_csv():
    _check_csrf()

    def go():
        f = request.files.get("file")
        if not f or not f.filename:
            raise ValueError("Bitte eine CSV-Datei auswählen.")
        raw = f.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        r = service.import_purchases_csv(text)
        return _page([("ok", "%d Käufe importiert (%d neu)." % (r["rows"], r["new"]))])
    return _run(go)


@app.get("/vorlage.csv")
def csv_template():
    return app.response_class("﻿" + template_csv(), mimetype="text/csv",
                              headers={"Content-Disposition": "attachment; filename=Kaeufe_Vorlage.csv"})


@app.post("/belege")
def belege():
    _check_csrf()

    def go():
        cfg = load_config(require_ebay=False)
        start, end = service.month_range(*_period())
        r = service.export_receipts(cfg, start, end)
        c = r["counts"]
        if not any(c.values()):
            return _page([("warn", "Keine Belege im Zeitraum. Zuerst „Daten von eBay holen“.")]
                         + [("warn", n) for n in r["notes"]])
        service.open_in_finder(r["folder"])
        msg = ("Belege erstellt: %d Einkäufe, %d Verkaufs-Sammelbelege, %d Gebühren-Übersichten, "
               "%d Erstattungs-Belege. Ordner: %s" % (c["purchases"], c["sales"], c["fees"], c["refunds"], r["folder"]))
        return _page([("ok", msg)] + [("warn", n) for n in r["notes"]])
    return _run(go)


@app.post("/preview")
def preview():
    _check_csrf()

    def go():
        start, end = service.month_range(*_period())
        vouchers, notes = service.preview_sevdesk(start, end)
        return _page([("warn", n) for n in notes], preview=vouchers)
    return _run(go)


@app.post("/send")
def send():
    _check_csrf()

    def go():
        cfg = load_config(require_ebay=False)
        start, end = service.month_range(*_period())
        r = service.send_to_sevdesk(cfg, start, end)
        msgs = [("ok", "%d Belege an sevDesk gesendet, %d waren schon da." % (len(r["sent"]), len(r["skipped"])))]
        msgs += [("danger", e) for e in r["errors"]]
        msgs += [("warn", n) for n in r["notes"]]
        return _page(msgs, accounts=r["accounts"])
    return _run(go)


@app.post("/sevdesk-check")
def sevdesk_check():
    _check_csrf()

    def go():
        cfg = load_config(require_ebay=False)
        r = service.sevdesk_status(cfg)
        if r.get("error"):
            return _page([("danger", r["error"])])
        return _page([("ok", "sevDesk verbunden (Buchhaltung %s)." % r["version"])], accounts=r["accounts"])
    return _run(go)


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    url = "http://127.0.0.1:%d/" % PORT
    if _port_in_use(PORT):
        webbrowser.open(url)
        sys.exit(0)
    print("eBay Buchhaltung läuft: %s\nDieses Fenster offen lassen. Zum Beenden: Fenster schließen." % url)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False)
