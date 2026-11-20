"""Demo mode: runs the button page with made-up data (for screenshots and trying it out).

    ./.venv/bin/python demo.py

Uses a temporary data folder and fake keys, so it never touches real eBay,
sevDesk, config.json or data/. "Daten von eBay holen" does nothing in demo mode.
"""
import os
import random
import sys
import tempfile
import threading
import webbrowser
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

DEMO_DIR = Path(tempfile.mkdtemp(prefix="ebay-demo-"))
os.environ["EBAY_TOOL_DATA_DIR"] = str(DEMO_DIR / "data")  # must be set before importing the tool

import app  # noqa: E402
from ebay_tool import service  # noqa: E402
from ebay_tool.store import Ledger  # noqa: E402

DEMO_CFG = {
    "owner_name": "Max Mustermann",
    "export_dir": str(DEMO_DIR / "export"),
    "previous_year_revenue": "14250.00",
    "ebay": {"client_id": "DEMO", "client_secret": "DEMO", "ru_name": "DEMO",
             "marketplace_id": "EBAY_DE", "site_id": "77"},
    "sevdesk": {"api_token": "", "voucher_status": 100, "accounts": {}},
}
ITEMS = ["Vintage Kamera Objektiv 50mm", "LEGO Technic Set 42083", "Nintendo Game Boy Color",
         "Bosch Akkuschrauber 18V", "Märklin H0 Lokomotive", "Vinyl LP Sammlung (12 Stück)",
         "Schallplattenspieler Dual CS 505", "Funkuhr Junghans Mega", "Playmobil Ritterburg"]
COUNTRIES = ["DE"] * 6 + ["AT", "FR", "NL", "IT", "ES", "BE"]


def money(x):
    return Decimal(x).quantize(Decimal("0.01"))


def make_demo_data(year=2026, months=10, seed=7):
    rnd = random.Random(seed)
    sales, purchases, fees = [], [], []
    for m in range(1, months + 1):
        for i in range(rnd.randint(14, 24)):
            d = date(year, m, rnd.randint(1, 28))
            price = money(rnd.uniform(8, 140))
            ship = money(rnd.choice([0, 4.99, 5.49, 6.99]))
            oid = "%02d-%05d-%05d" % (m, rnd.randint(10000, 99999), i)
            fee = money(price * Decimal("0.11") + Decimal("0.35"))
            sales.append({
                "order_id": oid, "date": d.isoformat(), "items": "1x " + rnd.choice(ITEMS),
                "buyer": "kaeufer_%03d" % rnd.randint(1, 400), "buyer_country": rnd.choice(COUNTRIES),
                "price": price, "shipping": ship, "discount": money(0), "income": price + ship,
                "ebay_fees": fee, "currency": "EUR", "payment_status": "PAID", "cancel_state": "NONE_REQUESTED",
            })
            fees.append({"transaction_id": "T" + oid, "key": "T%s:1" % oid, "date": d.isoformat(),
                         "order_id": oid, "currency": "EUR", "kind": "fee", "fee_type": "FINAL_VALUE_FEE",
                         "description": "Verkaufsprovision", "amount": fee})
            if rnd.random() < 0.6:
                fees.append({"transaction_id": "L" + oid, "key": "L" + oid,
                             "date": (d + timedelta(days=1)).isoformat(), "order_id": oid, "currency": "EUR",
                             "kind": "label", "fee_type": "SHIPPING_LABEL", "description": "Versandetikett DHL",
                             "amount": money(rnd.choice([4.19, 5.49, 6.19]))})
        for i in range(rnd.randint(14, 22)):
            d = date(year, m, rnd.randint(1, 28))
            price = money(rnd.uniform(3, 70))
            ship = money(rnd.choice([0, 3.99, 4.99]))
            purchases.append({
                "order_id": "P%02d-%05d-%03d" % (m, rnd.randint(10000, 99999), i), "date": d.isoformat(),
                "seller": "verkaeufer_%03d" % rnd.randint(1, 400), "items": "1x " + rnd.choice(ITEMS),
                "price": price, "shipping": ship, "total": price + ship, "amount_paid": price + ship,
                "currency": "EUR", "status": "Completed", "source": "Demo",
            })
    led = Ledger()
    led.merge("sales", sales, "order_id")
    led.merge("purchases", purchases, "order_id")
    led.merge("fees", fees, "key")
    led.save()


def _demo_fetch(cfg, start, end):
    return {"found": {"sales": 0, "purchases": 0, "fees": 0}, "new": {},
            "warnings": ["Demo-Modus: es wird nichts von eBay geholt."]}


def main():
    make_demo_data()
    app.load_config = lambda require_ebay=True: DEMO_CFG
    app.login_state = lambda: "ok"
    service.fetch_from_ebay = _demo_fetch
    port = app.PORT + 1
    url = "http://127.0.0.1:%d/?from_month=2026-01&to_month=2026-10" % port
    print("Demo läuft: %s\nDemo-Daten: %s" % (url, DEMO_DIR))
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
