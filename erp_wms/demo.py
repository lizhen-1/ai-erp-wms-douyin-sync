from __future__ import annotations

import json

from .repository import InMemoryRepository
from .services import WMSService


def main() -> None:
    repo = InMemoryRepository()
    service = WMSService(repo)

    service.create_product(
        master_sku="MSKU-COAT-001",
        name="夏季定制防晒服",
        specification="白色 / 均码",
        base_attributes={"material": "polyester", "category": "outerwear"},
    )
    service.screen_for_listing("MSKU-COAT-001", can_list=True, rule_note="适合抖店上架")
    service.set_default_price("MSKU-COAT-001", cost_price=48, pricing_factor=2.5)
    service.approve_inbound("MSKU-COAT-001", quantity=3, cost_price=48, pricing_factor=2.5)
    service.sync_to_shops("MSKU-COAT-001", ["douyin-a", "douyin-b"])
    service.set_shop_override_price("MSKU-COAT-001", "douyin-b", 139.0)
    service.sync_to_shops("MSKU-COAT-001", ["douyin-b"])

    order = service.capture_order(
        source="douyin",
        source_order_id="DY10001",
        master_sku="MSKU-COAT-001",
        quantity=1,
        receiver_name="Alice",
        address="Shanghai Pudong Test Road 18",
        customization_text="印字: AI先行",
        note="加急",
    )
    service.ship_order(order.order_id, carrier="SF", tracking_no="SF123456")
    service.report_order(order.order_id)

    print(json.dumps(service.snapshot(), indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
