"""Excel export: overview + one sheet per record type."""
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .store import local_date
from .summary import is_cancelled, ku_check, month_label, summarize

EUR = '#,##0.00 "€";[Red]-#,##0.00 "€"'
DATE = "DD.MM.YYYY"
HEAD_FILL = PatternFill("solid", fgColor="DDE7F0")
BOLD = Font(bold=True)

FEE_NAMES = {
    "FINAL_VALUE_FEE": "Verkaufsprovision",
    "FINAL_VALUE_FEE_FIXED_PER_ORDER": "Fixgebühr pro Bestellung",
    "AD_FEE": "Anzeigengebühr (Promoted Listings)",
    "SHIPPING_LABEL": "Versandetikett",
    "INSERTION_FEE": "Angebotsgebühr",
    "INTERNATIONAL_FEE": "Internationale Gebühr",
    "REGULATORY_OPERATING_FEE": "Regulatorische Gebühr",
}


def _sheet(wb, title, headers, rows, money_cols=(), date_cols=(), widths=None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = BOLD
        cell.fill = HEAD_FILL
    for r in rows:
        ws.append(r)
    for idx in money_cols:
        for row in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
            row[0].number_format = EUR
    for idx in date_cols:
        for row in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
            row[0].number_format = DATE
    for i, h in enumerate(headers, start=1):
        w = (widths or {}).get(i, max(12, len(h) + 2))
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def build_workbook(ledger, start, end, path, previous_year_revenue=None):
    s = summarize(ledger, start, end)
    wb = Workbook()
    ws = wb.active
    ws.title = "Übersicht"
    ws["A1"] = "eBay Einnahmen & Ausgaben (Kleinunternehmer, §19 UStG)"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Zeitraum: %s – %s" % (start.strftime("%d.%m.%Y"), end.strftime("%d.%m.%Y"))

    head = ["Monat", "Verkäufe", "Einnahmen", "Erstattungen", "Wareneinkauf", "eBay-Gebühren", "Versandetiketten", "Gewinn"]
    ws.append([])
    ws.append(head)
    hr = ws.max_row
    for c in range(1, len(head) + 1):
        ws.cell(row=hr, column=c).font = BOLD
        ws.cell(row=hr, column=c).fill = HEAD_FILL
    for key, b in s["months"].items():
        ws.append([month_label(key), b["sales_count"], b["income"], b["refunds"], b["purchases"], b["fees"], b["labels"], b["profit"]])
    t = s["totals"]
    ws.append(["Summe", t["sales_count"], t["income"], t["refunds"], t["purchases"], t["fees"], t["labels"], t["profit"]])
    for c in range(1, len(head) + 1):
        ws.cell(row=ws.max_row, column=c).font = BOLD
    for row in ws.iter_rows(min_row=hr + 1, max_row=ws.max_row, min_col=3, max_col=8):
        for cell in row:
            cell.number_format = EUR

    ws.append([])
    ws.append(["EÜR (vereinfacht)"])
    ws.cell(row=ws.max_row, column=1).font = BOLD
    eur_rows = [
        ("Betriebseinnahmen (Verkäufe − Erstattungen)", t["income"] - t["refunds"]),
        ("Wareneinkauf", t["purchases"]),
        ("eBay-Gebühren", t["fees"]),
        ("Versandkosten (Etiketten)", t["labels"]),
        ("Ergebnis (Gewinn)", t["profit"]),
    ]
    for label, val in eur_rows:
        ws.append([label, None, val])
        ws.cell(row=ws.max_row, column=3).number_format = EUR
    ws.cell(row=ws.max_row, column=1).font = BOLD

    ws.append([])
    ws.append(["Verkäufe nach Land", "Anzahl", "Einnahmen"])
    for c in range(1, 4):
        ws.cell(row=ws.max_row, column=c).font = BOLD
        ws.cell(row=ws.max_row, column=c).fill = HEAD_FILL
    for country, v in s["countries"].items():
        ws.append([country, v["count"], v["income"]])
        ws.cell(row=ws.max_row, column=3).number_format = EUR

    ku = ku_check(ledger, end.year, previous_year_revenue)
    ws.append([])
    ws.append(["Kleinunternehmer-Grenze %d" % ku["year"], None, ku["revenue"]])
    ws.cell(row=ws.max_row, column=1).font = BOLD
    ws.cell(row=ws.max_row, column=3).number_format = EUR
    ws.append(["Grenzen: Vorjahr max. 25.000 €, laufendes Jahr max. 100.000 €"])
    for _, msg in ku["messages"] or [("ok", "Umsatz unter den Grenzen.")]:
        ws.append([msg])

    ws.append([])
    ws.append(["Hinweis: Erstellt aus eBay-Daten. Bitte stichprobenartig mit Seller Hub > Zahlungen > Berichte vergleichen."])
    ws.column_dimensions["A"].width = 46
    for col in "BCDEFGH":
        ws.column_dimensions[col].width = 17

    sales = ledger.rows("sales", start, end)
    _sheet(wb, "Verkäufe",
           ["Datum", "Bestellnummer", "Artikel", "Käufer", "Land", "Preis", "Versand", "Rabatt", "Einnahme", "eBay-Gebühren", "Status"],
           [[local_date(x["date"]), x["order_id"], x["items"], x["buyer"], x["buyer_country"], x["price"], x["shipping"],
             x["discount"], x["income"], x["ebay_fees"], "storniert" if is_cancelled(x) else x.get("payment_status", "")]
            for x in sales],
           money_cols=(6, 7, 8, 9, 10), date_cols=(1,), widths={3: 45, 2: 18})

    purchases = ledger.rows("purchases", start, end)
    _sheet(wb, "Käufe",
           ["Datum", "Bestellnummer", "Artikel", "Verkäufer", "Preis", "Versand", "Gesamt", "Quelle"],
           [[local_date(x["date"]), x["order_id"], x["items"], x["seller"], x["price"], x["shipping"], x["total"], x.get("source", "")]
            for x in purchases],
           money_cols=(5, 6, 7), date_cols=(1,), widths={3: 45, 2: 18})

    fees = ledger.rows("fees", start, end)
    _sheet(wb, "Gebühren",
           ["Datum", "Bestellnummer", "Art", "Beschreibung", "Betrag", "Transaktion"],
           [[local_date(x["date"]), x.get("order_id", ""), FEE_NAMES.get(x["fee_type"], x["fee_type"]),
             x.get("description", ""), x["amount"], x["transaction_id"]] for x in fees],
           money_cols=(5,), date_cols=(1,), widths={3: 30, 4: 40, 2: 18})

    other = ledger.rows("other", start, end)
    _sheet(wb, "Sonstiges",
           ["Datum", "Typ", "Soll/Haben", "Bestellnummer", "Beschreibung", "Betrag", "Transaktion"],
           [[local_date(x["date"]), x["type"], x.get("booking", ""), x.get("order_id", ""), x.get("description", ""),
             x["amount"], x["transaction_id"]] for x in other],
           money_cols=(6,), date_cols=(1,), widths={5: 40})

    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                cell.alignment = Alignment(vertical="top")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
