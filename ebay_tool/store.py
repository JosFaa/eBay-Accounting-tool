"""Local ledger: everything fetched or imported is kept in data/ledger.json.

eBay only returns purchases for 90 days, so the ledger is the long-term
record. Rows are merged by ID, so fetching the same month twice is harmless.
"""
import json
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from .config import DATA_DIR

BERLIN = ZoneInfo("Europe/Berlin")
LEDGER_PATH = DATA_DIR / "ledger.json"
MONEY_FIELDS = {"price", "shipping", "discount", "income", "ebay_fees", "total", "amount_paid", "amount", "fee_credit"}
SECTIONS = ("sales", "purchases", "fees", "other")


def _to_json(o):
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(type(o))


def _restore(row):
    return {k: (Decimal(v) if k in MONEY_FIELDS and v not in (None, "") else v) for k, v in row.items()}


def local_date(value):
    """'2026-10-05T22:30:00.000Z' or '2026-10-05' -> date in German time."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    s = str(value)
    if len(s) == 10:
        return date.fromisoformat(s)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.astimezone(BERLIN).date()


class Ledger:
    def __init__(self, path=LEDGER_PATH):
        self.path = path
        self.data = {s: {} for s in SECTIONS}
        self.data["sent"] = {}
        if path.exists():
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            for s in SECTIONS:
                self.data[s] = {k: _restore(v) for k, v in raw.get(s, {}).items()}
            self.data["sent"] = raw.get("sent", {})

    def save(self):
        self.path.parent.mkdir(exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1, ensure_ascii=False, default=_to_json)
        tmp.replace(self.path)

    def merge(self, section, rows, key_field):
        """Insert or update rows. Returns number of new rows."""
        new = 0
        for r in rows:
            k = r[key_field]
            if k not in self.data[section]:
                new += 1
            self.data[section][k] = r
        return new

    def rows(self, section, start=None, end=None):
        """Rows whose local date is in [start, end] (dates, inclusive), sorted by date."""
        out = []
        for r in self.data[section].values():
            d = local_date(r["date"])
            if (start is None or d >= start) and (end is None or d <= end):
                out.append(r)
        return sorted(out, key=lambda r: local_date(r["date"]))

    # sevDesk bookkeeping: description -> sevDesk voucher id
    def is_sent(self, desc):
        return desc in self.data["sent"]

    def mark_sent(self, desc, voucher_id):
        self.data["sent"][desc] = str(voucher_id)
