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

## About defaults (important)

Built-in addresses are **convenience presets**, not permanent guarantees.

- The script auto-detects chain ID from your RPC.
- If the chain has a known preset (currently Polygon mainnet), that preset is used.
- If not, you **must** provide addresses via flags/env vars.
- The script validates that contract bytecode exists at both addresses before running.

Override addresses if needed:

```bash
export POLYMARKET_CTF_ADDRESS=0x...
export POLYMARKET_COLLATERAL_TOKEN=0x...
python claim_polymarket_outcomes.py --conditions-file conditions.json --dry-run
```

Or via CLI:

```bash
python claim_polymarket_outcomes.py \
  --ctf-address 0x... \
  --collateral-token 0x... \
  --condition-id 0x... \
  --dry-run
```

## RPC connectivity troubleshooting

If you get `ERROR: failed to connect to RPC URL`, your endpoint is down/blocked/slow from your network.

The script now tries multiple endpoints in order:

1. `--rpc-url` (or `POLYGON_RPC_URL`)
2. Any `--rpc-fallback-url` values
3. Any `POLYGON_RPC_FALLBACK_URLS` CSV values
4. Built-in public fallbacks

Example:

```bash
python claim_polymarket_outcomes.py \
  --rpc-url https://polygon-rpc.com \
  --rpc-fallback-url https://rpc.ankr.com/polygon \
  --rpc-fallback-url https://polygon.llamarpc.com \
  --condition-id 0x... \
  --dry-run
```

You can also tune timeout per endpoint:

```bash
python claim_polymarket_outcomes.py --rpc-timeout-seconds 20 --condition-id 0x... --dry-run
```

## Notes

- Only resolved conditions are redeemed (`payoutDenominator > 0`).
- Always run `--dry-run` first when testing a new condition list.
