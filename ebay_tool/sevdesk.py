"""sevDesk upload (bookkeeping system 2.0) for a Kleinunternehmer.

- Sale     -> income voucher (creditDebit D), tax rule 11 (§19 UStG), 0 %
- Purchase -> expense voucher (C), tax rule 10 (nicht vorsteuerabziehbar), 0 %
- eBay fees + shipping labels -> one expense voucher per finished month
Each voucher gets a fixed description (EBAY-V-/EBAY-K-/EBAY-G-...) which is
checked locally and in sevDesk before sending, so nothing is booked twice.
"""
from datetime import date, timedelta
from decimal import Decimal

import requests

from .config import DATA_DIR
from .receipts import fees_receipt, purchase_receipt, safe_name, sale_receipt
from .store import local_date
from .summary import counts_as_income, counts_as_purchase, month_label, purchase_amount, refunds

BASE_URL = "https://my.sevdesk.de/api/v1"
TAX_RULE_KU_REVENUE = 11
TAX_RULE_KU_EXPENSE = 10
PREFIX = "EBAY-"
RECEIPT_DIR = DATA_DIR / "belege"

# default account choice by name (first match wins), overridable by number in config
ACCOUNT_HINTS = {
    "revenue": ["kleinunternehmer", "erlöse", "umsatzerlöse"],
    "purchases": ["wareneingang", "wareneinkauf"],
    "fees": ["verkaufsprovision", "provision", "nebenkosten des geldverkehrs"],
    "shipping": ["porto", "ausgangsfracht", "versand"],
}
ACCOUNT_LABELS = {
    "revenue": "Einnahmen (Verkäufe)", "purchases": "Wareneinkauf",
    "fees": "eBay-Gebühren", "shipping": "Versandetiketten",
}
AVOID_WORDS = ("innergem", "steuerfrei", "ausland", "eu-", "19 %", "7 %", "16 %", "5 %", "§13b", "13b", "drittland")


class SevdeskError(Exception):
    pass


class SevdeskClient:
    def __init__(self, token):
        if not token or token.startswith("PASTE_"):
            raise SevdeskError("sevDesk-API-Token fehlt in config.json (siehe SETUP.md).")
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": token,
            "Accept": "application/json",
            "User-Agent": "ebay-buchhaltung/1.0",
        })

    def _check(self, resp, what):
        if resp.status_code == 401:
            raise SevdeskError("sevDesk lehnt den API-Token ab. Token prüfen oder Tarif ohne API-Zugang.")
        if resp.status_code == 403:
            raise SevdeskError("sevDesk: Keine Berechtigung (%s). Evtl. enthält der Tarif keinen API-Zugang." % what)
        if resp.status_code not in (200, 201):
            raise SevdeskError("sevDesk-Fehler %s bei %s: %s" % (resp.status_code, what, resp.text[:600]))
        return resp.json().get("objects")

    def get(self, path, params=None):
        return self._check(self.s.get(BASE_URL + path, params=params, timeout=60), path)

    def post_json(self, path, body):
        return self._check(self.s.post(BASE_URL + path, json=body, timeout=60), path)

    def upload(self, path):
        with open(path, "rb") as f:
            resp = self.s.post(BASE_URL + "/Voucher/Factory/uploadTempFile",
                               files={"file": (path.name, f, "application/pdf")}, timeout=120)
        return self._check(resp, "Beleg-Upload")["filename"]

    def system_version(self):
        return str(self.get("/Tools/bookkeepingSystemVersion")["version"])

    def existing_descriptions(self):
        found, offset = {}, 0
        while True:
            objs = self.get("/Voucher", {"descriptionLike": PREFIX, "limit": 1000, "offset": offset}) or []
            for v in objs:
                if (v.get("description") or "").startswith(PREFIX):
                    found[v["description"]] = v.get("id")
            if len(objs) < 1000:
                return found
            offset += 1000


# ---------- account selection ----------

def _allows(guide, rule_id):
    for r in guide.get("allowedTaxRules", []):
        if int(r.get("id", -1)) == rule_id and ("ZERO" in r.get("taxRates", []) or not r.get("taxRates")):
            return True
    return False


def pick_account(guides, key, rule_id, wanted_number=None):
    usable = [g for g in guides if _allows(g, rule_id)]
    if wanted_number:
        for g in usable:
            if str(g.get("accountNumber")) == str(wanted_number):
                return g
        raise SevdeskError("Konto %s passt in sevDesk nicht zu %s (Kleinunternehmer)." % (wanted_number, ACCOUNT_LABELS[key]))
    for hint in ACCOUNT_HINTS[key]:
        matches = [g for g in usable if hint in (g.get("accountName") or "").lower()
                   and not any(w in (g.get("accountName") or "").lower() for w in AVOID_WORDS)]
        if matches:
            return sorted(matches, key=lambda g: len(g.get("accountName") or ""))[0]
    raise SevdeskError("Kein passendes sevDesk-Konto für %s gefunden. Bitte Kontonummer in config.json "
                       "unter sevdesk.accounts.%s eintragen." % (ACCOUNT_LABELS[key], key))


def resolve_accounts(client, sev_cfg):
    wanted = sev_cfg.get("accounts", {}) or {}
    revenue = client.get("/ReceiptGuidance/forRevenue") or []
    expense = client.get("/ReceiptGuidance/forExpense") or []
    return {
        "revenue": pick_account(revenue, "revenue", TAX_RULE_KU_REVENUE, wanted.get("revenue")),
        "purchases": pick_account(expense, "purchases", TAX_RULE_KU_EXPENSE, wanted.get("purchases")),
        "fees": pick_account(expense, "fees", TAX_RULE_KU_EXPENSE, wanted.get("fees")),
        "shipping": pick_account(expense, "shipping", TAX_RULE_KU_EXPENSE, wanted.get("shipping")),
    }


# ---------- planning ----------

def _month_end(y, m):
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


def plan_vouchers(ledger, start, end, today=None):
    """Return (vouchers, notes). Nothing is sent here."""
    today = today or date.today()
    vouchers, notes = [], []
    for s in ledger.rows("sales", start, end):
        if not counts_as_income(s) or s["income"] <= 0:
            continue
        vouchers.append({
            "kind": "sale", "desc": PREFIX + "V-" + s["order_id"], "date": local_date(s["date"]),
            "party": s.get("buyer") or "eBay-Käufer", "amount": s["income"],
            "text": s["items"], "row": s,
            "positions": [("revenue", s["income"], "Verkauf %s (%s)" % (s["order_id"], s.get("buyer_country", "")))],
        })
    for p in ledger.rows("purchases", start, end):
        if not counts_as_purchase(p):
            continue
        paid = purchase_amount(p)
        vouchers.append({
            "kind": "purchase", "desc": PREFIX + "K-" + p["order_id"], "date": local_date(p["date"]),
            "party": p.get("seller") or "eBay-Verkäufer", "amount": paid,
            "text": p["items"], "row": p,
            "positions": [("purchases", paid, "Wareneinkauf %s" % p["order_id"])],
        })
    # fees: one voucher per month, only for months that are over and fully in the period
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        first, last = date(y, m, 1), _month_end(y, m)
        key = "%04d-%02d" % (y, m)
        rows = ledger.rows("fees", first, last)
        if rows:
            if last >= today or first < start or last > end:
                notes.append("Gebühren %s werden erst gebucht, wenn der ganze Monat abgeschlossen und ausgewählt ist." % month_label(key))
            else:
                fee_sum = sum((r["amount"] for r in rows if r.get("kind") != "label"), Decimal("0"))
                label_sum = sum((r["amount"] for r in rows if r.get("kind") == "label"), Decimal("0"))
                positions = []
                if fee_sum > 0:
                    positions.append(("fees", fee_sum, "eBay-Gebühren %s" % month_label(key)))
                if label_sum > 0:
                    positions.append(("shipping", label_sum, "Versandetiketten %s" % month_label(key)))
                if positions:
                    vouchers.append({
                        "kind": "fees", "desc": PREFIX + "G-" + key, "date": last, "party": "eBay",
                        "amount": sum((a for _, a, _ in positions), Decimal("0")),
                        "text": "eBay-Gebühren und Versandetiketten %s" % month_label(key),
                        "rows": rows, "month": key, "positions": positions,
                    })
                if fee_sum < 0 or label_sum < 0:
                    notes.append("Gebühren %s: Gutschriften überwiegen, bitte manuell prüfen." % month_label(key))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    refs = refunds(ledger.rows("other", start, end))
    if refs:
        notes.append("%d Erstattung(en) an Käufer im Zeitraum: bitte in sevDesk manuell buchen (siehe Excel, Blatt Sonstiges)." % len(refs))
    vouchers.sort(key=lambda v: (v["date"], v["desc"]))
    for v in vouchers:
        v["already_sent"] = ledger.is_sent(v["desc"])
    return vouchers, notes


# ---------- sending ----------

def _make_receipt(v, owner_name):
    if v["kind"] == "sale":
        return sale_receipt(v["row"], RECEIPT_DIR / "verkaeufe" / (safe_name(v["desc"]) + ".pdf"), owner_name)
    if v["kind"] == "purchase":
        return purchase_receipt(v["row"], RECEIPT_DIR / "kaeufe" / (safe_name(v["desc"]) + ".pdf"), owner_name)
    return fees_receipt(month_label(v["month"]), v["rows"], RECEIPT_DIR / "gebuehren" / (safe_name(v["desc"]) + ".pdf"), owner_name)


def voucher_payload(v, accounts, status, filename=None):
    d = v["date"].strftime("%d.%m.%Y")
    is_sale = v["kind"] == "sale"
    return {
        "voucher": {
            "objectName": "Voucher",
            "mapAll": True,
            "voucherDate": d,
            "deliveryDate": d,
            "supplier": None,
            "supplierName": v["party"][:100],
            "description": v["desc"],
            "status": status,
            "taxRule": {"id": str(TAX_RULE_KU_REVENUE if is_sale else TAX_RULE_KU_EXPENSE), "objectName": "TaxRule"},
            "creditDebit": "D" if is_sale else "C",
            "voucherType": "VOU",
            "currency": "EUR",
        },
        "voucherPosSave": [
            {
                "objectName": "VoucherPos",
                "mapAll": True,
                "accountDatev": {"id": int(accounts[acc]["accountDatevId"]), "objectName": "AccountDatev"},
                "taxRate": 0,
                "net": False,
                "sumGross": float(amount),
                "sumNet": float(amount),
                "comment": comment[:250],
            }
            for acc, amount, comment in v["positions"]
        ],
        "voucherPosDelete": None,
        "filename": filename,
    }


def send_vouchers(client, ledger, vouchers, sev_cfg, owner_name="", progress=None):
    """Send planned vouchers. Saves the ledger after each one. Returns result dict."""
    if client.system_version() != "2.0":
        raise SevdeskError("Dieses Tool unterstützt nur sevDesk-Buchhaltung Version 2.0.")
    accounts = resolve_accounts(client, sev_cfg)
    remote = client.existing_descriptions()
    status = int(sev_cfg.get("voucher_status", 100))
    sent, skipped, errors = [], [], []
    for v in vouchers:
        if ledger.is_sent(v["desc"]):
            skipped.append(v["desc"])
            continue
        if v["desc"] in remote:
            ledger.mark_sent(v["desc"], remote[v["desc"]])
            ledger.save()
            skipped.append(v["desc"])
            continue
        try:
            pdf = _make_receipt(v, owner_name)
            filename = client.upload(pdf)
            result = client.post_json("/Voucher/Factory/saveVoucher", voucher_payload(v, accounts, status, filename))
            ledger.mark_sent(v["desc"], (result or {}).get("voucher", {}).get("id", "?"))
            ledger.save()
            sent.append(v["desc"])
            if progress:
                progress(v)
        except SevdeskError as e:
            errors.append("%s: %s" % (v["desc"], e))
            if len(errors) >= 3 and not sent:
                errors.append("Abgebrochen nach 3 Fehlern ohne Erfolg.")
                break
    return {"sent": sent, "skipped": skipped, "errors": errors,
            "accounts": {k: "%s %s" % (a.get("accountNumber"), a.get("accountName")) for k, a in accounts.items()}}


def check_connection(client, sev_cfg):
    version = client.system_version()
    out = {"version": version}
    if version != "2.0":
        out["error"] = "sevDesk-Buchhaltung Version %s: dieses Tool braucht Version 2.0." % version
        return out
    accounts = resolve_accounts(client, sev_cfg)
    out["accounts"] = {ACCOUNT_LABELS[k]: "%s %s" % (a.get("accountNumber"), a.get("accountName")) for k, a in accounts.items()}
    return out
