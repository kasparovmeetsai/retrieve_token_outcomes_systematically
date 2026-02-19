# Polymarket outcome claim script

Redeems resolved Polymarket outcomes back to collateral through Conditional Tokens.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install web3
```

## Fast path (auto discover last ETH 5m markets)

```bash
export POLYMARKET_PRIVATE_KEY=0xYOUR_PRIVATE_KEY
python claim_polymarket_outcomes.py --dry-run
```

If no conditions are passed, the script builds slugs like `eth-updown-5m-<timestamp>` for the latest 12 five-minute markets and looks up `conditionId` from Gamma API.

## Common SSL error and fix

If you see:

`SSL: CERTIFICATE_VERIFY_FAILED ... unable to get local issuer certificate`

it means your Python runtime does not trust the certificate chain in your current VPN/proxy environment.

### Preferred fix (secure): provide CA bundle

1. Obtain your CA bundle PEM (corporate/VPN cert chain or certifi bundle).
2. Run:

```bash
python claim_polymarket_outcomes.py \
  --gamma-ca-bundle /absolute/path/to/cacert.pem \
  --dry-run
```

or environment variable:

```bash
export POLYMARKET_GAMMA_CA_BUNDLE=/absolute/path/to/cacert.pem
python claim_polymarket_outcomes.py --dry-run
```

### Last resort (less secure): skip Gamma TLS verification

```bash
python claim_polymarket_outcomes.py --gamma-insecure-skip-verify --dry-run
```

or:

```bash
export POLYMARKET_GAMMA_INSECURE=1
python claim_polymarket_outcomes.py --dry-run
```

Use this only temporarily.

## PyCharm step-by-step (for the SSL case)

1. **Run > Edit Configurations...**
2. Select `claim_polymarket_outcomes.py`.
3. In **Script parameters**, add one of:
   - `--gamma-ca-bundle /absolute/path/to/cacert.pem --dry-run`
   - or `--gamma-insecure-skip-verify --dry-run` (temporary fallback)
4. In **Environment variables**, set at least:
   - `POLYMARKET_PRIVATE_KEY=0xYOUR_PRIVATE_KEY`
5. Apply and run.

## Manual condition input still supported

```bash
python claim_polymarket_outcomes.py --condition-id 0x... --dry-run
python claim_polymarket_outcomes.py --conditions-file conditions.json --dry-run
```

## Useful options

- `--disable-auto-gamma`
- `--auto-eth-5m-count 12`
- `--auto-eth-5m-prefix eth-updown-5m`
- `--gamma-api-url https://gamma-api.polymarket.com/markets`
- `--rpc-no-proxy`
- `--rpc-http-proxy ... --rpc-https-proxy ...`

## Notes

- Default chain preset is Polygon mainnet.
- Always test with `--dry-run` first.
