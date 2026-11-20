# eBay → Excel → sevDesk tool: plan

Status: working on the user's Mac since 20 Nov 2026 (eBay login and signed Finances calls confirmed).

## Tax setup (what the tool assumes)
- Kleinunternehmer (§19 UStG): no VAT on sales; purchases and fees booked gross.
- Goal: clean records for the yearly EÜR.
- Limits since 2025: previous-year revenue ≤ €25,000 and current-year revenue ≤ €100,000.
  The tool warns at 80% of €25,000 (so he knows next year's status may change)
  and blocks nothing.

## Data sources (eBay)
| What | API | Notes |
|---|---|---|
| Sales (orders, buyer country, price, shipping) | Sell **Fulfillment API** `getOrders` | Filter by date |
| Fees, payouts, refunds, shipping labels | Sell **Finances API** `getTransactions`, `getPayouts` | Final value fees come as `NON_SALE_CHARGE`; labels as `SHIPPING_LABEL`. Developers report missing label costs in some cases → compare with Seller Hub report on first run |
| Purchases (as buyer) | **Trading API** `GetOrders` with `OrderRole=Buyer` | Buy-side APIs are limited; fallback = manual entry/import if this doesn't return what we need |

One eBay developer account + one app (free). OAuth login once in the browser; the tool stores and refreshes the token.

## Output
1. **Excel file** per run: `Sales`, `Purchases`, `Fees`, `Summary` (monthly totals, profit, sales per country, year-to-date EÜR, Kleinunternehmer limit check).
2. **Receipt PDF per purchase** (order details, or an Eigenbeleg if no invoice: date, seller, item, amount, purpose, "Wareneinkauf zum Weiterverkauf").
3. **sevDesk upload** (if the plan allows API access, see below):
   - Purchases → expense voucher, account *Wareneingang*, PDF attached
   - eBay fees → expense voucher(s), account for fees/commissions; labels → *Porto*
   - Sales → income voucher, Kleinunternehmer tax rule (§19, no VAT)
   - Each voucher carries the eBay order/transaction ID → re-runs skip existing ones
   - Preview + "Senden" confirmation before anything is written
   - Exact sevDesk account and tax-rule IDs get looked up via the API at setup, not hard-coded.

## How the user uses it
- Double-click `eBay Buchhaltung.command` on the desktop → a local page opens in the browser.
- Pick month (default: last month) → **Daten holen** → preview → **Excel speichern** / **An sevDesk senden**.
- Everything runs locally on his Mac; keys live in a local config file.

## Tech
- Python + small local web page (no install beyond a one-time setup script).
- Libraries: `requests`, `openpyxl`, a small web framework, a PDF library.
- Dry-run mode and a log file for errors.

## Status (19 Nov 2026)
All 5 steps are built and pass 14 offline tests. Not yet run against real eBay or sevDesk
(needs keys, see SETUP.md). Untested assumptions to confirm on the first real run:
- sevDesk accepts saveVoucher without the old `taxType`/`accountingType` fields, and tax rule 10 for KU expenses.
- Trading API GetOrders (OrderRole=Buyer) returns all purchases, incl. single-item orders.
- eBay API returns all fees/shipping labels (compare with Seller Hub).

## Build order
1. eBay connection + fetch sales/fees/purchases → print to screen (verify against Seller Hub).
   **Code done** (`fetch.py`, `ebay_tool/`), tested offline only; needs real eBay keys.
   Purchases via API only cover the last 90 days → Jan–Aug 2026 need a one-time CSV import.
2. Excel export + CSV import for older purchases.
3. Receipt/Eigenbeleg PDFs.
4. sevDesk upload with dry run and duplicate check.
5. Button page + double-click launcher + setup guide (German, simple).

## Things to check before/while building
- **sevDesk plan:** per sevDesk's help, the API needs at least **Buchhaltung Pro**.
  Token: Einstellungen → Erweiterungen → API. If he has a smaller plan: either upgrade
  or skip step 4 and upload the Excel/PDFs by hand (≈40 receipts/month, drag & drop).
- **eBay fee invoice VAT (§13b):** open one eBay fee invoice (Seller Hub → Zahlungen → Berichte).
  - Shows 19% USt → normal, nothing extra to do.
  - Shows 0% / "Steuerschuldnerschaft des Leistungsempfängers" (reverse charge) → he would owe
    that VAT himself and need to file it, even as Kleinunternehmer (§13b Abs. 8 UStG).
    This usually only happens if a USt-IdNr is stored at eBay. Clarify with the Finanzamt then.
- **Purchases from private sellers:** an eBay order confirmation normally serves as the receipt;
  the tool generates an Eigenbeleg where nothing else exists.

## Decisions
- Booking style: one receipt per purchase; sales as one Sammelbeleg per month (manual mode).
- First run starts 1 January 2026.
- The developer sets it up on the user's Mac.
- eBay fee invoice shows 19% USt → no reverse charge; fees booked gross.
- sevDesk: no Buchhaltung Pro → **manual mode**: button 3 creates PDF receipts in a folder,
  the user uploads them. The API path stays in the code and activates when a token is configured.
- sevDesk is set to Kleinunternehmer.

## Open questions
- Is the bank account that receives eBay payouts connected in sevDesk? (Payouts are net:
  sales minus fees; receipts get matched to those bank transactions.)
