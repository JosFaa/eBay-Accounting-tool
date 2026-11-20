"""Totals per month / country and the Kleinunternehmer limit check."""
from collections import OrderedDict
from datetime import date
from decimal import Decimal

from .store import local_date

KU_PREV_YEAR_LIMIT = Decimal("25000")
KU_CURRENT_YEAR_LIMIT = Decimal("100000")
WARN_SHARE = Decimal("0.8")
ZERO = Decimal("0")

MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
             "August", "September", "Oktober", "November", "Dezember"]


def is_cancelled(sale):
    return sale.get("cancel_state") == "CANCELED"


def refunds(other_rows):
    return [o for o in other_rows if o.get("type") == "REFUND"]


def _signed_refund(r):
    # DEBIT = money back to the buyer (reduces income)
    return r["amount"] if r.get("booking", "DEBIT") == "DEBIT" else -r["amount"]


def month_key(d):
    return "%04d-%02d" % (d.year, d.month)


def month_label(key):
    y, m = key.split("-")
    return "%s %s" % (MONTHS_DE[int(m) - 1], y)


def summarize(ledger, start, end):
    sales = [s for s in ledger.rows("sales", start, end) if not is_cancelled(s)]
    purchases = ledger.rows("purchases", start, end)
    fees = ledger.rows("fees", start, end)
    refs = refunds(ledger.rows("other", start, end))

    months = OrderedDict()
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        months["%04d-%02d" % (y, m)] = {
            "sales_count": 0, "income": ZERO, "refunds": ZERO,
            "purchases": ZERO, "fees": ZERO, "labels": ZERO,
        }
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    def bucket(row):
        return months[month_key(local_date(row["date"]))]

    countries = {}
    for s in sales:
        b = bucket(s)
        b["sales_count"] += 1
        b["income"] += s["income"]
        c = s.get("buyer_country") or "?"
        cc = countries.setdefault(c, {"count": 0, "income": ZERO})
        cc["count"] += 1
        cc["income"] += s["income"]
    for r in refs:
        bucket(r)["refunds"] += _signed_refund(r)
    for p in purchases:
        bucket(p)["purchases"] += p["total"]
    for f in fees:
        bucket(f)["labels" if f.get("kind") == "label" else "fees"] += f["amount"]

    for b in months.values():
        b["profit"] = b["income"] - b["refunds"] - b["purchases"] - b["fees"] - b["labels"]

    totals = {k: sum((b[k] for b in months.values()), ZERO if k != "sales_count" else 0)
              for k in ("sales_count", "income", "refunds", "purchases", "fees", "labels", "profit")}
    return {
        "months": months,
        "totals": totals,
        "countries": OrderedDict(sorted(countries.items(), key=lambda kv: -kv[1]["income"])),
        "counts": {"sales": len(sales), "purchases": len(purchases), "fees": len(fees), "refunds": len(refs)},
    }


def ku_check(ledger, year, previous_year_revenue=None):
    """Kleinunternehmer limits (since 2025): prev. year <= 25,000 €, current year <= 100,000 €."""
    s = summarize(ledger, date(year, 1, 1), date(year, 12, 31))
    revenue = s["totals"]["income"] - s["totals"]["refunds"]
    msgs = []
    if revenue > KU_CURRENT_YEAR_LIMIT:
        msgs.append(("danger", "Umsatz %d liegt über 100.000 €: Die Kleinunternehmerregelung endet sofort. Bitte Finanzamt/Steuerberater fragen." % year))
    elif revenue > KU_PREV_YEAR_LIMIT:
        msgs.append(("warn", "Umsatz %d liegt über 25.000 €: Ab 1.1.%d gilt die Kleinunternehmerregelung voraussichtlich nicht mehr (dann Umsatzsteuer)." % (year, year + 1)))
    elif revenue > KU_PREV_YEAR_LIMIT * WARN_SHARE:
        msgs.append(("warn", "Umsatz %d liegt bei über 80 %% der 25.000-€-Grenze." % year))
    if previous_year_revenue is not None and Decimal(str(previous_year_revenue)) > KU_PREV_YEAR_LIMIT:
        msgs.append(("danger", "Vorjahresumsatz laut Einstellungen über 25.000 €: Kleinunternehmerregelung gilt %d nicht." % year))
    return {"year": year, "revenue": revenue, "messages": msgs}
