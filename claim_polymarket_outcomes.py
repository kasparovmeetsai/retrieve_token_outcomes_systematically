#!/usr/bin/env python3
"""Redeem resolved Polymarket outcome tokens back to collateral."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Sequence
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from web3 import Web3
from web3.contract import Contract

DEFAULT_RPC_URL = "https://polygon-rpc.com"
DEFAULT_GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"
DEFAULT_AUTO_ETH_5M_COUNT = 12
DEFAULT_AUTO_ETH_5M_PREFIX = "eth-updown-5m"
FALLBACK_RPC_URLS = [
    "https://rpc.ankr.com/polygon",
    "https://polygon.llamarpc.com",
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
    "https://polygon.drpc.org",
]

KNOWN_NETWORK_DEFAULTS: dict[int, dict[str, str]] = {
    137: {
        "name": "polygon-mainnet",
        "ctf": "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",
        "collateral": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    }
}

CTF_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "collateralToken", "type": "address"},
            {"internalType": "bytes32", "name": "parentCollectionId", "type": "bytes32"},
            {"internalType": "bytes32", "name": "conditionId", "type": "bytes32"},
            {"internalType": "uint256[]", "name": "indexSets", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "conditionId", "type": "bytes32"}],
        "name": "getOutcomeSlotCount",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "conditionId", "type": "bytes32"}],
        "name": "payoutDenominator",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


@dataclass
class ConditionRedeemRequest:
    condition_id: bytes
    index_sets: list[int]


@dataclass
class ResolvedConfig:
    chain_id: int
    chain_name: str
    ctf_address: str
    collateral_token: str


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _ensure_0x_hex(raw: str, expected_bytes: int, label: str) -> str:
    raw = raw.strip()
    if not raw.startswith("0x"):
        raw = f"0x{raw}"
    try:
        as_bytes = Web3.to_bytes(hexstr=raw)
    except ValueError as exc:
        raise ValueError(f"Invalid {label}: {raw}") from exc
    if len(as_bytes) != expected_bytes:
        raise ValueError(f"{label} must be {expected_bytes} bytes, got {len(as_bytes)} bytes: {raw}")
    return Web3.to_hex(as_bytes)


def _split_csv_urls(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _default_condition_ids_from_env() -> list[str]:
    raw = os.getenv("POLYMARKET_CONDITION_IDS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def floor_to_5m(ts: float | None = None) -> int:
    if ts is None:
        ts = time.time()
    return int(ts // 300) * 300


def slug_for_ts(ts: int, slug_prefix: str) -> str:
    return f"{slug_prefix}-{ts}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-url", default=os.getenv("POLYGON_RPC_URL", DEFAULT_RPC_URL))
    parser.add_argument("--rpc-fallback-url", action="append", default=_split_csv_urls(os.getenv("POLYGON_RPC_FALLBACK_URLS")))
    parser.add_argument("--rpc-timeout-seconds", type=int, default=12)
    parser.add_argument("--rpc-http-proxy", default=os.getenv("POLYGON_RPC_HTTP_PROXY"))
    parser.add_argument("--rpc-https-proxy", default=os.getenv("POLYGON_RPC_HTTPS_PROXY"))
    parser.add_argument("--rpc-no-proxy", action="store_true")

    parser.add_argument("--gamma-api-url", default=os.getenv("POLYMARKET_GAMMA_API_URL", DEFAULT_GAMMA_API_URL))
    parser.add_argument("--gamma-ca-bundle", default=os.getenv("POLYMARKET_GAMMA_CA_BUNDLE"), help="Path to CA bundle PEM for Gamma HTTPS verification")
    parser.add_argument(
        "--gamma-insecure-skip-verify",
        action="store_true",
        default=_env_bool("POLYMARKET_GAMMA_INSECURE"),
        help="Skip TLS verification for Gamma API (last resort only)",
    )
    parser.add_argument("--auto-eth-5m-count", type=int, default=int(os.getenv("POLYMARKET_AUTO_ETH_5M_COUNT", DEFAULT_AUTO_ETH_5M_COUNT)))
    parser.add_argument("--auto-eth-5m-prefix", default=os.getenv("POLYMARKET_AUTO_ETH_5M_PREFIX", DEFAULT_AUTO_ETH_5M_PREFIX))
    parser.add_argument("--disable-auto-gamma", action="store_true")

    parser.add_argument("--private-key", default=os.getenv("POLYMARKET_PRIVATE_KEY"))
    parser.add_argument("--ctf-address", default=os.getenv("POLYMARKET_CTF_ADDRESS"))
    parser.add_argument("--collateral-token", default=os.getenv("POLYMARKET_COLLATERAL_TOKEN"))
    parser.add_argument("--condition-id", action="append", default=_default_condition_ids_from_env())
    parser.add_argument("--conditions-file", default=os.getenv("POLYMARKET_CONDITIONS_FILE"))
    parser.add_argument("--gas-multiplier", type=float, default=1.20)
    parser.add_argument("--chain-id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _build_rpc_request_kwargs(args: argparse.Namespace) -> dict:
    request_kwargs: dict = {"timeout": args.rpc_timeout_seconds}
    if args.rpc_no_proxy:
        request_kwargs["proxies"] = {"http": "", "https": ""}
    elif args.rpc_http_proxy or args.rpc_https_proxy:
        request_kwargs["proxies"] = {"http": args.rpc_http_proxy or "", "https": args.rpc_https_proxy or args.rpc_http_proxy or ""}
    return request_kwargs


def _connect_web3(args: argparse.Namespace) -> tuple[Web3, str]:
    rpc_candidates = [args.rpc_url, *args.rpc_fallback_url, *FALLBACK_RPC_URLS]
    deduped_candidates: list[str] = []
    for url in rpc_candidates:
        if url and url not in deduped_candidates:
            deduped_candidates.append(url)
    request_kwargs = _build_rpc_request_kwargs(args)
    errors: list[str] = []
    for url in deduped_candidates:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs=request_kwargs))
            chain_id = w3.eth.chain_id
            if isinstance(chain_id, int) and chain_id > 0:
                return w3, url
            errors.append(f"{url} -> chain_id unavailable")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url} -> {exc}")
    raise ConnectionError("failed to connect to any RPC URL.\n  - " + "\n  - ".join(errors))


def resolve_config(args: argparse.Namespace, w3: Web3) -> ResolvedConfig:
    rpc_chain_id = w3.eth.chain_id
    chain_id = args.chain_id if args.chain_id is not None else rpc_chain_id
    if chain_id != rpc_chain_id:
        raise ValueError(f"--chain-id ({chain_id}) does not match RPC chain ({rpc_chain_id}).")

    network_defaults = KNOWN_NETWORK_DEFAULTS.get(chain_id)
    chain_name = network_defaults["name"] if network_defaults else f"chain-{chain_id}"
    ctf_raw = args.ctf_address or (network_defaults["ctf"] if network_defaults else None)
    collateral_raw = args.collateral_token or (network_defaults["collateral"] if network_defaults else None)
    if not ctf_raw or not collateral_raw:
        raise ValueError(f"No built-in defaults for chain {chain_id}. Provide --ctf-address and --collateral-token.")

    ctf_address = Web3.to_checksum_address(ctf_raw)
    collateral_token = Web3.to_checksum_address(collateral_raw)
    if len(w3.eth.get_code(ctf_address)) == 0:
        raise ValueError(f"No contract code found at CTF address {ctf_address} on chain {chain_id}")
    if len(w3.eth.get_code(collateral_token)) == 0:
        raise ValueError(f"No contract code found at collateral token address {collateral_token} on chain {chain_id}")

    return ResolvedConfig(chain_id=chain_id, chain_name=chain_name, ctf_address=ctf_address, collateral_token=collateral_token)


def _build_gamma_ssl_context(args: argparse.Namespace) -> ssl.SSLContext:
    if args.gamma_insecure_skip_verify:
        return ssl._create_unverified_context()
    if args.gamma_ca_bundle:
        return ssl.create_default_context(cafile=args.gamma_ca_bundle)
    return ssl.create_default_context()


def _extract_condition_ids(markets_json: object) -> list[str]:
    items = markets_json if isinstance(markets_json, list) else [markets_json]
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            candidate = item.get("conditionId") or item.get("condition_id")
            if isinstance(candidate, str) and candidate:
                out.append(candidate)
    return out


def _fetch_condition_ids_for_slug(args: argparse.Namespace, slug: str) -> list[str]:
    query = urlencode({"slug": slug})
    url = f"{args.gamma_api_url}?{query}"
    ssl_context = _build_gamma_ssl_context(args)

    try:
        with urlopen(url, timeout=args.rpc_timeout_seconds, context=ssl_context) as response:
            payload = response.read().decode("utf-8")
    except URLError as exc:
        extra = ""
        if isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
            extra = (
                " (TLS verify failed. Fix CA chain on your machine or use --gamma-ca-bundle / "
                "POLYMARKET_GAMMA_CA_BUNDLE. Last resort: --gamma-insecure-skip-verify)"
            )
        raise ValueError(f"Gamma API request failed for slug={slug}: {exc}{extra}") from exc

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gamma API returned invalid JSON for slug={slug}") from exc
    return _extract_condition_ids(parsed)


def _auto_fetch_eth_5m_condition_ids(args: argparse.Namespace) -> list[str]:
    if args.auto_eth_5m_count <= 0:
        return []
    now_rounded = floor_to_5m()
    found: list[str] = []
    for i in range(args.auto_eth_5m_count):
        slug = slug_for_ts(now_rounded - (i * 300), args.auto_eth_5m_prefix)
        try:
            found.extend(_fetch_condition_ids_for_slug(args, slug))
        except ValueError as exc:
            print(f"WARN: {exc}", file=sys.stderr)
            continue
    deduped: list[str] = []
    for c in found:
        if c not in deduped:
            deduped.append(c)
    return deduped


def load_condition_requests(args: argparse.Namespace, ctf: Contract) -> list[ConditionRedeemRequest]:
    requests: list[ConditionRedeemRequest] = []

    for condition_id in args.condition_id:
        condition_bytes = Web3.to_bytes(hexstr=_ensure_0x_hex(condition_id, 32, "condition_id"))
        requests.append(ConditionRedeemRequest(condition_id=condition_bytes, index_sets=_all_index_sets_for_condition(ctf, condition_bytes)))

    if args.conditions_file:
        with open(args.conditions_file, "r", encoding="utf-8") as f:
            raw_entries = json.load(f)
        if not isinstance(raw_entries, list):
            raise ValueError("conditions-file must be a JSON array")
        for entry in raw_entries:
            if not isinstance(entry, dict) or "condition_id" not in entry:
                raise ValueError("each condition entry must be an object with condition_id")
            condition_bytes = Web3.to_bytes(hexstr=_ensure_0x_hex(str(entry["condition_id"]), 32, "condition_id"))
            raw_index_sets = entry.get("index_sets")
            if raw_index_sets is None:
                index_sets = _all_index_sets_for_condition(ctf, condition_bytes)
            else:
                if not isinstance(raw_index_sets, list) or not all(isinstance(x, int) and x > 0 for x in raw_index_sets):
                    raise ValueError("index_sets must be a list of positive integers")
                index_sets = raw_index_sets
            requests.append(ConditionRedeemRequest(condition_id=condition_bytes, index_sets=index_sets))

    if not requests and not args.disable_auto_gamma:
        for condition_id in _auto_fetch_eth_5m_condition_ids(args):
            condition_bytes = Web3.to_bytes(hexstr=_ensure_0x_hex(condition_id, 32, "condition_id"))
            requests.append(ConditionRedeemRequest(condition_id=condition_bytes, index_sets=_all_index_sets_for_condition(ctf, condition_bytes)))

    if not requests:
        raise ValueError("No conditions provided or discovered.")

    return _dedupe_requests(requests)


def _all_index_sets_for_condition(ctf: Contract, condition_id: bytes) -> list[int]:
    slot_count = ctf.functions.getOutcomeSlotCount(condition_id).call()
    if slot_count <= 0:
        raise ValueError(f"Condition {Web3.to_hex(condition_id)} has zero outcome slots. Verify the condition ID.")
    return [1 << i for i in range(slot_count)]


def _dedupe_requests(requests: Sequence[ConditionRedeemRequest]) -> list[ConditionRedeemRequest]:
    merged: dict[bytes, set[int]] = {}
    for req in requests:
        merged.setdefault(req.condition_id, set()).update(req.index_sets)
    return [ConditionRedeemRequest(condition_id=k, index_sets=sorted(v)) for k, v in merged.items()]


def _format_index_sets(index_sets: Iterable[int]) -> str:
    return "[" + ", ".join(str(i) for i in index_sets) + "]"


def main() -> int:
    args = parse_args()
    if not args.private_key:
        print("ERROR: private key is required via --private-key or POLYMARKET_PRIVATE_KEY", file=sys.stderr)
        return 1

    try:
        w3, selected_rpc_url = _connect_web3(args)
        config = resolve_config(args, w3)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    ctf = w3.eth.contract(address=config.ctf_address, abi=CTF_ABI)
    owner = w3.eth.account.from_key(args.private_key).address

    try:
        requests = load_condition_requests(args, ctf)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Owner:          {owner}")
    print(f"RPC:            {selected_rpc_url}")
    print(f"Chain:          {config.chain_id} ({config.chain_name})")
    print(f"CTF:            {config.ctf_address}")
    print(f"Collateral:     {config.collateral_token}")
    print(f"Conditions:     {len(requests)}")
    if args.dry_run:
        print("Mode:           DRY RUN (no tx sent)")

    nonce = w3.eth.get_transaction_count(owner)
    sent = 0
    skipped = 0
    for idx, req in enumerate(requests, start=1):
        condition_hex = Web3.to_hex(req.condition_id)
        payout_denominator = ctf.functions.payoutDenominator(req.condition_id).call()
        if payout_denominator == 0:
            print(f"[{idx}/{len(requests)}] SKIP unresolved condition {condition_hex}")
            skipped += 1
            continue

        fn = ctf.functions.redeemPositions(config.collateral_token, b"\x00" * 32, req.condition_id, req.index_sets)
        try:
            gas_limit = int(fn.estimate_gas({"from": owner}) * args.gas_multiplier)
        except Exception as exc:  # noqa: BLE001
            print(f"[{idx}/{len(requests)}] ERROR estimating gas for {condition_hex}: {exc}")
            continue

        print(f"[{idx}/{len(requests)}] Redeem {condition_hex} index_sets={_format_index_sets(req.index_sets)} payout_denom={payout_denominator} gas~{gas_limit}")
        if args.dry_run:
            continue

        tx = fn.build_transaction(
            {
                "from": owner,
                "nonce": nonce,
                "chainId": config.chain_id,
                "gas": gas_limit,
                "maxFeePerGas": w3.eth.max_priority_fee + w3.eth.gas_price,
                "maxPriorityFeePerGas": w3.eth.max_priority_fee,
            }
        )
        signed = w3.eth.account.sign_transaction(tx, private_key=args.private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        print(f"    -> sent tx: {tx_hash.hex()}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        print(f"    -> mined status={receipt.status} block={receipt.blockNumber}")
        nonce += 1
        sent += 1

    print(f"Done. sent={sent}, skipped={skipped}, total={len(requests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
