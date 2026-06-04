from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
import sqlite3
from typing import Any, get_args, get_origin, get_type_hints

from .models import (
    AuditLog,
    ExceptionTask,
    InboundReceipt,
    InventoryLedgerEntry,
    ProductMaster,
    SalesOrder,
    Shipment,
    ShopSkuMapping,
    SyncTask,
)


class InMemoryRepository:
    _MODEL_FIELDS = {
        "products": ProductMaster,
        "shop_mappings": ShopSkuMapping,
        "inbounds": InboundReceipt,
        "orders": SalesOrder,
        "shipments": Shipment,
        "sync_tasks": SyncTask,
        "exception_tasks": ExceptionTask,
    }
    _LIST_FIELDS = {
        "inventory_entries": InventoryLedgerEntry,
        "audit_logs": AuditLog,
    }

    def __init__(self) -> None:
        self.products: dict[str, ProductMaster] = {}
        self.shop_mappings: dict[str, ShopSkuMapping] = {}
        self.inbounds: dict[str, InboundReceipt] = {}
        self.inventory_entries: list[InventoryLedgerEntry] = []
        self.orders: dict[str, SalesOrder] = {}
        self.shipments: dict[str, Shipment] = {}
        self.sync_tasks: dict[str, SyncTask] = {}
        self.exception_tasks: dict[str, ExceptionTask] = {}
        self.audit_logs: list[AuditLog] = []
        self.inventory_by_sku: defaultdict[str, int] = defaultdict(int)

    def to_snapshot(self) -> dict[str, Any]:
        return {
            field_name: {key: self._serialize(value) for key, value in getattr(self, field_name).items()}
            for field_name in self._MODEL_FIELDS
        } | {
            field_name: [self._serialize(value) for value in getattr(self, field_name)]
            for field_name in self._LIST_FIELDS
        } | {
            "inventory_by_sku": dict(self.inventory_by_sku),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict[str, Any]) -> InMemoryRepository:
        repo = cls()
        repo._apply_snapshot(snapshot)
        return repo

    def _apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        for field_name, model_cls in self._MODEL_FIELDS.items():
            collection = {
                key: self._deserialize(model_cls, value)
                for key, value in snapshot.get(field_name, {}).items()
            }
            setattr(self, field_name, collection)
        for field_name, model_cls in self._LIST_FIELDS.items():
            collection = [
                self._deserialize(model_cls, value)
                for value in snapshot.get(field_name, [])
            ]
            setattr(self, field_name, collection)
        self.inventory_by_sku = defaultdict(int, snapshot.get("inventory_by_sku", {}))

    def save_to_file(self, file_path: str | Path) -> Path:
        path = Path(file_path)
        path.write_text(
            json.dumps(self.to_snapshot(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load_from_file(cls, file_path: str | Path) -> InMemoryRepository:
        path = Path(file_path)
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_snapshot(snapshot)

    def commit(self) -> None:
        return None

    def close(self) -> None:
        return None

    @staticmethod
    def _serialize(value: Any) -> Any:
        if is_dataclass(value):
            return {
                field_name: InMemoryRepository._serialize(field_value)
                for field_name, field_value in asdict(value).items()
            }
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, list):
            return [InMemoryRepository._serialize(item) for item in value]
        if isinstance(value, dict):
            return {key: InMemoryRepository._serialize(item) for key, item in value.items()}
        return value

    @staticmethod
    def _deserialize(model_cls: type[Any], payload: dict[str, Any]) -> Any:
        type_hints = get_type_hints(model_cls)
        values = {}
        for field in fields(model_cls):
            raw_value = payload[field.name]
            values[field.name] = InMemoryRepository._deserialize_value(type_hints[field.name], raw_value)
        return model_cls(**values)

    @staticmethod
    def _deserialize_value(field_type: Any, value: Any) -> Any:
        origin = get_origin(field_type)
        if origin is list:
            (item_type,) = get_args(field_type)
            return [InMemoryRepository._deserialize_value(item_type, item) for item in value]
        if origin is dict:
            _, item_type = get_args(field_type)
            return {key: InMemoryRepository._deserialize_value(item_type, item) for key, item in value.items()}
        if origin is not None:
            args = [arg for arg in get_args(field_type) if arg is not type(None)]
            if value is None:
                return None
            if len(args) == 1:
                return InMemoryRepository._deserialize_value(args[0], value)
        if isinstance(field_type, type) and issubclass(field_type, datetime):
            return datetime.fromisoformat(value)
        if isinstance(field_type, type) and issubclass(field_type, Enum):
            return field_type(value)
        return value


class SQLiteRepository(InMemoryRepository):
    def __init__(self, database_path: str | Path) -> None:
        super().__init__()
        self.database_path = Path(database_path)
        self.connection = sqlite3.connect(self.database_path)
        self._create_schema()
        self._load_from_database()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS repo_entities (
                collection_name TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (collection_name, entity_key)
            );

            CREATE TABLE IF NOT EXISTS repo_lists (
                collection_name TEXT NOT NULL,
                item_index INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (collection_name, item_index)
            );

            CREATE TABLE IF NOT EXISTS inventory_balances (
                master_sku TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL
            );
            """
        )
        self.connection.commit()

    def _load_from_database(self) -> None:
        snapshot: dict[str, Any] = {
            field_name: {}
            for field_name in self._MODEL_FIELDS
        } | {
            field_name: []
            for field_name in self._LIST_FIELDS
        } | {
            "inventory_by_sku": {},
        }

        entity_rows = self.connection.execute(
            "SELECT collection_name, entity_key, payload_json FROM repo_entities"
        ).fetchall()
        for collection_name, entity_key, payload_json in entity_rows:
            snapshot[collection_name][entity_key] = json.loads(payload_json)

        list_rows = self.connection.execute(
            "SELECT collection_name, item_index, payload_json FROM repo_lists ORDER BY collection_name, item_index"
        ).fetchall()
        for collection_name, _, payload_json in list_rows:
            snapshot[collection_name].append(json.loads(payload_json))

        inventory_rows = self.connection.execute(
            "SELECT master_sku, quantity FROM inventory_balances"
        ).fetchall()
        for master_sku, quantity in inventory_rows:
            snapshot["inventory_by_sku"][master_sku] = quantity

        self._apply_snapshot(snapshot)

    def commit(self) -> None:
        snapshot = self.to_snapshot()
        with self.connection:
            self.connection.execute("DELETE FROM repo_entities")
            self.connection.execute("DELETE FROM repo_lists")
            self.connection.execute("DELETE FROM inventory_balances")

            entity_rows = []
            for collection_name in self._MODEL_FIELDS:
                entity_rows.extend(
                    (
                        collection_name,
                        entity_key,
                        json.dumps(payload, ensure_ascii=False),
                    )
                    for entity_key, payload in snapshot[collection_name].items()
                )
            self.connection.executemany(
                "INSERT INTO repo_entities (collection_name, entity_key, payload_json) VALUES (?, ?, ?)",
                entity_rows,
            )

            list_rows = []
            for collection_name in self._LIST_FIELDS:
                list_rows.extend(
                    (
                        collection_name,
                        index,
                        json.dumps(payload, ensure_ascii=False),
                    )
                    for index, payload in enumerate(snapshot[collection_name])
                )
            self.connection.executemany(
                "INSERT INTO repo_lists (collection_name, item_index, payload_json) VALUES (?, ?, ?)",
                list_rows,
            )

            inventory_rows = [
                (master_sku, quantity)
                for master_sku, quantity in snapshot["inventory_by_sku"].items()
            ]
            self.connection.executemany(
                "INSERT INTO inventory_balances (master_sku, quantity) VALUES (?, ?)",
                inventory_rows,
            )

    def close(self) -> None:
        self.connection.close()
