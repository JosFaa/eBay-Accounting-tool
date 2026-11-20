import unittest
from decimal import Decimal

from ebay_tool.ebay_auth import extract_code
from ebay_tool.normalize import parse_trading_orders, sale_row, split_transactions

ORDER = {
    "orderId": "12-34567-89012",
    "creationDate": "2026-10-05T10:00:00.000Z",
    "buyer": {"username": "buyer1"},
    "orderPaymentStatus": "PAID",
    "cancelStatus": {"cancelState": "NONE_REQUESTED"},
    "pricingSummary": {
        "priceSubtotal": {"value": "25.00", "currency": "EUR"},
        "deliveryCost": {"value": "4.99", "currency": "EUR"},
        "priceDiscount": {"value": "-2.00", "currency": "EUR"},
        "total": {"value": "27.99", "currency": "EUR"},
    },
    "totalMarketplaceFee": {"value": "3.10", "currency": "EUR"},
    "lineItems": [{"title": "Vintage Lampe", "quantity": 1}],
    "fulfillmentStartInstructions": [
        {"shippingStep": {"shipTo": {"contactAddress": {"countryCode": "AT"}}}}
    ],
}

TRANSACTIONS = [
    {
        "transactionId": "T1", "transactionType": "SALE", "bookingEntry": "CREDIT",
        "orderId": "12-34567-89012", "transactionDate": "2026-10-05T10:01:00.000Z",
        "amount": {"value": "24.89", "currency": "EUR"},
        "orderLineItems": [{"marketplaceFees": [
            {"feeType": "FINAL_VALUE_FEE", "amount": {"value": "2.75", "currency": "EUR"}},
            {"feeType": "FINAL_VALUE_FEE_FIXED_PER_ORDER", "amount": {"value": "0.35", "currency": "EUR"}},
        ]}],
    },
    {
        "transactionId": "T2", "transactionType": "SHIPPING_LABEL", "bookingEntry": "DEBIT",
        "transactionDate": "2026-10-06T08:00:00.000Z",
        "amount": {"value": "4.49", "currency": "EUR"}, "transactionMemo": "DHL Paket",
    },
    {
        "transactionId": "T3", "transactionType": "NON_SALE_CHARGE", "bookingEntry": "CREDIT",
        "feeType": "AD_FEE", "transactionDate": "2026-10-07T08:00:00.000Z",
        "amount": {"value": "1.00", "currency": "EUR"},
    },
    {
        "transactionId": "T4", "transactionType": "TRANSFER", "bookingEntry": "DEBIT",
        "transactionDate": "2026-10-08T08:00:00.000Z",
        "amount": {"value": "50.00", "currency": "EUR"},
    },
]

TRADING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<GetOrdersResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <OrderArray>
    <Order>
      <OrderID>99-11111-22222</OrderID>
      <OrderStatus>Completed</OrderStatus>
      <CreatedTime>2026-10-02T12:00:00.000Z</CreatedTime>
      <SellerUserID>privatverkaeufer</SellerUserID>
      <Subtotal currencyID="EUR">10.00</Subtotal>
      <Total currencyID="EUR">14.50</Total>
      <AmountPaid currencyID="EUR">14.50</AmountPaid>
      <ShippingServiceSelected><ShippingServiceCost currencyID="EUR">4.50</ShippingServiceCost></ShippingServiceSelected>
      <TransactionArray><Transaction>
        <QuantityPurchased>2</QuantityPurchased>
        <Item><Title>Porzellan Tassen</Title></Item>
      </Transaction></TransactionArray>
    </Order>
  </OrderArray>
  <HasMoreOrders>false</HasMoreOrders>
</GetOrdersResponse>"""


class TestNormalize(unittest.TestCase):
    def test_sale_row(self):
        r = sale_row(ORDER)
        self.assertEqual(r["buyer_country"], "AT")
        self.assertEqual(r["income"], Decimal("27.99"))
        self.assertEqual(r["ebay_fees"], Decimal("3.10"))
        self.assertEqual(r["items"], "1x Vintage Lampe")

    def test_split_transactions(self):
        fees, other = split_transactions(TRANSACTIONS)
        self.assertEqual(len(fees), 4)
        self.assertEqual(sum(f["amount"] for f in fees), Decimal("2.75") + Decimal("0.35") + Decimal("4.49") - Decimal("1.00"))
        self.assertEqual([o["type"] for o in other], ["TRANSFER"])

    def test_trading_orders(self):
        rows, more, errors = parse_trading_orders(TRADING_XML)
        self.assertFalse(more)
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["seller"], "privatverkaeufer")
        self.assertEqual(rows[0]["total"], Decimal("14.50"))
        self.assertEqual(rows[0]["shipping"], Decimal("4.50"))
        self.assertEqual(rows[0]["items"], "2x Porzellan Tassen")

    def test_trading_error(self):
        xml = ('<GetOrdersResponse xmlns="urn:ebay:apis:eBLBaseComponents"><Ack>Failure</Ack>'
               "<Errors><LongMessage>Invalid token</LongMessage></Errors></GetOrdersResponse>")
        _, _, errors = parse_trading_orders(xml)
        self.assertEqual(errors, ["Invalid token"])

    def test_extract_code(self):
        url = "https://auth2.ebay.com/oauth2/ThirdPartyAuthSucessFailure.html?isAuthSuccessful=true&code=v%5E1.1%23abc&expires_in=299"
        self.assertEqual(extract_code(url), "v^1.1#abc")


if __name__ == "__main__":
    unittest.main()
