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


PAID_STATES = {"PAID", "FULLY_REFUNDED", "PARTIALLY_REFUNDED"}


def is_cancelled(sale):
    return sale.get("cancel_state") == "CANCELED"


def counts_as_income(sale):
    """A sale is income once the buyer paid, even if it was later refunded or cancelled:
    the refund is booked separately on its own date, so both months stay correct.
    Unpaid orders (PENDING, FAILED) and cancellations before payment are not income."""
    status = sale.get("payment_status") or ""
    if status:
        return status in PAID_STATES
    return not is_cancelled(sale)  # rows without a status (old data): previous rule


def income_sales(rows):
    return [s for s in rows if counts_as_income(s)]


def purchase_amount(p):
    """What was actually paid. eBay rows carry amount_paid; CSV rows only a total."""
    if p.get("source") == "eBay-API":
        return p.get("amount_paid") or Decimal("0")
    return p.get("total") or Decimal("0")


def counts_as_purchase(p):
    return p.get("status") != "Cancelled" and purchase_amount(p) > 0


def paid_purchases(rows):
    return [p for p in rows if counts_as_purchase(p)]


def skipped_purchases(rows):
    return [p for p in rows if not counts_as_purchase(p)]


def refunds(other_rows):
    return [o for o in other_rows if o.get("type") == "REFUND"]


def refund_amount(r):
    """Money given back to the buyer (positive), credits to the seller negative.
    eBay's REFUND amount is what the seller was charged; the fee credit eBay gave back
    is added on top so the full refund reduces income and the credit reduces fees."""
    gross = r["amount"] + (r.get("fee_credit") or Decimal("0"))
    return gross if r.get("booking", "DEBIT") == "DEBIT" else -gross


def month_key(d):
    return "%04d-%02d" % (d.year, d.month)


def month_label(key):
    y, m = key.split("-")
    return "%s %s" % (MONTHS_DE[int(m) - 1], y)


def summarize(ledger, start, end):
    sales = income_sales(ledger.rows("sales", start, end))
    purchases = paid_purchases(ledger.rows("purchases", start, end))
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
        bucket(r)["refunds"] += refund_amount(r)
    for p in purchases:
        bucket(p)["purchases"] += purchase_amount(p)
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
