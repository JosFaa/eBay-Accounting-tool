"""Offline tests for ledger, CSV import, summary, Excel, PDFs and sevDesk planning/sending."""
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from ebay_tool import sevdesk
from ebay_tool.csv_import import ImportError_, parse_purchases_csv, template_csv
from ebay_tool.excel import build_workbook
from ebay_tool.normalize import sale_row, split_transactions
from ebay_tool.receipts import purchase_receipt
from ebay_tool.store import Ledger, local_date
from ebay_tool.summary import ku_check, summarize
from tests.test_normalize import ORDER, TRANSACTIONS

GUIDES_REVENUE = [
    {"accountDatevId": 1, "accountNumber": "8400", "accountName": "Erlöse 19 % USt",
     "allowedTaxRules": [{"id": 1, "taxRates": ["NINETEEN"]}]},
    {"accountDatevId": 2, "accountNumber": "8195", "accountName": "Erlöse als Kleinunternehmer i.S.d. § 19 Abs. 1 UStG",
     "allowedTaxRules": [{"id": 11, "taxRates": ["ZERO"]}]},
]
GUIDES_EXPENSE = [
    {"accountDatevId": 10, "accountNumber": "3400", "accountName": "Wareneingang 19 % Vorsteuer",
     "allowedTaxRules": [{"id": 9, "taxRates": ["NINETEEN"]}, {"id": 10, "taxRates": ["ZERO"]}]},
    {"accountDatevId": 11, "accountNumber": "3200", "accountName": "Wareneingang",
     "allowedTaxRules": [{"id": 10, "taxRates": ["ZERO"]}]},
    {"accountDatevId": 12, "accountNumber": "4760", "accountName": "Verkaufsprovisionen",
     "allowedTaxRules": [{"id": 10, "taxRates": ["ZERO"]}]},
    {"accountDatevId": 13, "accountNumber": "4910", "accountName": "Porto",
     "allowedTaxRules": [{"id": 10, "taxRates": ["ZERO"]}]},
]


class FakeSevdesk:
    def __init__(self, existing=None):
        self.saved, self.uploads = [], []
        self.existing = existing or {}

    def system_version(self):
        return "2.0"

    def get(self, path, params=None):
        return {"/ReceiptGuidance/forRevenue": GUIDES_REVENUE, "/ReceiptGuidance/forExpense": GUIDES_EXPENSE}[path]

    def existing_descriptions(self):
        return dict(self.existing)

    def upload(self, path):
        assert path.exists() and path.stat().st_size > 500
        self.uploads.append(path)
        return "hash%d.pdf" % len(self.uploads)

    def post_json(self, path, body):
        self.saved.append(body)
        return {"voucher": {"id": str(1000 + len(self.saved))}}


def make_ledger(tmp):
    led = Ledger(Path(tmp) / "ledger.json")
    led.merge("sales", [sale_row(ORDER)], "order_id")
    fees, other = split_transactions(TRANSACTIONS)
    led.merge("fees", fees, "key")
    led.merge("other", other, "transaction_id")
    led.merge("purchases", parse_purchases_csv(template_csv()), "order_id")
    led.save()
    return led


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        sevdesk.RECEIPT_DIR = Path(self.tmp) / "belege"

    def test_local_date_berlin(self):
        self.assertEqual(local_date("2026-10-31T23:30:00.000Z"), date(2026, 11, 1))
        self.assertEqual(local_date("2026-03-15"), date(2026, 3, 15))

    def test_ledger_roundtrip_and_merge(self):
        led = make_ledger(self.tmp)
        again = Ledger(Path(self.tmp) / "ledger.json")
        self.assertEqual(again.data["sales"]["12-34567-89012"]["income"], Decimal("27.99"))
        self.assertEqual(again.merge("sales", [sale_row(ORDER)], "order_id"), 0)
        self.assertEqual(len(led.rows("fees")), 4)

    def test_csv_import(self):
        rows = parse_purchases_csv("Datum;Artikel;Preis;Versand\n01.02.2026;Lampe;1.234,50;5\n\n")
        self.assertEqual(rows[0]["total"], Decimal("1239.50"))
        self.assertTrue(rows[0]["order_id"].startswith("CSV-"))
        self.assertEqual(rows, parse_purchases_csv("Datum;Artikel;Preis;Versand\n01.02.2026;Lampe;1.234,50;5\n"))
        with self.assertRaises(ImportError_):
            parse_purchases_csv("Datum;Artikel;Preis\n2026-02-01;Lampe;3\n")
        with self.assertRaises(ImportError_):
            parse_purchases_csv("Foo;Bar\n1;2\n")

    def test_summary(self):
        led = make_ledger(self.tmp)
        s = summarize(led, date(2026, 1, 1), date(2026, 10, 31))
        self.assertEqual(len(s["months"]), 10)
        oct_ = s["months"]["2026-10"]
        self.assertEqual(oct_["income"], Decimal("27.99"))
        self.assertEqual(oct_["fees"], Decimal("2.10"))  # 2.75 + 0.35 - 1.00 credit
        self.assertEqual(oct_["labels"], Decimal("4.49"))
        self.assertEqual(s["months"]["2026-03"]["purchases"], Decimal("14.50"))
        self.assertEqual(s["totals"]["profit"], Decimal("27.99") - Decimal("14.50") - Decimal("2.10") - Decimal("4.49"))
        self.assertEqual(s["countries"]["AT"]["count"], 1)
        self.assertEqual(ku_check(led, 2026)["messages"], [])
        self.assertEqual(ku_check(led, 2026, 30000)["messages"][0][0], "danger")

    def test_excel(self):
        led = make_ledger(self.tmp)
        path = build_workbook(led, date(2026, 1, 1), date(2026, 10, 31), Path(self.tmp) / "x.xlsx")
        wb = load_workbook(path)
        self.assertEqual(wb.sheetnames, ["Übersicht", "Verkäufe", "Käufe", "Gebühren", "Sonstiges"])
        self.assertEqual(wb["Verkäufe"]["E2"].value, "AT")
        self.assertEqual(wb["Käufe"].max_row, 2)

    def test_receipt_pdf_handles_unicode(self):
        p = parse_purchases_csv(template_csv())[0]
        p["items"] = "Tasse 😀 „Zwiebelmuster“ – Ø 8 cm"
        out = purchase_receipt(p, Path(self.tmp) / "r.pdf", "Max Muster")
        self.assertTrue(out.read_bytes().startswith(b"%PDF"))

    def test_plan_vouchers(self):
        led = make_ledger(self.tmp)
        vs, notes = sevdesk.plan_vouchers(led, date(2026, 1, 1), date(2026, 10, 31), today=date(2026, 11, 19))
        kinds = sorted(v["kind"] for v in vs)
        self.assertEqual(kinds, ["fees", "purchase", "sale"])
        fees = [v for v in vs if v["kind"] == "fees"][0]
        self.assertEqual(fees["desc"], "EBAY-G-2026-10")
        self.assertEqual(fees["amount"], Decimal("6.59"))
        # current month: fees are deferred
        vs2, notes2 = sevdesk.plan_vouchers(led, date(2026, 10, 1), date(2026, 10, 31), today=date(2026, 10, 20))
        self.assertNotIn("fees", [v["kind"] for v in vs2])
        self.assertTrue(any("abgeschlossen" in n for n in notes2))

    def test_pick_account(self):
        self.assertEqual(sevdesk.pick_account(GUIDES_REVENUE, "revenue", 11)["accountNumber"], "8195")
        self.assertEqual(sevdesk.pick_account(GUIDES_EXPENSE, "purchases", 10)["accountNumber"], "3200")
        self.assertEqual(sevdesk.pick_account(GUIDES_EXPENSE, "purchases", 10, "3400")["accountNumber"], "3400")
        with self.assertRaises(sevdesk.SevdeskError):
            sevdesk.pick_account(GUIDES_REVENUE, "revenue", 11, "8400")

    def test_send_and_dedupe(self):
        led = make_ledger(self.tmp)
        vs, _ = sevdesk.plan_vouchers(led, date(2026, 1, 1), date(2026, 10, 31), today=date(2026, 11, 19))
        fake = FakeSevdesk(existing={"EBAY-K-12-34567-89012": "77"})
        r = sevdesk.send_vouchers(fake, led, vs, {"voucher_status": 100})
        self.assertEqual(sorted(r["sent"]), ["EBAY-G-2026-10", "EBAY-V-12-34567-89012"])
        self.assertEqual(r["skipped"], ["EBAY-K-12-34567-89012"])
        self.assertEqual(r["errors"], [])
        sale = [b for b in fake.saved if b["voucher"]["creditDebit"] == "D"][0]
        self.assertEqual(sale["voucher"]["taxRule"]["id"], "11")
        self.assertEqual(sale["voucherPosSave"][0]["accountDatev"]["id"], 2)
        self.assertEqual(sale["voucherPosSave"][0]["sumGross"], 27.99)
        self.assertEqual(sale["voucher"]["voucherDate"], "05.10.2026")
        fee = [b for b in fake.saved if b["voucher"]["description"] == "EBAY-G-2026-10"][0]
        self.assertEqual([p["accountDatev"]["id"] for p in fee["voucherPosSave"]], [12, 13])
        self.assertEqual(fee["voucher"]["taxRule"]["id"], "10")
        # second run sends nothing
        fake2 = FakeSevdesk()
        r2 = sevdesk.send_vouchers(fake2, Ledger(Path(self.tmp) / "ledger.json"), vs, {})
        self.assertEqual(r2["sent"], [])
        self.assertEqual(fake2.saved, [])


if __name__ == "__main__":
    unittest.main()
