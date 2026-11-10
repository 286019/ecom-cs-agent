"""第三层·工具层：mock / 真实接口双数据源适配。

- 默认 mock：内置演示数据，零依赖跑通全流程。
- 真实接口：TOOL_BACKEND=http + TOOL_API_BASE + TOOL_API_KEY 开启。
  Base URL、鉴权请求头、查询参数名、字段 JSONPath 全部在 config/tools_http.json 配置，
  返回的 JSON 只按配置抽取需要的字段，不会把整段响应塞给模型或用户。
- 真实接口异常时自动降级回 mock，并在结果 meta 里标记 degraded，前端会提示。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from . import mock_data
from .config import BASE_DIR, Settings
from .jsonpath import extract_all, extract_one

log = logging.getLogger("ecom.datasource")

HTTP_CONFIG_PATH = BASE_DIR / "config" / "tools_http.json"
NUMERIC_FIELDS = {"paid_amount", "price", "stock", "refund_amount"}


class DataSourceError(RuntimeError):
    pass


class DataSource:
    def __init__(self, settings: Settings, config_path: Path | None = None):
        self.settings = settings
        self.config_path = config_path or HTTP_CONFIG_PATH
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.mode = "http" if settings.tool_backend == "http" and settings.tool_api_base else "mock"

    # ---------- 真实接口 ----------

    def _headers(self) -> dict:
        if not self.settings.tool_api_key:
            return {}
        auth = self.config.get("auth", {})
        header = self.settings.tool_api_key_header or auth.get("header", "Authorization")
        prefix = auth.get("prefix", "")
        return {header: f"{prefix}{self.settings.tool_api_key}"}

    def _fetch_http(self, tool: str, params: dict) -> list[dict]:
        spec = (self.config.get("tools") or {}).get(tool)
        if not spec:
            raise DataSourceError(f"未配置工具 {tool} 的接口映射")

        query = {
            remote: params.get(local)
            for local, remote in (spec.get("params") or {}).items()
            if params.get(local) not in (None, "")
        }
        url = f"{self.settings.tool_api_base}{spec['path']}"
        try:
            with httpx.Client(timeout=self.settings.request_timeout) as client:
                resp = client.request(
                    spec.get("method", "GET"), url, params=query, headers=self._headers()
                )
        except httpx.HTTPError as exc:
            raise DataSourceError(f"请求失败：{exc}") from exc
        if resp.status_code >= 400:
            raise DataSourceError(f"HTTP {resp.status_code}: {resp.text[:160]}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise DataSourceError("接口返回的不是 JSON") from exc

        raw_records = extract_all(body, spec.get("record_path", "$.data[*]"))
        records = []
        for raw in raw_records:
            if not isinstance(raw, dict):
                continue
            record = {}
            for field, path in (spec.get("fields") or {}).items():
                if path.endswith("[*]"):
                    record[field] = extract_all(raw, path)
                else:
                    record[field] = extract_one(raw, path)
            records.append(record)
        if not records:
            raise DataSourceError("按 JSONPath 没有抽取到记录，请检查接口返回结构")
        return records

    def _fetch(self, tool: str, params: dict) -> tuple[list[dict], dict]:
        if self.mode != "http":
            return [], {"source": "mock", "degraded": False, "error": None}
        try:
            return self._fetch_http(tool, params), {"source": "http", "degraded": False, "error": None}
        except DataSourceError as exc:
            log.warning("真实接口 %s 调用失败，降级 mock：%s", tool, exc)
            return [], {"source": "mock", "degraded": True, "error": str(exc)}

    # ---------- 对外数据方法（mock / http 统一返回结构） ----------

    def orders(self, order_id: str | None, phone_last4: str | None) -> tuple[list[dict], dict]:
        if self.mode == "http":
            records, meta = self._fetch("query_order", {"order_id": order_id, "phone_last4": phone_last4})
            if records:
                return [self._normalize_order(r) for r in records], meta
        return mock_data.find_order(order_id, None if order_id else phone_last4), meta_or_mock()

    def logistics(self, order_id: str) -> tuple[dict | None, dict]:
        if self.mode == "http":
            records, meta = self._fetch("query_logistics", {"order_id": order_id})
            if records:
                return records[0], meta
        return mock_data.LOGISTICS.get(order_id.upper()), meta_or_mock()

    def products(self, keyword: str | None, product_id: str | None) -> tuple[list[dict], dict]:
        if self.mode == "http":
            records, meta = self._fetch("query_product", {"keyword": keyword, "product_id": product_id})
            if records:
                return records, meta
        items = list(mock_data.PRODUCTS.values())
        if product_id:
            items = [p for p in items if p["product_id"] == product_id]
        elif keyword:
            items = [p for p in items if keyword in p["name"]]
        return items, meta_or_mock()

    def after_sales(self, order_id: str | None, after_sale_id: str | None) -> tuple[list[dict], dict]:
        if self.mode == "http":
            records, meta = self._fetch(
                "query_after_sale", {"order_id": order_id, "after_sale_id": after_sale_id}
            )
            if records:
                return records, meta
        return self.mock_after_sales(order_id, after_sale_id), meta_or_mock()

    def mock_after_sales(self, order_id: str | None, after_sale_id: str | None) -> list[dict]:
        if after_sale_id:
            record = mock_data.AFTER_SALES.get(after_sale_id.upper())
            return [record] if record else []
        if order_id:
            return [r for r in mock_data.AFTER_SALES.values() if r["order_id"] == order_id]
        return []

    @staticmethod
    def _normalize_order(record: dict) -> dict:
        for field in NUMERIC_FIELDS:
            if field in record and isinstance(record[field], str):
                try:
                    record[field] = float(record[field])
                except ValueError:
                    pass
        record.setdefault("items", [])
        record.setdefault("carrier", "")
        record.setdefault("tracking_no", "")
        record.setdefault("eta", "")
        return record


def meta_or_mock() -> dict:
    return {"source": "mock", "degraded": False, "error": None}
