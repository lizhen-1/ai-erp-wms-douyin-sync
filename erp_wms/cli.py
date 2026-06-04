from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .demo import load_repository, resolve_state_file, save_repository
from .services import WMSService


def parse_key_value_pairs(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        key, separator, value = item.partition("=")
        if not separator:
            raise ValueError(f"invalid key=value item: {item}")
        result[key] = value
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ERP/WMS prototype CLI.")
    parser.add_argument("--backend", choices=("json", "sqlite"), default="sqlite")
    parser.add_argument("--state-file", type=Path, default=None)
    parser.add_argument("--reset", action="store_true")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("snapshot", help="Print the current repository snapshot.")
    subparsers.add_parser("bootstrap-demo", help="Seed the default demo data when missing.")

    create_product = subparsers.add_parser("create-product", help="Create a master product.")
    create_product.add_argument("--master-sku", required=True)
    create_product.add_argument("--name", required=True)
    create_product.add_argument("--specification", required=True)
    create_product.add_argument("--attribute", action="append", default=[])

    screen_product = subparsers.add_parser("screen-product", help="Screen a product for listing.")
    screen_product.add_argument("--master-sku", required=True)
    screen_product.add_argument("--can-list", choices=("true", "false"), required=True)
    screen_product.add_argument("--rule-note", required=True)

    set_price = subparsers.add_parser("set-price", help="Set the default price for a master SKU.")
    set_price.add_argument("--master-sku", required=True)
    set_price.add_argument("--cost-price", type=float, required=True)
    set_price.add_argument("--pricing-factor", type=float, required=True)

    approve_inbound = subparsers.add_parser("approve-inbound", help="Approve inbound stock.")
    approve_inbound.add_argument("--master-sku", required=True)
    approve_inbound.add_argument("--quantity", type=int, required=True)
    approve_inbound.add_argument("--cost-price", type=float, required=True)
    approve_inbound.add_argument("--pricing-factor", type=float, required=True)

    sync_shops = subparsers.add_parser("sync-shops", help="Sync a master SKU to shops.")
    sync_shops.add_argument("--master-sku", required=True)
    sync_shops.add_argument("--shop", action="append", required=True, default=[])

    set_override = subparsers.add_parser("set-shop-price", help="Override price for a shop SKU mapping.")
    set_override.add_argument("--master-sku", required=True)
    set_override.add_argument("--shop-id", required=True)
    set_override.add_argument("--price", type=float, required=True)

    capture_order = subparsers.add_parser("capture-order", help="Capture an order into the order pool.")
    capture_order.add_argument("--source", required=True)
    capture_order.add_argument("--source-order-id", required=True)
    capture_order.add_argument("--master-sku", required=True)
    capture_order.add_argument("--quantity", type=int, required=True)
    capture_order.add_argument("--receiver-name", required=True)
    capture_order.add_argument("--address", required=True)
    capture_order.add_argument("--customization-text", default="")
    capture_order.add_argument("--note", default="")

    ship_order = subparsers.add_parser("ship-order", help="Ship an order.")
    ship_order.add_argument("--order-id", required=True)
    ship_order.add_argument("--carrier", required=True)
    ship_order.add_argument("--tracking-no", required=True)

    report_order = subparsers.add_parser("report-order", help="Mark a shipped order as reported.")
    report_order.add_argument("--order-id", required=True)

    return parser


def run_command(service: WMSService, args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "snapshot":
        return service.snapshot()
    if args.command == "bootstrap-demo":
        from .demo import bootstrap_demo_data

        bootstrap_demo_data(service)
        return service.snapshot()
    if args.command == "create-product":
        product = service.create_product(
            master_sku=args.master_sku,
            name=args.name,
            specification=args.specification,
            base_attributes=parse_key_value_pairs(args.attribute),
        )
        return {"product": product.master_sku, "status": product.status}
    if args.command == "screen-product":
        product = service.screen_for_listing(
            args.master_sku,
            can_list=args.can_list == "true",
            rule_note=args.rule_note,
        )
        return {"product": product.master_sku, "status": product.status, "can_list": product.can_list}
    if args.command == "set-price":
        product = service.set_default_price(
            args.master_sku,
            cost_price=args.cost_price,
            pricing_factor=args.pricing_factor,
        )
        return {"product": product.master_sku, "default_price": product.default_price}
    if args.command == "approve-inbound":
        receipt = service.approve_inbound(
            args.master_sku,
            quantity=args.quantity,
            cost_price=args.cost_price,
            pricing_factor=args.pricing_factor,
        )
        return {"receipt_id": receipt.receipt_id, "master_sku": receipt.master_sku, "quantity": receipt.quantity}
    if args.command == "sync-shops":
        task = service.sync_to_shops(args.master_sku, args.shop)
        return {"task_id": task.task_id, "status": task.status, "errors": task.error_messages}
    if args.command == "set-shop-price":
        mapping = service.set_shop_override_price(args.master_sku, args.shop_id, args.price)
        return {"mapping_id": mapping.mapping_id, "shop_id": mapping.shop_id, "override_price": mapping.override_price}
    if args.command == "capture-order":
        order = service.capture_order(
            source=args.source,
            source_order_id=args.source_order_id,
            master_sku=args.master_sku,
            quantity=args.quantity,
            receiver_name=args.receiver_name,
            address=args.address,
            customization_text=args.customization_text,
            note=args.note,
        )
        return {"order_id": order.order_id, "status": order.status, "exceptions": order.exceptions}
    if args.command == "ship-order":
        shipment = service.ship_order(args.order_id, carrier=args.carrier, tracking_no=args.tracking_no)
        return {"shipment_id": shipment.shipment_id, "order_id": shipment.order_id, "status": shipment.status}
    if args.command == "report-order":
        order = service.report_order(args.order_id)
        return {"order_id": order.order_id, "status": order.status}
    raise ValueError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    state_file = resolve_state_file(args.backend, args.state_file)
    repo = load_repository(args.backend, state_file, reset=args.reset)
    service = WMSService(repo)
    try:
        payload = run_command(service, args)
        save_repository(repo, state_file, backend=args.backend)
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    finally:
        repo.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
