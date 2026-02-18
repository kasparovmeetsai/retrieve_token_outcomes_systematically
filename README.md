# Polymarket outcome claim script

This repository contains a Python script that redeems resolved Polymarket outcome tokens back into collateral (USDC) via the Conditional Tokens contract.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install web3
```

## Usage

Set your private key in an environment variable:

```bash
export POLYMARKET_PRIVATE_KEY=0xYOUR_PRIVATE_KEY
```

Dry run with one condition:

```bash
python claim_polymarket_outcomes.py \
  --condition-id 0x<32-byte-condition-id> \
  --dry-run
```

Send transactions for multiple conditions in a JSON file:

```json
[
  {"condition_id": "0xabc...", "index_sets": [1, 2]},
  {"condition_id": "0xdef..."}
]
```

```bash
python claim_polymarket_outcomes.py --conditions-file conditions.json
```

If `index_sets` is omitted, the script will auto-redeem all outcomes for that condition based on `getOutcomeSlotCount`.

## Notes

- Default network is Polygon (chain ID 137).
- Default collateral token is Polygon USDC.e (`0x2791...4174`).
- Only resolved conditions are redeemed (`payoutDenominator > 0`).
- Always run `--dry-run` first when testing a new condition list.
