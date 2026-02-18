#!/usr/bin/env python3
"""Redeem resolved Polymarket outcome tokens back to collateral.

This script calls `redeemPositions` on the Conditional Tokens Framework (CTF)
contract used by Polymarket. It can process many conditions in one run,
allowing you to quickly claim collateral after markets resolve.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Iterable, Sequence

from web3 import Web3
from web3.contract import Contract

DEFAULT_RPC_URL = "https://polygon-rpc.com"

# These are known-good presets at the time this script was written.
# You can always override with flags/environment if Polymarket updates addresses.
KNOWN_NETWORK_DEFAULTS: dict[int, dict[str, str]] = {
    137: {
        "name": "polygon-mainnet",
        "ctf": "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",
        "collateral": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",  # USDC.e
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Redeem resolved Polymarket outcomes through ConditionalTokens.redeemPositions"
    )
    parser.add_argument(
        "--rpc-url",
        default=os.getenv("POLYGON_RPC_URL", DEFAULT_RPC_URL),
        help="Polygon RPC URL (default: %(default)s or POLYGON_RPC_URL env)",
    )
    parser.add_argument(
        "--private-key",
        default=os.getenv("POLYMARKET_PRIVATE_KEY"),
        help="Wallet private key (or set POLYMARKET_PRIVATE_KEY)",
    )
    parser.add_argument(
        "--ctf-address",
        default=os.getenv("POLYMARKET_CTF_ADDRESS"),
        help="Conditional Tokens contract address (or set POLYMARKET_CTF_ADDRESS)",
    )
    parser.add_argument(
        "--collateral-token",
        default=os.getenv("POLYMARKET_COLLATERAL_TOKEN"),
        help="Collateral token address (or set POLYMARKET_COLLATERAL_TOKEN)",
    )
    parser.add_argument(
        "--condition-id",
        action="append",
        default=[],
        help="Condition ID to redeem (bytes32 hex). Repeat for multiple.",
    )
    parser.add_argument(
        "--conditions-file",
        help=(
            "Optional JSON file with entries like "
            "[{\"condition_id\":\"0x..\",\"index_sets\":[1,2]}]. "
            "If index_sets is omitted, all outcomes are redeemed for that condition."
        ),
    )
    parser.add_argument(
        "--gas-multiplier",
        type=float,
        default=1.20,
        help="Multiplier applied to estimated gas (default: %(default)s)",
    )
    parser.add_argument(
        "--chain-id",
        type=int,
        help=(
            "Chain ID for signing. If omitted, uses connected RPC chain. "
            "If provided, it must match the RPC chain."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be redeemed without sending transactions.",
    )
    return parser.parse_args()


def resolve_config(args: argparse.Namespace, w3: Web3) -> ResolvedConfig:
    rpc_chain_id = w3.eth.chain_id
    chain_id = args.chain_id if args.chain_id is not None else rpc_chain_id
    if chain_id != rpc_chain_id:
        raise ValueError(
            f"--chain-id ({chain_id}) does not match RPC chain ({rpc_chain_id}). "
            "Use the correct RPC or remove --chain-id."
        )

    network_defaults = KNOWN_NETWORK_DEFAULTS.get(chain_id)
    chain_name = network_defaults["name"] if network_defaults else f"chain-{chain_id}"

    ctf_raw = args.ctf_address or (network_defaults["ctf"] if network_defaults else None)
    collateral_raw = args.collateral_token or (network_defaults["collateral"] if network_defaults else None)

    if not ctf_raw or not collateral_raw:
        raise ValueError(
            f"No built-in defaults for chain {chain_id}. Provide --ctf-address and --collateral-token "
            "(or POLYMARKET_CTF_ADDRESS / POLYMARKET_COLLATERAL_TOKEN)."
        )

    ctf_address = Web3.to_checksum_address(ctf_raw)
    collateral_token = Web3.to_checksum_address(collateral_raw)

    ctf_code = w3.eth.get_code(ctf_address)
    collateral_code = w3.eth.get_code(collateral_token)
    if len(ctf_code) == 0:
        raise ValueError(f"No contract code found at CTF address {ctf_address} on chain {chain_id}")
    if len(collateral_code) == 0:
        raise ValueError(f"No contract code found at collateral token address {collateral_token} on chain {chain_id}")

    return ResolvedConfig(
        chain_id=chain_id,
        chain_name=chain_name,
        ctf_address=ctf_address,
        collateral_token=collateral_token,
    )


def load_condition_requests(args: argparse.Namespace, ctf: Contract) -> list[ConditionRedeemRequest]:
    requests: list[ConditionRedeemRequest] = []

    for condition_id in args.condition_id:
        condition_hex = _ensure_0x_hex(condition_id, 32, "condition_id")
        condition_bytes = Web3.to_bytes(hexstr=condition_hex)
        requests.append(
            ConditionRedeemRequest(
                condition_id=condition_bytes,
                index_sets=_all_index_sets_for_condition(ctf, condition_bytes),
            )
        )

    if args.conditions_file:
        with open(args.conditions_file, "r", encoding="utf-8") as f:
            raw_entries = json.load(f)

        if not isinstance(raw_entries, list):
            raise ValueError("conditions-file must be a JSON array")

        for entry in raw_entries:
            if not isinstance(entry, dict) or "condition_id" not in entry:
                raise ValueError("each condition entry must be an object with condition_id")

            condition_hex = _ensure_0x_hex(str(entry["condition_id"]), 32, "condition_id")
            condition_bytes = Web3.to_bytes(hexstr=condition_hex)

            raw_index_sets = entry.get("index_sets")
            if raw_index_sets is None:
                index_sets = _all_index_sets_for_condition(ctf, condition_bytes)
            else:
                if not isinstance(raw_index_sets, list) or not all(
                    isinstance(x, int) and x > 0 for x in raw_index_sets
                ):
                    raise ValueError("index_sets must be a list of positive integers")
                index_sets = raw_index_sets

            requests.append(ConditionRedeemRequest(condition_id=condition_bytes, index_sets=index_sets))

    if not requests:
        raise ValueError("No conditions provided. Use --condition-id and/or --conditions-file")

    return _dedupe_requests(requests)


def _all_index_sets_for_condition(ctf: Contract, condition_id: bytes) -> list[int]:
    slot_count = ctf.functions.getOutcomeSlotCount(condition_id).call()
    if slot_count <= 0:
        raise ValueError(
            f"Condition {Web3.to_hex(condition_id)} has zero outcome slots. Verify the condition ID."
        )
    return [1 << i for i in range(slot_count)]


def _dedupe_requests(requests: Sequence[ConditionRedeemRequest]) -> list[ConditionRedeemRequest]:
    merged: dict[bytes, set[int]] = {}
    for req in requests:
        merged.setdefault(req.condition_id, set()).update(req.index_sets)

    return [
        ConditionRedeemRequest(condition_id=condition_id, index_sets=sorted(index_sets))
        for condition_id, index_sets in merged.items()
    ]


def _format_index_sets(index_sets: Iterable[int]) -> str:
    return "[" + ", ".join(str(i) for i in index_sets) + "]"


def main() -> int:
    args = parse_args()

    if not args.private_key:
        print("ERROR: private key is required via --private-key or POLYMARKET_PRIVATE_KEY", file=sys.stderr)
        return 1

    w3 = Web3(Web3.HTTPProvider(args.rpc_url))
    if not w3.is_connected():
        print(f"ERROR: failed to connect to RPC URL: {args.rpc_url}", file=sys.stderr)
        return 1

    try:
        config = resolve_config(args, w3)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    ctf = w3.eth.contract(address=config.ctf_address, abi=CTF_ABI)

    account = w3.eth.account.from_key(args.private_key)
    owner = account.address

    try:
        requests = load_condition_requests(args, ctf)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Owner:          {owner}")
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

        fn = ctf.functions.redeemPositions(
            config.collateral_token,
            b"\x00" * 32,
            req.condition_id,
            req.index_sets,
        )

        try:
            estimated_gas = fn.estimate_gas({"from": owner})
        except Exception as exc:  # noqa: BLE001
            print(f"[{idx}/{len(requests)}] ERROR estimating gas for {condition_hex}: {exc}")
            continue

        gas_limit = int(estimated_gas * args.gas_multiplier)

        print(
            f"[{idx}/{len(requests)}] Redeem {condition_hex} index_sets={_format_index_sets(req.index_sets)} "
            f"payout_denom={payout_denominator} gas~{gas_limit}"
        )

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
