"""HTTP-клієнт до Turso Database.

Turso — це libSQL (fork SQLite) з HTTP API.
API doc: https://docs.turso.tech/api-reference
"""

from __future__ import annotations

import logging
from typing import Any

from curl_cffi import requests as cffi_requests

log = logging.getLogger(__name__)


class TursoError(Exception):
    """Помилка запиту до Turso."""


class TursoClient:
    """HTTP-клієнт до Turso."""

    def __init__(self, url: str, token: str, *, timeout: int = 25) -> None:
        if not url or not token:
            raise ValueError("Turso URL і token обов'язкові")

        self._base_url = url.strip().replace("libsql://", "https://")
        self._token = token.strip()
        self._timeout = timeout

    # ─────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────

    def execute(
        self,
        sql: str,
        params: list[Any] | None = None,
    ) -> list[list[Any]]:
        """Виконати SELECT. Повертає список рядків (кожен — список значень)."""
        result = self._pipeline(sql, params, return_rows=True)
        if result is None or isinstance(result, int):
            return []
        return result

    def execute_non_query(
        self,
        sql: str,
        params: list[Any] | None = None,
    ) -> int:
        """Виконати INSERT/UPDATE/DELETE. Повертає affected_row_count."""
        result = self._pipeline(sql, params, return_rows=False)
        if result is None:
            return 0
        if isinstance(result, list):
            return 0
        return result

    # ─────────────────────────────────────────────────────
    # Внутрішнє
    # ─────────────────────────────────────────────────────

    def _pipeline(
        self,
        sql: str,
        params: list[Any] | None,
        *,
        return_rows: bool,
    ) -> list[list[Any]] | int | None:
        """Виконує один запит через Turso /v2/pipeline."""
        stmt: dict[str, Any] = {"sql": sql}

        if params:
            stmt["args"] = [self._encode_arg(p) for p in params]

        payload = {"requests": [{"type": "execute", "stmt": stmt}]}

        try:
            response = cffi_requests.post(
                f"{self._base_url}/v2/pipeline",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
        except Exception as e:
            log.exception("Turso HTTP помилка: %s", e)
            raise TursoError(f"HTTP помилка: {e}") from e

        if response.status_code != 200:
            log.error("Turso HTTP %d: %s", response.status_code, response.text[:200])
            raise TursoError(f"HTTP {response.status_code}")

        try:
            data = response.json()
        except Exception as e:
            raise TursoError(f"Неправильний JSON: {e}") from e

        results = data.get("results", [])
        if not results:
            return [] if return_rows else 0

        result = results[0]

        if result.get("type") == "error":
            err = result.get("error", {})
            log.error("Turso SQL помилка: %s", err)
            raise TursoError(f"SQL: {err}")

        response_obj = result.get("response", {})
        if response_obj.get("type") != "execute":
            return [] if return_rows else 0

        inner = response_obj.get("result", {})

        if return_rows:
            raw_rows = inner.get("rows", [])
            return [[cell.get("value") for cell in row] for row in raw_rows]

        return int(inner.get("affected_row_count", 0))

    @staticmethod
    def _encode_arg(value: Any) -> dict[str, Any]:
        """Конвертує Python-значення у Turso-формат."""
        if value is None:
            return {"type": "null"}
        if isinstance(value, bool):
            return {"type": "integer", "value": "1" if value else "0"}
        if isinstance(value, int):
            return {"type": "integer", "value": str(value)}
        if isinstance(value, float):
            # Turso не має типу "float" — передаємо як text,
            # SQLite через type affinity збереже у REAL
            return {"type": "text", "value": str(value)}
        return {"type": "text", "value": str(value)}
