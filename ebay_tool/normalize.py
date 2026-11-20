"""Turn raw eBay API responses into flat rows for Excel/sevDesk.

Pure functions only (no network), so they can be tested with sample data.
Amounts are Decimal; expense amounts are positive when money went out.
"""
import xml.etree.ElementTree as ET
from decimal import Decimal

TRADING_NS = {"e": "urn:ebay:apis:eBLBaseComponents"}


def _money(obj):
    if not obj or obj.get("value") in (None, ""):
        return Decimal("0")
    return Decimal(str(obj["value"]))


def _currency(*objs):
    for o in objs:
        if o and o.get("currency"):
            return o["currency"]
    return "EUR"


# ---------- Sales (Sell Fulfillment API getOrders) ----------

def sale_row(order):
    ps = order.get("pricingSummary", {})
    subtotal = _money(ps.get("priceSubtotal"))
    shipping = _money(ps.get("deliveryCost"))
    discount = abs(_money(ps.get("priceDiscount"))) + abs(_money(ps.get("deliveryDiscount")))
    country = ""
    for fsi in order.get("fulfillmentStartInstructions", []):
        addr = fsi.get("shippingStep", {}).get("shipTo", {}).get("contactAddress", {})
        if addr.get("countryCode"):
            country = addr["countryCode"]
            break
    items = order.get("lineItems", [])
    return {
        "order_id": order.get("orderId", ""),
        "date": order.get("creationDate", ""),
        "items": "; ".join(
            "%sx %s" % (li.get("quantity", 1), li.get("title", "")) for li in items
        ),
        "buyer": order.get("buyer", {}).get("username", ""),
        "buyer_country": country,
        "price": subtotal,
        "shipping": shipping,
        "discount": discount,
        # what the buyer paid the seller (excl. any taxes eBay collects itself)
        "income": subtotal + shipping - discount,
        "ebay_fees": _money(order.get("totalMarketplaceFee")),
        "currency": _currency(ps.get("priceSubtotal"), ps.get("total")),
        "payment_status": order.get("orderPaymentStatus", ""),
        "cancel_state": order.get("cancelStatus", {}).get("cancelState", ""),
    }


# ---------- Fees, refunds, payouts (Sell Finances API getTransactions) ----------

def _signed_expense(tx):
    amount = _money(tx.get("amount"))
    return amount if tx.get("bookingEntry", "DEBIT") == "DEBIT" else -amount


def split_transactions(transactions):
    """Return (fee_rows, other_rows).

    fee_rows: eBay fees and shipping labels (expenses).
    other_rows: refunds, payouts, disputes etc. kept for checking.
    """
    fees, other = [], []
    for tx in transactions:
        ttype = tx.get("transactionType", "")
        base = {
            "transaction_id": tx.get("transactionId", ""),
            "date": tx.get("transactionDate", ""),
            "order_id": tx.get("orderId", ""),
            "currency": _currency(tx.get("amount")),
        }
        if ttype == "SALE":
            n = 0
            for li in tx.get("orderLineItems", []):
                for fee in li.get("marketplaceFees", []):
                    n += 1
                    fees.append(dict(
                        base,
                        key="%s:%d" % (base["transaction_id"], n),
                        kind="fee",
                        fee_type=fee.get("feeType", "FEE"),
                        description=fee.get("feeMemo", "") or "Verkaufsgebühr",
                        amount=_money(fee.get("amount")),
                    ))
        elif ttype in ("NON_SALE_CHARGE", "SHIPPING_LABEL"):
            fees.append(dict(
                base,
                key=base["transaction_id"],
                kind="label" if ttype == "SHIPPING_LABEL" else "fee",
                fee_type=tx.get("feeType") or ttype,
                description=tx.get("transactionMemo", "") or ttype,
                amount=_signed_expense(tx),
            ))
        else:
            other.append(dict(
                base,
                type=ttype,
                booking=tx.get("bookingEntry", ""),
                description=tx.get("transactionMemo", ""),
                amount=_money(tx.get("amount")),
            ))
    return fees, other


# ---------- Purchases (Trading API GetOrders, OrderRole=Buyer) ----------

def _text(el, path):
    found = el.find(path, TRADING_NS)
    return found.text if found is not None and found.text else ""


def _dec(el, path):
    t = _text(el, path)
    return Decimal(t) if t else Decimal("0")


def parse_trading_orders(xml_text):
    """Return (rows, has_more, errors) from a GetOrders XML response."""
    root = ET.fromstring(xml_text)
    errors = []
    if _text(root, "e:Ack") in ("Failure", "PartialFailure"):
        for err in root.findall("e:Errors", TRADING_NS):
            errors.append(_text(err, "e:LongMessage") or _text(err, "e:ShortMessage"))
    rows = []
    for order in root.findall("e:OrderArray/e:Order", TRADING_NS):
        titles = []
        for tr in order.findall("e:TransactionArray/e:Transaction", TRADING_NS):
            qty = _text(tr, "e:QuantityPurchased") or "1"
            titles.append("%sx %s" % (qty, _text(tr, "e:Item/e:Title")))
        total_el = order.find("e:Total", TRADING_NS)
        rows.append({
            "order_id": _text(order, "e:OrderID"),
            "date": _text(order, "e:CreatedTime"),
            "seller": _text(order, "e:SellerUserID"),
            "items": "; ".join(titles),
            "price": _dec(order, "e:Subtotal"),
            "shipping": _dec(order, "e:ShippingServiceSelected/e:ShippingServiceCost"),
            "total": _dec(order, "e:Total"),
            "amount_paid": _dec(order, "e:AmountPaid"),
            "currency": total_el.get("currencyID", "EUR") if total_el is not None else "EUR",
            "status": _text(order, "e:OrderStatus"),
            "source": "eBay-API",
        })
    has_more = _text(root, "e:HasMoreOrders").lower() == "true"
    return rows, has_more, errors
