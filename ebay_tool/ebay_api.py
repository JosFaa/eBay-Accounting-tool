"""Calls to eBay: sales (Fulfillment), fees (Finances), purchases (Trading)."""
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

import requests

from .ebay_auth import get_access_token
from .signing import get_signing_key, signed_headers
from .normalize import parse_trading_orders, sale_row, split_transactions

FULFILLMENT_URL = "https://api.ebay.com/sell/fulfillment/v1/order"
FINANCES_URL = "https://apiz.ebay.com/sell/finances/v1/transaction"
TRADING_URL = "https://api.ebay.com/ws/api.dll"
TRADING_COMPAT = "1349"
PURCHASE_LOOKBACK_DAYS = 90  # Trading GetOrders can't go further back


class EbayError(Exception):
    pass


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _windows(start, end, days):
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=days), end)
        yield cur, nxt
        cur = nxt


class EbayClient:
    def __init__(self, ebay_cfg):
        self.cfg = ebay_cfg
        self.session = requests.Session()

    def _headers(self):
        return {
            "Authorization": "Bearer " + get_access_token(self.cfg),
            "X-EBAY-C-MARKETPLACE-ID": self.cfg["marketplace_id"],
            "Accept": "application/json",
        }

    def _get(self, url, params, signed=False):
        headers = self._headers()
        if signed:  # Finances API: digital signature required for EU sellers
            headers.update(signed_headers("GET", url, get_signing_key(self.cfg)))
        resp = self.session.get(url, headers=headers, params=params, timeout=60)
        if resp.status_code != 200:
            raise EbayError("eBay-Fehler %s bei %s: %s" % (resp.status_code, url, resp.text[:500]))
        return resp.json()

    # ---- sales ----
    def fetch_sales(self, start, end):
        rows = []
        for a, b in _windows(start, end, 30):
            offset = 0
            while True:
                body = self._get(FULFILLMENT_URL, {
                    "filter": "creationdate:[%s..%s]" % (_iso(a), _iso(b - timedelta(milliseconds=1))),
                    "limit": 200,
                    "offset": offset,
                })
                orders = body.get("orders", [])
                rows.extend(sale_row(o) for o in orders)
                offset += len(orders)
                if not orders or offset >= body.get("total", 0):
                    break
        return rows

    # ---- fees / refunds / payouts ----
    def fetch_transactions(self, start, end):
        raw = []
        for a, b in _windows(start, end, 30):
            offset = 0
            while True:
                body = self._get(FINANCES_URL, signed=True, params={
                    "filter": "transactionDate:[%s..%s]" % (_iso(a), _iso(b - timedelta(milliseconds=1))),
                    "limit": 1000,
                    "offset": offset,
                })
                txs = body.get("transactions", [])
                raw.extend(txs)
                offset += len(txs)
                if not txs or offset >= body.get("total", 0):
                    break
        return split_transactions(raw)

    # ---- purchases ----
    def _trading_get_orders(self, a, b, page):
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<GetOrdersRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            "<CreateTimeFrom>%s</CreateTimeFrom><CreateTimeTo>%s</CreateTimeTo>"
            "<OrderRole>Buyer</OrderRole><OrderStatus>All</OrderStatus>"
            "<Pagination><EntriesPerPage>100</EntriesPerPage><PageNumber>%d</PageNumber></Pagination>"
            "<DetailLevel>ReturnAll</DetailLevel>"
            "</GetOrdersRequest>"
        ) % (escape(_iso(a)), escape(_iso(b)), page)
        resp = self.session.post(TRADING_URL, data=xml.encode("utf-8"), timeout=60, headers={
            "X-EBAY-API-CALL-NAME": "GetOrders",
            "X-EBAY-API-SITEID": self.cfg["site_id"],
            "X-EBAY-API-COMPATIBILITY-LEVEL": TRADING_COMPAT,
            "X-EBAY-API-IAF-TOKEN": get_access_token(self.cfg),
            "Content-Type": "text/xml",
        })
        if resp.status_code != 200:
            raise EbayError("eBay-Fehler %s bei Käufen: %s" % (resp.status_code, resp.text[:500]))
        return parse_trading_orders(resp.text)

    def fetch_purchases(self, start, end):
        """Returns (rows, warning). Only the last 90 days are available."""
        warning = ""
        earliest = datetime.now(timezone.utc) - timedelta(days=PURCHASE_LOOKBACK_DAYS - 1)
        if start < earliest:
            warning = (
                "Käufe vor %s kann eBay nicht über die Schnittstelle liefern. "
                "Diese bitte per CSV-Import nachtragen." % earliest.strftime("%d.%m.%Y")
            )
            start = earliest
        rows = []
        if start >= end:
            return rows, warning
        for a, b in _windows(start, end, 30):
            page = 1
            while True:
                found, has_more, errors = self._trading_get_orders(a, b, page)
                if errors:
                    raise EbayError("eBay-Fehler bei Käufen: " + " | ".join(errors))
                rows.extend(found)
                if not has_more:
                    break
                page += 1
        return rows, warning
