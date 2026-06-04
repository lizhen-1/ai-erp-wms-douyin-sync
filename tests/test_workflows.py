from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from erp_wms.cli import main as cli_main
from erp_wms.demo import bootstrap_demo_data, load_repository, save_repository
from erp_wms.models import OrderStatus, ProductStatus, SyncTaskStatus
from erp_wms.repository import InMemoryRepository, SQLiteRepository
from erp_wms.services import WMSService


class WorkflowTests(unittest.TestCase):
    def run_cli(self, argv: list[str]) -> None:
        with redirect_stdout(StringIO()):
            cli_main(argv)

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

    def test_repository_snapshot_roundtrip_preserves_workflow_state(self) -> None:
        self.service.approve_inbound("MSKU-001", quantity=3, cost_price=20, pricing_factor=3)
        self.service.sync_to_shops("MSKU-001", ["douyin-a"])
        order = self.service.capture_order(
            source="douyin",
            source_order_id="DY-2",
            master_sku="MSKU-001",
            quantity=1,
            receiver_name="Dai",
            address="Suzhou Park 66",
        )
        self.service.ship_order(order.order_id, carrier="ZTO", tracking_no="ZT002")

        snapshot = self.repo.to_snapshot()
        restored_repo = InMemoryRepository.from_snapshot(snapshot)

        self.assertEqual(restored_repo.inventory_by_sku["MSKU-001"], 2)
        self.assertEqual(restored_repo.products["MSKU-001"].status, ProductStatus.SYNCED)
        self.assertEqual(restored_repo.orders[order.order_id].status, OrderStatus.SHIPPED)
        self.assertEqual(len(restored_repo.audit_logs), len(self.repo.audit_logs))

    def test_repository_file_roundtrip_supports_continued_operations(self) -> None:
        self.service.approve_inbound("MSKU-001", quantity=2, cost_price=20, pricing_factor=3)

        with TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "repo-state.json"
            self.repo.save_to_file(snapshot_path)

            restored_repo = InMemoryRepository.load_from_file(snapshot_path)
            restored_service = WMSService(restored_repo)
            order = restored_service.capture_order(
                source="douyin",
                source_order_id="DY-3",
                master_sku="MSKU-001",
                quantity=1,
                receiver_name="Eve",
                address="Ningbo Center 10",
            )

        self.assertEqual(order.order_id, "ord-00009")
        self.assertEqual(restored_repo.orders[order.order_id].status, OrderStatus.READY_TO_SHIP)

    def test_demo_bootstrap_reuses_saved_state_without_duplicate_seed_data(self) -> None:
        with TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "demo-state.json"

            repo = load_repository("json", state_file, reset=False)
            service = WMSService(repo)
            bootstrap_demo_data(service)
            save_repository(repo, state_file, backend="json")

            restored_repo = load_repository("json", state_file, reset=False)
            restored_service = WMSService(restored_repo)
            bootstrap_demo_data(restored_service)

        self.assertEqual(len(restored_repo.products), 1)
        self.assertEqual(len(restored_repo.orders), 1)
        self.assertEqual(restored_repo.inventory_by_sku["MSKU-COAT-001"], 2)

    def test_sqlite_repository_persists_and_restores_workflow_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "erp-wms.db"
            repo = SQLiteRepository(database_path)
            service = WMSService(repo)
            service.create_product(
                master_sku="MSKU-SQL-001",
                name="SQLite tee",
                specification="black / M",
                base_attributes={"category": "tee"},
            )
            service.screen_for_listing("MSKU-SQL-001", can_list=True, rule_note="sqlite-ready")
            service.approve_inbound("MSKU-SQL-001", quantity=4, cost_price=30, pricing_factor=2)
            service.sync_to_shops("MSKU-SQL-001", ["douyin-a"])
            repo.close()

            restored_repo = SQLiteRepository(database_path)
            restored_service = WMSService(restored_repo)
            order = restored_service.capture_order(
                source="douyin",
                source_order_id="DY-SQL-1",
                master_sku="MSKU-SQL-001",
                quantity=1,
                receiver_name="Fang",
                address="Wuhan Optics Valley 1",
            )

            self.assertEqual(restored_repo.inventory_by_sku["MSKU-SQL-001"], 4)
            self.assertEqual(restored_repo.products["MSKU-SQL-001"].status, ProductStatus.SYNCED)
            self.assertEqual(order.status, OrderStatus.READY_TO_SHIP)
            self.assertEqual(len(restored_repo.shop_mappings), 1)
            restored_repo.close()

    def test_cli_flow_updates_sqlite_repository(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "cli-state.db"

            self.run_cli(
                [
                    "--backend",
                    "sqlite",
                    "--state-file",
                    str(database_path),
                    "create-product",
                    "--master-sku",
                    "MSKU-CLI-001",
                    "--name",
                    "CLI Hoodie",
                    "--specification",
                    "gray / XL",
                    "--attribute",
                    "category=hoodie",
                ]
            )
            self.run_cli(
                [
                    "--backend",
                    "sqlite",
                    "--state-file",
                    str(database_path),
                    "screen-product",
                    "--master-sku",
                    "MSKU-CLI-001",
                    "--can-list",
                    "true",
                    "--rule-note",
                    "cli-approved",
                ]
            )
            self.run_cli(
                [
                    "--backend",
                    "sqlite",
                    "--state-file",
                    str(database_path),
                    "approve-inbound",
                    "--master-sku",
                    "MSKU-CLI-001",
                    "--quantity",
                    "2",
                    "--cost-price",
                    "35",
                    "--pricing-factor",
                    "2.2",
                ]
            )
            self.run_cli(
                [
                    "--backend",
                    "sqlite",
                    "--state-file",
                    str(database_path),
                    "sync-shops",
                    "--master-sku",
                    "MSKU-CLI-001",
                    "--shop",
                    "douyin-a",
                ]
            )

            repo = SQLiteRepository(database_path)
            self.assertEqual(repo.inventory_by_sku["MSKU-CLI-001"], 2)
            self.assertEqual(repo.products["MSKU-CLI-001"].status, ProductStatus.SYNCED)
            self.assertEqual(len(repo.shop_mappings), 1)
            repo.close()


if __name__ == "__main__":
    unittest.main()
