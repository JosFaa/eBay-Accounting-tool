"""PDF receipts: Eigenbeleg for purchases, Verkaufsbeleg for sales.

An eBay purchase from a private seller has no invoice, so an Eigenbeleg
documents date, seller, item, amount and business purpose.
"""
import re
from datetime import date

from fpdf import FPDF

from .store import local_date


def _latin1(text):
    # core PDF fonts only cover Latin-1; replace anything else
    return str(text).replace("€", "EUR").replace("–", "-").replace("„", '"').replace("“", '"') \
        .encode("latin-1", "replace").decode("latin-1")


def _eur(d):
    s = "{:,.2f}".format(d)
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)[:60]


def _pdf(title, subtitle, fields, note, owner_name, signature=True):
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=20)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _latin1(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _latin1(subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    for label, value in fields:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(55, 7, _latin1(label))
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 7, _latin1(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, _latin1(note), new_x="LMARGIN", new_y="NEXT")
    if signature:
        pdf.ln(18)
        pdf.cell(80, 0, "", border="T")
        pdf.ln(2)
        pdf.cell(0, 5, _latin1("Datum, Unterschrift %s" % (owner_name or "")), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, _latin1("Automatisch erstellt am %s aus eBay-Bestelldaten." % date.today().strftime("%d.%m.%Y")))
    return pdf


def purchase_receipt(p, path, owner_name=""):
    d = local_date(p["date"])
    fields = [
        ("Kaufdatum:", d.strftime("%d.%m.%Y")),
        ("Verkäufer (eBay-Name):", p.get("seller") or "unbekannt"),
        ("eBay-Bestellnummer:", p["order_id"]),
        ("Artikel:", p["items"]),
        ("Artikelpreis:", _eur(p["price"])),
        ("Versand:", _eur(p["shipping"])),
        ("Gesamtbetrag bezahlt:", _eur(p["total"])),
        ("Zahlungsweg:", "Bezahlung über eBay"),
        ("Zweck:", "Wareneinkauf zum Weiterverkauf"),
    ]
    note = ("Eigenbeleg: Kauf über eBay, in der Regel von einer Privatperson. Eine Rechnung mit "
            "Umsatzsteuerausweis liegt nicht vor. Der Betrag wurde vollständig bezahlt. "
            "Kleinunternehmer nach §19 UStG: kein Vorsteuerabzug, Buchung brutto.")
    pdf = _pdf("Eigenbeleg - Wareneinkauf", "Beleg ohne Rechnung", fields, note, owner_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


def sale_receipt(s, path, owner_name=""):
    d = local_date(s["date"])
    fields = [
        ("Verkaufsdatum:", d.strftime("%d.%m.%Y")),
        ("Käufer (eBay-Name):", s.get("buyer") or "unbekannt"),
        ("Lieferland:", s.get("buyer_country") or "-"),
        ("eBay-Bestellnummer:", s["order_id"]),
        ("Artikel:", s["items"]),
        ("Artikelpreis:", _eur(s["price"])),
        ("Versand:", _eur(s["shipping"])),
        ("Rabatt:", _eur(s["discount"])),
        ("Einnahme:", _eur(s["income"])),
    ]
    note = "Gemäß §19 UStG wird keine Umsatzsteuer berechnet. Zahlung über eBay (Auszahlung gesammelt aufs Bankkonto)."
    pdf = _pdf("Verkaufsbeleg - eBay", "Beleg aus eBay-Bestelldaten", fields, note, owner_name, signature=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


def fees_receipt(month_label_text, rows, path, owner_name=""):
    total = sum(r["amount"] for r in rows)
    fields = [("Monat:", month_label_text), ("Anzahl Positionen:", str(len(rows))), ("Summe:", _eur(total))]
    lines = "\n".join("%s  %-28s %s  %s" % (local_date(r["date"]).strftime("%d.%m."), r.get("fee_type", "")[:28],
                                          _eur(r["amount"]), r.get("order_id", "")) for r in rows[:120])
    note = ("Zusammenstellung der eBay-Gebühren und Versandetiketten aus den eBay-Finanzdaten.\n"
            "Die offizielle eBay-Gebührenrechnung (Seller Hub > Zahlungen > Berichte) bitte zusätzlich aufbewahren.\n\n" + lines)
    pdf = _pdf("eBay-Gebühren " + month_label_text, "Monatsübersicht", fields, note, owner_name, signature=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


def sales_summary_receipt(month_label_text, rows, path, owner_name=""):
    """One collective receipt (Sammelbeleg) for all eBay sales of a month."""
    total = sum(r["income"] for r in rows)
    fields = [("Monat:", month_label_text), ("Anzahl Verkäufe:", str(len(rows))), ("Summe Einnahmen:", _eur(total))]
    lines = "\n".join("%s  %-16s %-3s %12s  %s" % (local_date(r["date"]).strftime("%d.%m."), r["order_id"],
                                                 r.get("buyer_country") or "-", _eur(r["income"]), r["items"][:45])
                      for r in rows)
    note = ("Sammelbeleg der eBay-Verkäufe (Artikel + Versand, abzüglich Rabatte, stornierte Verkäufe nicht enthalten).\n"
            "Gemäß §19 UStG wird keine Umsatzsteuer berechnet. Zahlungseingang über eBay-Auszahlungen.\n\n" + lines)
    pdf = _pdf("eBay-Verkäufe " + month_label_text, "Sammelbeleg Einnahmen", fields, note, owner_name, signature=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path
