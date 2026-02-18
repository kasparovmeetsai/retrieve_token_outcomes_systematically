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

If you get `ERROR: failed to connect to any RPC URL`, the machine running the script cannot reach Polygon RPC endpoints (endpoint down, network block, proxy issue, or timeout).

The script tries endpoints in order:

1. `--rpc-url` (or `POLYGON_RPC_URL`)
2. Any `--rpc-fallback-url` values
3. Any `POLYGON_RPC_FALLBACK_URLS` CSV values
4. Built-in public fallbacks

### Option A: Use your own RPC provider

Use a private provider URL (Alchemy, QuickNode, Chainstack, etc.):

```bash
python claim_polymarket_outcomes.py \
  --rpc-url "https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY" \
  --condition-id 0x... \
  --dry-run
```

### Option B: Force no proxy

If your machine has `HTTP_PROXY`/`HTTPS_PROXY` env vars and they are blocking requests:

```bash
python claim_polymarket_outcomes.py --rpc-no-proxy --condition-id 0x... --dry-run
```

### Option C: Set an explicit proxy for RPC

```bash
python claim_polymarket_outcomes.py \
  --rpc-http-proxy http://127.0.0.1:7890 \
  --rpc-https-proxy http://127.0.0.1:7890 \
  --condition-id 0x... \
  --dry-run
```

(Equivalent env vars: `POLYGON_RPC_HTTP_PROXY`, `POLYGON_RPC_HTTPS_PROXY`.)

### Option D: Add more fallbacks and increase timeout

```bash
python claim_polymarket_outcomes.py \
  --rpc-fallback-url https://polygon-bor-rpc.publicnode.com \
  --rpc-fallback-url https://polygon.drpc.org \
  --rpc-timeout-seconds 20 \
  --condition-id 0x... \
  --dry-run
```

## Notes

- Only resolved conditions are redeemed (`payoutDenominator > 0`).
- Always run `--dry-run` first when testing a new condition list.
