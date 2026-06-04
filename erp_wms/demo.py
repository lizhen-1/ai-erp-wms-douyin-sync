from __future__ import annotations

import argparse
import json
from pathlib import Path

from .repository import InMemoryRepository, SQLiteRepository
from .services import WMSService

DEFAULT_STATE_FILE = Path(__file__).resolve().parent.parent / "sample_data" / "demo-state.json"
DEFAULT_SQLITE_FILE = Path(__file__).resolve().parent.parent / "sample_data" / "demo-state.db"
DEMO_MASTER_SKU = "MSKU-COAT-001"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ERP/WMS prototype demo workflow.")
    parser.add_argument(
        "--backend",
        choices=("json", "sqlite"),
        default="json",
        help="Repository backend used by the demo.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="Path to the persisted state file. Defaults depend on the backend.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Ignore any saved state and rebuild the demo flow from scratch.",
    )
    return parser.parse_args()


def resolve_state_file(backend: str, state_file: Path | None) -> Path:
    if state_file is not None:
        return state_file
    if backend == "sqlite":
        return DEFAULT_SQLITE_FILE
    return DEFAULT_STATE_FILE


def load_repository(backend: str, state_file: Path, *, reset: bool) -> InMemoryRepository:
    if backend == "sqlite":
        if reset and state_file.exists():
            state_file.unlink()
        state_file.parent.mkdir(parents=True, exist_ok=True)
        return SQLiteRepository(state_file)
    if not reset and state_file.exists():
        return InMemoryRepository.load_from_file(state_file)
    return InMemoryRepository()


def bootstrap_demo_data(service: WMSService) -> None:
    if DEMO_MASTER_SKU in service.repo.products:
        return

    service.create_product(
        master_sku=DEMO_MASTER_SKU,
        name="demo sun-protection coat",
        specification="white / one-size",
        base_attributes={"material": "polyester", "category": "outerwear"},
    )
    service.screen_for_listing(DEMO_MASTER_SKU, can_list=True, rule_note="eligible for initial Douyin rollout")
    service.set_default_price(DEMO_MASTER_SKU, cost_price=48, pricing_factor=2.5)
    service.approve_inbound(DEMO_MASTER_SKU, quantity=3, cost_price=48, pricing_factor=2.5)
    service.sync_to_shops(DEMO_MASTER_SKU, ["douyin-a", "douyin-b"])
    service.set_shop_override_price(DEMO_MASTER_SKU, "douyin-b", 139.0)
    service.sync_to_shops(DEMO_MASTER_SKU, ["douyin-b"])

    order = service.capture_order(
        source="douyin",
        source_order_id="DY10001",
        master_sku=DEMO_MASTER_SKU,
        quantity=1,
        receiver_name="Alice",
        address="Shanghai Pudong Test Road 18",
        customization_text="print text: AI first",
        note="priority",
    )
    service.ship_order(order.order_id, carrier="SF", tracking_no="SF123456")
    service.report_order(order.order_id)


def save_repository(repo: InMemoryRepository, state_file: Path, *, backend: str) -> Path:
    if backend == "sqlite":
        state_file.parent.mkdir(parents=True, exist_ok=True)
        repo.commit()
        return state_file
    state_file.parent.mkdir(parents=True, exist_ok=True)
    return repo.save_to_file(state_file)


def main() -> None:
    args = parse_args()
    state_file = resolve_state_file(args.backend, args.state_file)
    repo = load_repository(args.backend, state_file, reset=args.reset)
    service = WMSService(repo)
    bootstrap_demo_data(service)
    save_repository(repo, state_file, backend=args.backend)
    print(json.dumps(service.snapshot(), indent=2, ensure_ascii=False, default=str))
    repo.close()


if __name__ == "__main__":
    main()
