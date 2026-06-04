from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from itertools import count

from .models import (
    AuditLog,
    ExceptionTask,
    ExceptionTaskStatus,
    InboundReceipt,
    InventoryLedgerEntry,
    OrderStatus,
    ProductMaster,
    ProductStatus,
    SalesOrder,
    Shipment,
    ShipmentStatus,
    ShopSkuMapping,
    SyncTask,
    SyncTaskStatus,
)
from .repository import InMemoryRepository


class DouyinGateway:
    """Mock gateway for prototype purposes."""

    def create_or_update_sku(
        self,
        *,
        shop_id: str,
        master_sku: str,
        product_name: str,
        price: float,
    ) -> tuple[bool, dict[str, str]]:
        if shop_id.startswith("fail"):
            return False, {"error": f"shop {shop_id} rejected sync"}
        suffix = f"{shop_id}-{master_sku}"
        return True, {
            "platform_product_id": f"prod-{suffix}",
            "platform_sku_id": f"sku-{suffix}",
        }

    def delist_sku(self, *, shop_id: str, platform_sku_id: str) -> tuple[bool, str]:
        if shop_id.startswith("fail-delist"):
            return False, "delist request failed"
        return True, "ok"


class AIAssistant:
    """Prototype assistant that structures customization text and exceptions."""

    def review_order(self, order: SalesOrder) -> str:
        hints: list[str] = []
        if not order.address.strip():
            hints.append("地址缺失，需人工确认收货信息。")
        if order.customization_text.strip():
            hints.append(f"定制信息建议结构化处理: {order.customization_text}")
        if "加急" in order.note:
            hints.append("订单备注包含加急，建议优先处理。")
        if not hints:
            hints.append("订单字段完整，可按常规流程进入发货。")
        return " ".join(hints)


class WMSService:
    def __init__(
        self,
        repository: InMemoryRepository,
        gateway: DouyinGateway | None = None,
        ai_assistant: AIAssistant | None = None,
    ) -> None:
        self.repo = repository
        self.gateway = gateway or DouyinGateway()
        self.ai = ai_assistant or AIAssistant()
        self._seq = count(1)

    def _next_id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._seq):05d}"

    def _audit(self, action: str, reference_id: str, details: dict[str, str]) -> None:
        self.repo.audit_logs.append(
            AuditLog(
                log_id=self._next_id("log"),
                action=action,
                reference_id=reference_id,
                details=details,
            )
        )

    def _raise_exception(self, category: str, reference_id: str, message: str) -> None:
        task = ExceptionTask(
            task_id=self._next_id("exc"),
            category=category,
            reference_id=reference_id,
            message=message,
        )
        self.repo.exception_tasks[task.task_id] = task
        self._audit("exception_created", reference_id, {"category": category, "message": message})

    def create_product(
        self,
        *,
        master_sku: str,
        name: str,
        specification: str,
        base_attributes: dict[str, str],
    ) -> ProductMaster:
        product = ProductMaster(
            product_id=self._next_id("prd"),
            master_sku=master_sku,
            name=name,
            specification=specification,
            base_attributes=base_attributes,
        )
        self.repo.products[master_sku] = product
        self._audit("product_created", master_sku, {"name": name})
        return product

    def screen_for_listing(self, master_sku: str, *, can_list: bool, rule_note: str) -> ProductMaster:
        product: ProductMaster = self.repo.products[master_sku]
        product.can_list = can_list
        product.listing_rules["screening_note"] = rule_note
        product.status = ProductStatus.PENDING_PRICING if can_list else ProductStatus.PENDING_SCREENING
        self._audit("product_screened", master_sku, {"can_list": str(can_list), "note": rule_note})
        return product

    def set_default_price(self, master_sku: str, *, cost_price: float, pricing_factor: float) -> ProductMaster:
        product: ProductMaster = self.repo.products[master_sku]
        product.default_price = round(cost_price * pricing_factor, 2)
        product.status = ProductStatus.PENDING_REVIEW
        self._audit(
            "default_price_set",
            master_sku,
            {"cost_price": str(cost_price), "pricing_factor": str(pricing_factor), "price": str(product.default_price)},
        )
        return product

    def approve_inbound(
        self,
        master_sku: str,
        *,
        quantity: int,
        cost_price: float,
        pricing_factor: float,
    ) -> InboundReceipt:
        product: ProductMaster = self.repo.products[master_sku]
        if not product.can_list:
            raise ValueError("product is not approved for listing")
        if product.default_price is None:
            self.set_default_price(master_sku, cost_price=cost_price, pricing_factor=pricing_factor)
        receipt = InboundReceipt(
            receipt_id=self._next_id("inb"),
            master_sku=master_sku,
            quantity=quantity,
            cost_price=cost_price,
            pricing_factor=pricing_factor,
            approved=True,
            approved_at=datetime.now(UTC),
        )
        self.repo.inbounds[receipt.receipt_id] = receipt
        product.status = ProductStatus.PENDING_SYNC
        self._change_inventory(master_sku, quantity, "inbound_approved")
        self._audit("inbound_approved", receipt.receipt_id, {"master_sku": master_sku, "quantity": str(quantity)})
        return receipt

    def _change_inventory(self, master_sku: str, delta: int, reason: str) -> None:
        entry = InventoryLedgerEntry(
            entry_id=self._next_id("inv"),
            master_sku=master_sku,
            delta=delta,
            reason=reason,
        )
        self.repo.inventory_entries.append(entry)
        self.repo.inventory_by_sku[master_sku] += delta
        self._audit("inventory_changed", master_sku, {"delta": str(delta), "reason": reason})

    def sync_to_shops(self, master_sku: str, shop_ids: list[str]) -> SyncTask:
        product: ProductMaster = self.repo.products[master_sku]
        task = SyncTask(task_id=self._next_id("syn"), master_sku=master_sku, shop_ids=shop_ids, status=SyncTaskStatus.RUNNING)
        self.repo.sync_tasks[task.task_id] = task
        success_count = 0

        for shop_id in shop_ids:
            mapping = self._find_or_create_mapping(master_sku, shop_id)
            effective_price = mapping.override_price if mapping.override_price is not None else product.default_price
            ok, payload = self.gateway.create_or_update_sku(
                shop_id=shop_id,
                master_sku=master_sku,
                product_name=product.name,
                price=effective_price or 0.0,
            )
            if ok:
                mapping.platform_product_id = payload["platform_product_id"]
                mapping.platform_sku_id = payload["platform_sku_id"]
                mapping.published = True
                mapping.sync_status = SyncTaskStatus.SUCCESS
                success_count += 1
            else:
                mapping.sync_status = SyncTaskStatus.FAILED
                message = payload["error"]
                task.error_messages.append(message)
                self._raise_exception("sync_failure", mapping.mapping_id, message)

        if success_count == len(shop_ids):
            task.status = SyncTaskStatus.SUCCESS
            product.status = ProductStatus.SYNCED
        elif success_count == 0:
            task.status = SyncTaskStatus.FAILED
            product.status = ProductStatus.SYNC_EXCEPTION
        else:
            task.status = SyncTaskStatus.PARTIAL_SUCCESS
            product.status = ProductStatus.SYNC_EXCEPTION

        self._audit("shop_sync_completed", task.task_id, {"master_sku": master_sku, "status": task.status})
        return task

    def _find_or_create_mapping(self, master_sku: str, shop_id: str) -> ShopSkuMapping:
        for mapping in self.repo.shop_mappings.values():
            if mapping.master_sku == master_sku and mapping.shop_id == shop_id:
                return mapping
        mapping = ShopSkuMapping(mapping_id=self._next_id("map"), master_sku=master_sku, shop_id=shop_id)
        self.repo.shop_mappings[mapping.mapping_id] = mapping
        return mapping

    def set_shop_override_price(self, master_sku: str, shop_id: str, price: float) -> ShopSkuMapping:
        mapping = self._find_or_create_mapping(master_sku, shop_id)
        mapping.override_price = price
        self._audit("shop_price_override_set", mapping.mapping_id, {"price": str(price)})
        return mapping

    def capture_order(
        self,
        *,
        source: str,
        source_order_id: str,
        master_sku: str,
        quantity: int,
        receiver_name: str,
        address: str,
        customization_text: str = "",
        note: str = "",
    ) -> SalesOrder:
        order = SalesOrder(
            order_id=self._next_id("ord"),
            source=source,
            source_order_id=source_order_id,
            master_sku=master_sku,
            quantity=quantity,
            receiver_name=receiver_name,
            address=address,
            customization_text=customization_text,
            note=note,
            status=OrderStatus.PENDING_REVIEW,
        )
        order.ai_suggestion = self.ai.review_order(order)

        if not address.strip():
            order.exceptions.append("missing_address")
        if quantity > self.repo.inventory_by_sku[master_sku]:
            order.exceptions.append("insufficient_inventory")
        if not self.repo.products[master_sku].can_list:
            order.exceptions.append("product_not_approved")

        order.status = OrderStatus.EXCEPTION if order.exceptions else OrderStatus.READY_TO_SHIP
        self.repo.orders[order.order_id] = order
        if order.exceptions:
            self._raise_exception("order_review", order.order_id, ",".join(order.exceptions))
        self._audit("order_captured", order.order_id, {"status": order.status, "source": source})
        return order

    def ship_order(self, order_id: str, *, carrier: str, tracking_no: str) -> Shipment:
        order: SalesOrder = self.repo.orders[order_id]
        if order.status != OrderStatus.READY_TO_SHIP:
            raise ValueError("order is not ready to ship")
        shipment = Shipment(
            shipment_id=self._next_id("shp"),
            order_id=order_id,
            master_sku=order.master_sku,
            quantity=order.quantity,
            carrier=carrier,
            tracking_no=tracking_no,
            status=ShipmentStatus.SHIPPED,
        )
        self.repo.shipments[shipment.shipment_id] = shipment
        self._change_inventory(order.master_sku, -order.quantity, "shipment")
        order.status = OrderStatus.SHIPPED
        self._audit("order_shipped", order_id, {"carrier": carrier, "tracking_no": tracking_no})
        self._delist_if_needed(order.master_sku)
        return shipment

    def _delist_if_needed(self, master_sku: str) -> None:
        if self.repo.inventory_by_sku[master_sku] > 0:
            return
        product: ProductMaster = self.repo.products[master_sku]
        failed_shops: list[str] = []
        for mapping in self.repo.shop_mappings.values():
            if mapping.master_sku != master_sku or not mapping.published or not mapping.platform_sku_id:
                continue
            ok, message = self.gateway.delist_sku(shop_id=mapping.shop_id, platform_sku_id=mapping.platform_sku_id)
            if ok:
                mapping.published = False
            else:
                failed_shops.append(mapping.shop_id)
                self._raise_exception("delist_failure", mapping.mapping_id, message)
        if failed_shops:
            product.status = ProductStatus.SYNC_EXCEPTION
        else:
            product.status = ProductStatus.DELISTED
        self._audit("product_delist_checked", master_sku, {"remaining_inventory": str(self.repo.inventory_by_sku[master_sku])})

    def report_order(self, order_id: str) -> SalesOrder:
        order: SalesOrder = self.repo.orders[order_id]
        if order.status != OrderStatus.SHIPPED:
            raise ValueError("order must be shipped before reporting")
        order.status = OrderStatus.REPORTED
        self._audit("order_reported", order_id, {"source_order_id": order.source_order_id})
        return order

    def snapshot(self) -> dict[str, object]:
        return {
            "products": {key: asdict(value) for key, value in self.repo.products.items()},
            "inventory": dict(self.repo.inventory_by_sku),
            "orders": {key: asdict(value) for key, value in self.repo.orders.items()},
            "shop_mappings": {key: asdict(value) for key, value in self.repo.shop_mappings.items()},
            "exceptions": {key: asdict(value) for key, value in self.repo.exception_tasks.items()},
            "audit_count": len(self.repo.audit_logs),
        }
