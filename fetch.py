"""Command-line version (for the developer). The user uses the button page instead.

  python fetch.py --login                         one-time eBay sign-in
  python fetch.py --month 2026-10                 fetch one month into the ledger
  python fetch.py --from 2026-01 --to 2026-10     fetch several months
  python fetch.py --month 2026-10 --excel         also write the Excel file
  python fetch.py --import kaeufe.csv             import older purchases
  python fetch.py --month 2026-10 --preview       show what would go to sevDesk
"""
import argparse
import sys

from ebay_tool import service
from ebay_tool.config import ConfigError, load_config
from ebay_tool.csv_import import ImportError_
from ebay_tool.ebay_api import EbayError
from ebay_tool.ebay_auth import AuthError, interactive_login
from ebay_tool.sevdesk import SevdeskError


def euro(d):
    return ("%.2f €" % d).replace(".", ",")


def main():
    p = argparse.ArgumentParser(description="eBay-Buchhaltung")
    p.add_argument("--login", action="store_true")
    p.add_argument("--month", help="z.B. 2026-10")
    p.add_argument("--from", dest="from_month", help="Startmonat, z.B. 2026-01")
    p.add_argument("--to", dest="to_month", help="Endmonat, z.B. 2026-10")
    p.add_argument("--no-fetch", action="store_true", help="nur lokale Daten verwenden")
    p.add_argument("--excel", action="store_true")
    p.add_argument("--preview", action="store_true")
    p.add_argument("--import", dest="import_csv", help="CSV mit älteren Käufen")
    args = p.parse_args()

    try:
        if args.import_csv:
            with open(args.import_csv, encoding="utf-8-sig") as f:
                r = service.import_purchases_csv(f.read())
            print("%d Käufe importiert (%d neu)." % (r["rows"], r["new"]))
            return 0
        cfg = load_config(require_ebay=not args.no_fetch)
        if args.login:
            interactive_login(cfg["ebay"])
            return 0
        frm = args.month or args.from_month or service.last_month()
        start, end = service.month_range(frm, args.to_month if not args.month else args.month)
        print("Zeitraum %s – %s" % (start.strftime("%d.%m.%Y"), end.strftime("%d.%m.%Y")))
        if not args.no_fetch:
            r = service.fetch_from_ebay(cfg, start, end)
            print("Von eBay: %(sales)d Verkäufe, %(purchases)d Käufe, %(fees)d Gebühren, %(other)d Sonstiges" % r["found"])
            for w in r["warnings"]:
                print("HINWEIS: " + w)
        t = service.overview(cfg, start, end)["summary"]["totals"]
        print("Einnahmen %s | Wareneinkauf %s | Gebühren %s | Versand %s | Gewinn %s" % (
            euro(t["income"] - t["refunds"]), euro(t["purchases"]), euro(t["fees"]), euro(t["labels"]), euro(t["profit"])))
        if args.excel:
            print("Excel: %s" % service.export_excel(cfg, start, end))
        if args.preview:
            vouchers, notes = service.preview_sevdesk(start, end)
            for v in vouchers:
                print("%s %-10s %-9s %10s  %s%s" % (v["date"].strftime("%d.%m.%Y"), v["kind"], v["desc"][:24],
                                                  euro(v["amount"]), v["party"], "  (schon gesendet)" if v["already_sent"] else ""))
            for n in notes:
                print("HINWEIS: " + n)
    except (ConfigError, AuthError, EbayError, SevdeskError, ImportError_, ValueError, OSError) as e:
        print("FEHLER: %s" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
