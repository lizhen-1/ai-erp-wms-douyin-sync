from __future__ import annotations

import unittest

from erp_wms.models import OrderStatus, ProductStatus, SyncTaskStatus
from erp_wms.repository import InMemoryRepository
from erp_wms.services import WMSService


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = InMemoryRepository()
        self.service = WMSService(self.repo)
        self.service.create_product(
            master_sku="MSKU-001",
            name="定制短袖",
            specification="黑色 / L",
            base_attributes={"category": "tee"},
        )
        self.service.screen_for_listing("MSKU-001", can_list=True, rule_note="首期核心店铺可上架")
        self.service.set_default_price("MSKU-001", cost_price=20, pricing_factor=3)

    def test_inbound_sync_and_override_price(self) -> None:
        self.service.approve_inbound("MSKU-001", quantity=5, cost_price=20, pricing_factor=3)
        self.service.set_shop_override_price("MSKU-001", "douyin-b", 79)
        task = self.service.sync_to_shops("MSKU-001", ["douyin-a", "douyin-b"])

        self.assertEqual(task.status, SyncTaskStatus.SUCCESS)
        self.assertEqual(self.repo.products["MSKU-001"].status, ProductStatus.SYNCED)
        mapping = [m for m in self.repo.shop_mappings.values() if m.shop_id == "douyin-b"][0]
        self.assertEqual(mapping.override_price, 79)
        self.assertTrue(mapping.published)

    def test_partial_sync_creates_exception(self) -> None:
        self.service.approve_inbound("MSKU-001", quantity=5, cost_price=20, pricing_factor=3)
        task = self.service.sync_to_shops("MSKU-001", ["douyin-a", "fail-shop"])

        self.assertEqual(task.status, SyncTaskStatus.PARTIAL_SUCCESS)
        self.assertEqual(self.repo.products["MSKU-001"].status, ProductStatus.SYNC_EXCEPTION)
        self.assertTrue(self.repo.exception_tasks)

    def test_order_with_missing_address_becomes_exception(self) -> None:
        self.service.approve_inbound("MSKU-001", quantity=2, cost_price=20, pricing_factor=3)
        order = self.service.capture_order(
            source="offline_custom",
            source_order_id="OFF-1",
            master_sku="MSKU-001",
            quantity=1,
            receiver_name="Bob",
            address="",
            customization_text="印字: Hello",
        )

        self.assertEqual(order.status, OrderStatus.EXCEPTION)
        self.assertIn("missing_address", order.exceptions)
        self.assertIn("定制信息建议结构化处理", order.ai_suggestion)

    def test_ship_order_reduces_inventory_and_delists_on_sellout(self) -> None:
        self.service.approve_inbound("MSKU-001", quantity=1, cost_price=20, pricing_factor=3)
        self.service.sync_to_shops("MSKU-001", ["douyin-a", "douyin-b"])
        order = self.service.capture_order(
            source="douyin",
            source_order_id="DY-1",
            master_sku="MSKU-001",
            quantity=1,
            receiver_name="Chen",
            address="Hangzhou Xihu 88",
        )

        self.assertEqual(order.status, OrderStatus.READY_TO_SHIP)
        self.service.ship_order(order.order_id, carrier="YTO", tracking_no="YT001")

        self.assertEqual(self.repo.inventory_by_sku["MSKU-001"], 0)
        self.assertEqual(self.repo.products["MSKU-001"].status, ProductStatus.DELISTED)
        self.assertTrue(all(not m.published for m in self.repo.shop_mappings.values()))


if __name__ == "__main__":
    unittest.main()
