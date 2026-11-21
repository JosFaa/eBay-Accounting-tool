# Setup

## 1. Install the tool
Copy this folder to the Mac where the tool will run (e.g. `~/eBay-Buchhaltung`), then in Terminal inside the folder:

```bash
./setup.sh
```

This creates `config.json`. It holds secrets: never share or upload it (same for `tokens.json`, `signing_key.json` and the `data/` folder).

Also fill in `owner_name` (the name printed on the Eigenbelege).

## 2. eBay API keys
1. Go to <https://developer.ebay.com> and create a developer account (free). It doesn't have to belong to the seller: access to the seller's data is only granted when the seller signs in later.
2. **Application Keys** → create a **Production** keyset (not Sandbox).
   eBay asks about *Marketplace Account Deletion* notifications: choose the opt-out/exemption, since the tool only reads one seller's own account and stores nothing on a server.
3. Copy **App ID (Client ID)** → `ebay.client_id` and **Cert ID (Client Secret)** → `ebay.client_secret`.
4. Next to the Production keyset: **User Tokens** → **Get a Token from eBay via Your Application** → **Add eBay Redirect URL**. Keep eBay's default accept/decline pages, make sure **OAuth** is selected, save, and copy the **RuName** → `ebay.ru_name`.

## 3. sevDesk
The tool assumes sevDesk is set to **Kleinunternehmer** (§19 UStG).

- **Without API access** (plans below Buchhaltung Pro): leave `sevdesk.api_token` as it is. The tool then creates PDF receipts that you upload by hand (see "Upload to sevDesk" below).
- **With Buchhaltung Pro:** Einstellungen → Erweiterungen → **API** → copy the token into `sevdesk.api_token`.
  The page then switches to direct sending (preview + "senden") automatically.

## 4. Start and connect
1. Double-click **eBay Buchhaltung.command**. (The first time, macOS may block it: right-click → Öffnen → Öffnen.) A Terminal window opens (leave it open) and the browser shows the page.
2. Click **Bei eBay anmelden**, sign in with the seller account and click **Zustimmen**. Copy the whole address of the eBay page that follows, paste it into the box, **Anmeldung speichern**. The login is valid for about 18 months.
3. Only with an API token: open **sevDesk-Verbindung prüfen** → check the accounts it picked, e.g.:
   - Einnahmen: *Erlöse als Kleinunternehmer* (SKR03 8195 / SKR04 4185)
   - Wareneinkauf: *Wareneingang* (SKR03 3200 / SKR04 5200)
   - eBay-Gebühren: *Verkaufsprovisionen* (SKR03 4760 / SKR04 6770)
   - Versandetiketten: *Porto* (SKR03 4910 / SKR04 6800)
   If one is wrong, put the right account number into `sevdesk.accounts` in `config.json`.

Tip: drag `eBay Buchhaltung.command` to the desktop as an alias.

## 5. First real run (careful test)
1. Pick **one finished month** with few sales, click **1. Daten von eBay holen**.
2. Compare the overview with **Seller Hub → Zahlungen → Berichte** for that month (sales, fees, shipping labels).
3. **2. Excel speichern** and look at the file.
4. **3. Belege für sevDesk erstellen** → a Finder window opens with the PDFs. Upload them as described below.
5. If everything matches: select all earlier months you need and do steps 1–4 again.

## 6. Older purchases (one-time)
eBay only returns purchases from the last 90 days. For older ones:
1. On the page open **Ältere Käufe importieren** → download the **Vorlage**.
2. Fill in one row per purchase from eBay → Mein eBay → Käufe (date, order number, seller, item, price, shipping). Save as CSV.
3. Upload it. Then create the receipts (button 3) as usual.

## Upload to sevDesk (by hand)
Button 3 creates the folder `Dokumente › eBay-Buchhaltung › Belege <von> bis <bis>` with four subfolders:

| Folder | One PDF per | In sevDesk book as |
|---|---|---|
| `1 Einkäufe` | purchase (Eigenbeleg) | **Ausgabe**, category *Wareneingang / Wareneinkauf* |
| `2 Verkäufe` | month (all sales together) | **Einnahme**, category *Erlöse (Kleinunternehmer)* |
| `3 eBay-Gebühren` | month (overview) | only for comparison, see below |
| `4 Erstattungen` | month (refunds to buyers) | **Einnahme** with a negative amount (reduces income) in the month of the refund |

- In sevDesk: **Belege → Beleg hochladen**, drag all PDFs of a folder in at once. sevDesk reads date and amount; check them and pick the category.
  sevDesk may suggest "Ausgabe" for everything, so switch the sales receipts to **Einnahme**.
- **eBay fees:** upload **eBay's official monthly fee invoice** instead (Seller Hub → Zahlungen → Berichte → Rechnungen).
  It shows 19% VAT; as Kleinunternehmer you book the **full amount** as an expense (category *Verkaufsprovisionen / Nebenkosten*), no VAT deduction.
  Compare its total with the tool's overview. If shipping labels are not on the eBay invoice, upload the tool's overview for those.
  Don't upload both for the same fees, otherwise they are counted twice.
- Sales and fees are only created for **finished months**; the current month comes next time.
- Export each month only once, otherwise you'd upload the same receipts again. The folder name shows which months it covers.
  Exporting the same period again replaces the PDFs in that folder, so outdated receipts don't stay behind.
- **Counted only when paid:** unpaid sales and cancelled or unpaid purchases get no receipt. The page lists skipped purchases so you can check them on eBay.
  A sale that was paid and later refunded stays in its month; the refund is booked separately in the month it happened.

## Monthly routine
At the start of each month: double-click → leave "Von/Bis" at last month →
**1. Daten von eBay holen** → **2. Excel speichern** → **3. Belege für sevDesk erstellen** → drag the PDFs into sevDesk,
plus eBay's fee invoice for that month.
Running it every month keeps purchases within eBay's 90 days.

## What the tool does not do
- **Refunds to buyers** are not sent to sevDesk automatically: upload the receipt from `4 Erstattungen` by hand. Fee credits eBay gives back on a refund appear in the fee overview.
- **Payouts**: eBay pays out sales minus fees in batches. Matching those bank transactions to the vouchers happens in sevDesk.
- **Not tax advice.** If revenue nears €25,000 per year the page warns; then ask the Finanzamt or a tax advisor.

## Command line

```bash
./.venv/bin/python fetch.py --month 2026-10 --excel --preview
```

```bash
./.venv/bin/python -m unittest discover -s tests -t .
```
