"""Regression tests for the bookkeeping bugs found in review (refunds, unpaid orders, CSV, paging, files)."""
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from ebay_tool import service
from ebay_tool.csv_import import parse_purchases_csv
from ebay_tool.ebay_api import EbayClient, EbayError, _iso
from ebay_tool.normalize import split_transactions
from ebay_tool.receipts import purchase_receipt, unique_name
from ebay_tool.store import Ledger
from ebay_tool.summary import summarize

D = Decimal
HEAD = "Datum;Bestellnummer;Verkäufer;Artikel;Preis;Versand;Gesamt\n"


def sale(order_id, day, income, payment="PAID", cancel="NONE_REQUESTED"):
    return {"order_id": order_id, "date": day, "items": "1x Lampe", "buyer": "b", "buyer_country": "DE",
            "price": D(income), "shipping": D("0"), "discount": D("0"), "income": D(income),
            "ebay_fees": D("0"), "currency": "EUR", "payment_status": payment, "cancel_state": cancel}


def refund_tx(tx_id, day, amount, fee_credit=None):
    tx = {"transactionId": tx_id, "transactionType": "REFUND", "bookingEntry": "DEBIT", "orderId": "S1",
          "transactionDate": day, "amount": {"value": amount, "currency": "EUR"}}
    if fee_credit:
        tx["orderLineItems"] = [{"marketplaceFees": [
            {"feeType": "FINAL_VALUE_FEE", "amount": {"value": fee_credit, "currency": "EUR"}}]}]
    return tx


def api_purchase(order_id, total, paid, status="Completed"):
    return {"order_id": order_id, "date": "2026-10-10", "seller": "s", "items": "1x Tasse", "price": D(total),
            "shipping": D("0"), "total": D(total), "amount_paid": D(paid), "currency": "EUR",
            "status": status, "source": "eBay-API"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ledger = Ledger(self.tmp / "ledger.json")

    def add_refund(self, *txs):
        fees, other = split_transactions(list(txs))
        self.ledger.merge("fees", fees, "key")
        self.ledger.merge("other", other, "transaction_id")


class TestRefunds(Base):
    def test_refunded_then_cancelled_sale_nets_to_zero(self):
        # paid in October, fully refunded in November; October re-fetched as CANCELED
        self.ledger.merge("sales", [sale("S1", "2026-10-05", "100.00", "FULLY_REFUNDED", "CANCELED")], "order_id")
        self.add_refund(refund_tx("R1", "2026-11-03T10:00:00.000Z", "100.00"))
        s = summarize(self.ledger, date(2026, 10, 1), date(2026, 11, 30))
        self.assertEqual(s["months"]["2026-10"]["income"], D("100.00"))
        self.assertEqual(s["months"]["2026-11"]["refunds"], D("100.00"))
        self.assertEqual(s["totals"]["income"] - s["totals"]["refunds"], D("0"))

    def test_fee_credit_counted_once(self):
        # buyer gets 100, eBay gives back 10 fee: seller is charged 90
        self.ledger.merge("sales", [sale("S1", "2026-10-05", "100.00")], "order_id")
        self.ledger.merge("fees", [{"key": "F1", "transaction_id": "F1", "date": "2026-10-05", "order_id": "S1",
                                    "kind": "fee", "fee_type": "FINAL_VALUE_FEE", "amount": D("10.00")}], "key")
        self.add_refund(refund_tx("R1", "2026-10-20T10:00:00.000Z", "90.00", fee_credit="10.00"))
        s = summarize(self.ledger, date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(s["totals"]["refunds"], D("100.00"))
        self.assertEqual(s["totals"]["fees"], D("0.00"))
        self.assertEqual(s["totals"]["profit"], D("0.00"))  # 100 in, 90 charged back, 10 fee net 0

    def test_refund_only_month_gets_receipt_and_note(self):
        self.add_refund(refund_tx("R1", "2026-11-03T10:00:00.000Z", "100.00"))
        self.ledger.save()
        cfg = {"export_dir": str(self.tmp / "out")}
        with mock.patch.object(service, "Ledger", lambda: self.ledger):
            r = service.export_receipts(cfg, date(2026, 11, 1), date(2026, 11, 30), today=date(2026, 12, 5))
        self.assertEqual(r["counts"]["refunds"], 1)
        self.assertEqual(len(list((r["folder"] / "4 Erstattungen").glob("*.pdf"))), 1)
        self.assertTrue(any("Erstattung" in n for n in r["notes"]))

    def test_reexport_removes_outdated_receipts(self):
        self.ledger.merge("sales", [sale("S1", "2026-10-05", "100.00")], "order_id")
        cfg = {"export_dir": str(self.tmp / "out")}
        with mock.patch.object(service, "Ledger", lambda: self.ledger):
            first = service.export_receipts(cfg, date(2026, 10, 1), date(2026, 10, 31), today=date(2026, 12, 5))
            self.assertEqual(len(list((first["folder"] / "2 Verkäufe").glob("*.pdf"))), 1)
            # cancelled before payment ever arrived: no longer income
            self.ledger.merge("sales", [sale("S1", "2026-10-05", "100.00", "PENDING", "CANCELED")], "order_id")
            second = service.export_receipts(cfg, date(2026, 10, 1), date(2026, 10, 31), today=date(2026, 12, 5))
        self.assertEqual(second["counts"]["sales"], 0)
        self.assertEqual(list((second["folder"] / "2 Verkäufe").glob("*.pdf")), [])


class TestUnpaid(Base):
    def test_pending_sale_is_not_income(self):
        self.ledger.merge("sales", [sale("S1", "2026-10-05", "50.00", "PENDING")], "order_id")
        s = summarize(self.ledger, date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(s["totals"]["income"], D("0"))

    def test_unpaid_or_cancelled_purchase_is_not_expense(self):
        self.ledger.merge("purchases", [api_purchase("P1", "14.50", "0"),
                                        api_purchase("P2", "20.00", "20.00", status="Cancelled"),
                                        api_purchase("P3", "30.00", "28.00")], "order_id")
        s = summarize(self.ledger, date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(s["totals"]["purchases"], D("28.00"))  # only what was really paid

    def test_receipt_shows_amount_paid(self):
        from ebay_tool import receipts
        real_pdf = receipts._pdf
        seen = {}

        def capture(title, subtitle, fields, *args, **kwargs):
            seen.update(dict(fields))
            return real_pdf(title, subtitle, fields, *args, **kwargs)

        with mock.patch.object(receipts, "_pdf", capture):
            purchase_receipt(api_purchase("P3", "30.00", "28.00"), self.tmp / "p.pdf")
        self.assertEqual(seen["Gesamtbetrag bezahlt:"], "28,00 EUR")


class TestCsv(unittest.TestCase):
    def test_explicit_zero_total_stays_zero(self):
        rows = parse_purchases_csv(HEAD + "01.03.2026;X1;s;Tasse;15,00;0;0\n")
        self.assertEqual(rows[0]["total"], D("0"))

    def test_empty_total_is_price_plus_shipping(self):
        rows = parse_purchases_csv(HEAD + "01.03.2026;X1;s;Tasse;15,00;4,50;\n")
        self.assertEqual(rows[0]["total"], D("19.50"))

    def test_same_item_from_different_sellers_kept_apart(self):
        rows = parse_purchases_csv(HEAD + "01.03.2026;;anna;Tasse;10;0;10\n01.03.2026;;bert;Tasse;10;0;10\n")
        self.assertEqual(len({r["order_id"] for r in rows}), 2)

    def test_identical_rows_are_two_purchases_and_stable(self):
        text = HEAD + "01.03.2026;;anna;Tasse;10;0;10\n01.03.2026;;anna;Tasse;10;0;10\n"
        ids = [r["order_id"] for r in parse_purchases_csv(text)]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(ids, [r["order_id"] for r in parse_purchases_csv(text)])  # re-import: same IDs


class TestApi(unittest.TestCase):
    def test_iso_keeps_milliseconds(self):
        dt = datetime(2026, 10, 31, 22, 59, 59, 999000, tzinfo=timezone.utc)
        self.assertEqual(_iso(dt), "2026-10-31T22:59:59.999Z")

    def test_incomplete_page_raises(self):
        client = EbayClient({"marketplace_id": "EBAY_DE"})
        pages = [{"orders": [{"orderId": "1"}], "total": 2}, {"orders": [], "total": 2}]
        with mock.patch.object(client, "_get", side_effect=pages):
            with self.assertRaises(EbayError):
                client.fetch_sales(datetime(2026, 10, 1, tzinfo=timezone.utc),
                                   datetime(2026, 10, 20, tzinfo=timezone.utc))


class TestFiles(unittest.TestCase):
    def test_similar_ids_get_different_file_names(self):
        self.assertNotEqual(unique_name("A/B"), unique_name("A_B"))


if __name__ == "__main__":
    unittest.main()
