# Store Parser Profiles

The agent can use a store-specific parser profile when one POS layout needs
special handling.

## Folder

On Windows, place profiles here:

```text
C:\ProgramData\BillEduthuAgent\parser_profiles\
```

Profile filenames should match the store code, shop ID, or merchant name:

```text
SHOP001.json
SHOP001.txt
```

The agent checks the local data folder first, then the repo `parser_profiles`
folder.

## JSON Profile

Example for a restaurant bill with columns:

```text
Item | Price | Qty | Total
```

Use:

```json
{
  "name": "SHOP001 restaurant layout",
  "merchant_name": "Bhagini",
  "item_layout": "item_price_qty_total",
  "subtotal_labels": ["Sub-Total"],
  "grand_total_labels": ["Total"],
  "skip_item_line_contains": ["GST No", "RECEIPT"]
}
```

Supported `item_layout` values:

```text
item_price_qty_total
item_qty_price_total
```

## Text Sample

You can also put a sample bill as:

```text
SHOP001.txt
```

If the sample contains:

```text
Item Price Qty Total
```

the agent infers:

```json
{"item_layout": "item_price_qty_total"}
```

The JSON profile is better for production because it can include merchant name,
labels, and skip rules.
