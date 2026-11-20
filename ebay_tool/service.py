"""High-level actions used by both the button page (app.py) and the CLI."""
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import DATA_DIR
from .csv_import import parse_purchases_csv
from .ebay_api import EbayClient
from .excel import build_workbook
from .sevdesk import SevdeskClient, check_connection, plan_vouchers, send_vouchers
from .store import BERLIN, Ledger, local_date
from .summary import ku_check, summarize


def month_range(from_month, to_month=None, today=None):
    """'2026-01', '2026-10' -> (date(2026,1,1), date(2026,10,31)), capped at today."""
    today = today or date.today()
    y1, m1 = (int(x) for x in from_month.split("-"))
    y2, m2 = (int(x) for x in (to_month or from_month).split("-"))
    start = date(y1, m1, 1)
    end = date(y2 + (m2 == 12), m2 % 12 + 1, 1) - timedelta(days=1)
    if end < start:
        raise ValueError("Der Endmonat liegt vor dem Startmonat.")
    if start > today:
        raise ValueError("Der Zeitraum liegt in der Zukunft.")
    return start, min(end, today)


def last_month(today=None):
    today = today or date.today()
    first = today.replace(day=1) - timedelta(days=1)
    return "%04d-%02d" % (first.year, first.month)


def export_dir(cfg):
    p = cfg.get("export_dir") or "~/Documents/eBay-Buchhaltung"
    return Path(p).expanduser()


def fetch_from_ebay(cfg, start, end):
    client = EbayClient(cfg["ebay"])
    dt_start = datetime(start.year, start.month, start.day, tzinfo=BERLIN)
    dt_end = min(datetime(end.year, end.month, end.day, tzinfo=BERLIN) + timedelta(days=1),
                 datetime.now(BERLIN))
    sales = client.fetch_sales(dt_start, dt_end)
    fees, other = client.fetch_transactions(dt_start, dt_end)
    purchases, warning = client.fetch_purchases(dt_start, dt_end)
    ledger = Ledger()
    new = {
        "sales": ledger.merge("sales", sales, "order_id"),
        "fees": ledger.merge("fees", fees, "key"),
        "purchases": ledger.merge("purchases", purchases, "order_id"),
        "other": ledger.merge("other", other, "transaction_id"),
    }
    ledger.save()
    return {"found": {"sales": len(sales), "fees": len(fees), "purchases": len(purchases), "other": len(other)},
            "new": new, "warnings": [warning] if warning else []}


def import_purchases_csv(text):
    rows = parse_purchases_csv(text)
    ledger = Ledger()
    new = ledger.merge("purchases", rows, "order_id")
    ledger.save()
    return {"rows": len(rows), "new": new}


def overview(cfg, start, end):
    ledger = Ledger()
    return {
        "summary": summarize(ledger, start, end),
        "ku": ku_check(ledger, end.year, cfg.get("previous_year_revenue")),
    }


def export_excel(cfg, start, end):
    name = "eBay_%s_bis_%s.xlsx" % (start.strftime("%Y-%m"), end.strftime("%Y-%m"))
    path = export_dir(cfg) / name
    return build_workbook(Ledger(), start, end, path, cfg.get("previous_year_revenue"))


def preview_sevdesk(start, end):
    return plan_vouchers(Ledger(), start, end)


def send_to_sevdesk(cfg, start, end):
    ledger = Ledger()
    vouchers, notes = plan_vouchers(ledger, start, end)
    todo = [v for v in vouchers if not v["already_sent"]]
    client = SevdeskClient(cfg.get("sevdesk", {}).get("api_token", ""))
    result = send_vouchers(client, ledger, todo, cfg.get("sevdesk", {}), cfg.get("owner_name", ""))
    result["notes"] = notes
    return result


def sevdesk_status(cfg):
    client = SevdeskClient(cfg.get("sevdesk", {}).get("api_token", ""))
    return check_connection(client, cfg.get("sevdesk", {}))


DATA_DIR.mkdir(exist_ok=True)


def _completed_months(start, end, today):
    """Yield (key, first, last) for months fully inside [start, end] and already over."""
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        first = date(y, m, 1)
        last = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        if first >= start and last <= end and last < today:
            yield "%04d-%02d" % (y, m), first, last
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def export_receipts(cfg, start, end, today=None):
    """Write all receipts as PDFs into one folder for manual upload to sevDesk."""
    from .receipts import fees_receipt, purchase_receipt, safe_name, sales_summary_receipt
    from .summary import is_cancelled, month_label

    today = today or date.today()
    ledger = Ledger()
    owner = cfg.get("owner_name", "")
    folder = export_dir(cfg) / ("Belege %s bis %s" % (start.strftime("%Y-%m"), end.strftime("%Y-%m")))
    counts = {"purchases": 0, "sales": 0, "fees": 0}
    for p in ledger.rows("purchases", start, end):
        d = local_date(p["date"])
        name = "%s Einkauf %s.pdf" % (d.isoformat(), safe_name(p["order_id"]))
        purchase_receipt(p, folder / "1 Einkäufe" / name, owner)
        counts["purchases"] += 1
    notes = []
    months = list(_completed_months(start, end, today))
    for key, first, last in months:
        sales = [s for s in ledger.rows("sales", first, last) if not is_cancelled(s)]
        if sales:
            sales_summary_receipt(month_label(key), sales,
                                  folder / "2 Verkäufe" / ("%s Verkäufe %s.pdf" % (key, month_label(key))), owner)
            counts["sales"] += 1
        fees = ledger.rows("fees", first, last)
        if fees:
            fees_receipt(month_label(key), fees,
                         folder / "3 eBay-Gebühren" / ("%s Gebühren-Übersicht %s.pdf" % (key, month_label(key))), owner)
            counts["fees"] += 1
    done = {k for k, _, _ in months}
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        if "%04d-%02d" % (y, m) not in done:
            notes.append("%s ist noch nicht abgeschlossen: Verkäufe und Gebühren dafür erst nächsten Monat exportieren."
                         % month_label("%04d-%02d" % (y, m)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return {"folder": folder, "counts": counts, "notes": notes}


def open_in_finder(path):
    import subprocess
    if path.exists():
        subprocess.run(["open", str(path)], check=False)
