from __future__ import annotations

from collections import defaultdict


class InMemoryRepository:
    def __init__(self) -> None:
        self.products: dict[str, object] = {}
        self.shop_mappings: dict[str, object] = {}
        self.inbounds: dict[str, object] = {}
        self.inventory_entries: list[object] = []
        self.orders: dict[str, object] = {}
        self.shipments: dict[str, object] = {}
        self.sync_tasks: dict[str, object] = {}
        self.exception_tasks: dict[str, object] = {}
        self.audit_logs: list[object] = []
        self.inventory_by_sku: defaultdict[str, int] = defaultdict(int)

