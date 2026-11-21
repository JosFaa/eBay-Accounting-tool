"""Import purchases from a CSV file (for purchases older than eBay's 90 days).

Columns (first row = header, ; or , separated, German or dot decimals):
  Datum;Bestellnummer;Verkäufer;Artikel;Preis;Versand;Gesamt
Datum as TT.MM.JJJJ. Gesamt may be empty (then Preis + Versand).
"""
import csv
import hashlib
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

COLUMNS = ["Datum", "Bestellnummer", "Verkäufer", "Artikel", "Preis", "Versand", "Gesamt"]


class ImportError_(Exception):
    pass


def template_csv():
    return ";".join(COLUMNS) + "\n" + "15.03.2026;12-34567-89012;verkaeufer123;2x Porzellan Tassen;10,00;4,50;14,50\n"


def _amount(s, line, col):
    s = (s or "").strip().replace("€", "").replace(" ", "")
    if not s:
        return Decimal("0")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ImportError_("Zeile %d: '%s' ist kein gültiger Betrag (%s)." % (line, s, col))


def parse_purchases_csv(text):
    text = text.lstrip("﻿")
    first = text.splitlines()[0] if text.strip() else ""
    delim = ";" if first.count(";") >= first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    missing = [c for c in ("Datum", "Artikel", "Preis") if c not in (reader.fieldnames or [])]
    if missing:
        raise ImportError_("Spalten fehlen: %s. Erwartet: %s" % (", ".join(missing), ";".join(COLUMNS)))
    rows = []
    seen = {}
    for i, r in enumerate(reader, start=2):
        if not any((v or "").strip() for v in r.values()):
            continue
        try:
            d = datetime.strptime(r["Datum"].strip(), "%d.%m.%Y").date()
        except ValueError:
            raise ImportError_("Zeile %d: Datum '%s' bitte als TT.MM.JJJJ." % (i, r["Datum"]))
        price = _amount(r.get("Preis"), i, "Preis")
        shipping = _amount(r.get("Versand"), i, "Versand")
        # an explicit 0 in "Gesamt" stays 0; only an empty cell means "Preis + Versand"
        if (r.get("Gesamt") or "").strip():
            total = _amount(r.get("Gesamt"), i, "Gesamt")
        else:
            total = price + shipping
        seller = (r.get("Verkäufer") or "").strip()
        order_id = (r.get("Bestellnummer") or "").strip()
        if not order_id:
            h = hashlib.sha1(("%s|%s|%s|%s" % (d, seller, r["Artikel"].strip(), total)).encode()).hexdigest()[:10]
            order_id = "CSV-" + h
            # identical rows in one file are separate purchases: number them (stable on re-import)
            seen[order_id] = seen.get(order_id, 0) + 1
            if seen[order_id] > 1:
                order_id += "-%d" % seen[order_id]
        rows.append({
            "order_id": order_id,
            "date": d.isoformat(),
            "seller": seller,
            "items": r["Artikel"].strip(),
            "price": price,
            "shipping": shipping,
            "total": total,
            "amount_paid": total,
            "currency": "EUR",
            "status": "Completed",
            "source": "CSV-Import",
        })
    return rows
