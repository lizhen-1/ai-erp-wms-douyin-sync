from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ProductStatus(StrEnum):
    PENDING_SCREENING = "pending_screening"
    PENDING_PRICING = "pending_pricing"
    PENDING_REVIEW = "pending_review"
    INBOUNDED = "inbounded"
    PENDING_SYNC = "pending_sync"
    SYNCED = "synced"
    SYNC_EXCEPTION = "sync_exception"
    DELISTED = "delisted"


class OrderStatus(StrEnum):
    PENDING_CAPTURE = "pending_capture"
    PENDING_REVIEW = "pending_review"
    EXCEPTION = "exception"
    READY_TO_SHIP = "ready_to_ship"
    SHIPPED = "shipped"
    REPORTED = "reported"


class SyncTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    PENDING_MANUAL = "pending_manual"


class ShipmentStatus(StrEnum):
    PENDING = "pending"
    SHIPPED = "shipped"


class ExceptionTaskStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


@dataclass
class ProductMaster:
    product_id: str
    master_sku: str
    name: str
    specification: str
    base_attributes: dict[str, str]
    default_price: float | None = None
    status: ProductStatus = ProductStatus.PENDING_SCREENING
    listing_rules: dict[str, str] = field(default_factory=dict)
    media_assets: list[str] = field(default_factory=list)
    can_list: bool = False


@dataclass
class ShopSkuMapping:
    mapping_id: str
    master_sku: str
    shop_id: str
    platform_product_id: str | None = None
    platform_sku_id: str | None = None
    published: bool = False
    sync_status: SyncTaskStatus = SyncTaskStatus.PENDING
    override_price: float | None = None


@dataclass
class InboundReceipt:
    receipt_id: str
    master_sku: str
    quantity: int
    cost_price: float
    pricing_factor: float
    approved: bool = False
    approved_at: datetime | None = None


@dataclass
class InventoryLedgerEntry:
    entry_id: str
    master_sku: str
    delta: int
    reason: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class SalesOrder:
    order_id: str
    source: str
    source_order_id: str
    master_sku: str
    quantity: int
    receiver_name: str
    address: str
    customization_text: str = ""
    note: str = ""
    status: OrderStatus = OrderStatus.PENDING_CAPTURE
    exceptions: list[str] = field(default_factory=list)
    ai_suggestion: str = ""


@dataclass
class Shipment:
    shipment_id: str
    order_id: str
    master_sku: str
    quantity: int
    carrier: str
    tracking_no: str
    status: ShipmentStatus = ShipmentStatus.PENDING


@dataclass
class SyncTask:
    task_id: str
    master_sku: str
    shop_ids: list[str]
    status: SyncTaskStatus = SyncTaskStatus.PENDING
    error_messages: list[str] = field(default_factory=list)


@dataclass
class ExceptionTask:
    task_id: str
    category: str
    reference_id: str
    message: str
    status: ExceptionTaskStatus = ExceptionTaskStatus.OPEN


@dataclass
class AuditLog:
    log_id: str
    action: str
    reference_id: str
    details: dict[str, str]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
