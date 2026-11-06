from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .config import resolve_config_path
from .models import CatalogRecord, Component, normalize_name


class CatalogError(RuntimeError):
    pass


class CatalogAdapter(ABC):
    @abstractmethod
    def find(self, component: Component) -> list[CatalogRecord]:
        raise NotImplementedError


class FileCatalogAdapter(CatalogAdapter):
    def __init__(self, path: Path):
        if not path.exists():
            raise CatalogError(f"Catalog file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.records = _records_from_response(data)

    def find(self, component: Component) -> list[CatalogRecord]:
        return _match_records(self.records, component)


class ApiCatalogAdapter(CatalogAdapter):
    def __init__(self, config: dict[str, Any]):
        self.base_url = str(config.get("base_url", "")).rstrip("/")
        if not self.base_url:
            raise CatalogError("catalog.base_url is required for API mode.")
        self.timeout = int(config.get("timeout_seconds", 20))
        self.token = _token(config)
        self.verify_tls = bool(config.get("verify_tls", True))
        self.query_parameters = config.get(
            "query_parameters",
            {"name": "name", "ecosystem": "ecosystem", "version": "version"},
        )

    def find(self, component: Component) -> list[CatalogRecord]:
        values = {
            "name": component.name,
            "ecosystem": component.ecosystem,
            "version": component.version or "",
        }
        params = {
            parameter_name: values[field_name]
            for field_name, parameter_name in self.query_parameters.items()
            if field_name in values and values[field_name]
        }
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        response = _http_get(url, self.token, self.timeout, self.verify_tls)
        try:
            data = json.loads(response)
        except json.JSONDecodeError as exc:
            raise CatalogError(f"SCAS API did not return JSON for {component.name}.") from exc
        return _match_records(_records_from_response(data), component)


class ScasTokenProvider:
    """Exchange an SCAS refresh token for a short-lived access token."""

    def __init__(self, config: dict[str, Any]):
        self.refresh_url = str(
            config.get(
                "refresh_url",
                "https://scas.internal.ericsson.com/registry/auth/token/refresh",
            )
        )
        self.refresh_token_env = str(
            config.get("refresh_token_env", "SCAS_REFRESH_TOKEN")
        )
        self.timeout = int(config.get("timeout_seconds", 20))
        self.verify_tls = bool(config.get("verify_tls", True))
        self._access_token: str | None = None
        self._expires_at = 0.0

    def access_token(self, force_refresh: bool = False) -> str:
        if (
            not force_refresh
            and self._access_token
            and time.monotonic() < self._expires_at
        ):
            return self._access_token

        refresh_token = os.environ.get(self.refresh_token_env)
        if not refresh_token:
            raise CatalogError(
                f"SCAS refresh token is not set. Define environment variable "
                f"{self.refresh_token_env} before starting Kiro."
            )

        body = urllib.parse.urlencode({"refresh_token": refresh_token}).encode("utf-8")
        request = urllib.request.Request(
            self.refresh_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=_ssl_context(self.verify_tls),
            ) as response:
                payload = json.loads(
                    response.read().decode(
                        response.headers.get_content_charset() or "utf-8"
                    )
                )
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise CatalogError(
                f"SCAS token refresh failed with HTTP {code}."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CatalogError(f"SCAS token refresh request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise CatalogError("SCAS token refresh did not return valid JSON.") from exc

        access_token = payload.get("access_token") if isinstance(payload, dict) else None
        if not access_token:
            raise CatalogError(
                "SCAS token refresh response does not contain access_token."
            )
        try:
            expires_in = max(60, int(payload.get("expires_in", 600)))
        except (TypeError, ValueError):
            expires_in = 600
        self._access_token = str(access_token)
        self._expires_at = time.monotonic() + max(30, expires_in - 30)
        return self._access_token


class ScasCatalogAdapter(CatalogAdapter):
    """SCAS Search 3PP adapter for Ordering Service component search."""

    def __init__(self, config: dict[str, Any]):
        self.base_url = str(
            config.get("base_url", "https://scas.internal.ericsson.com/ordering")
        ).rstrip("/")
        self.search_path = "/" + str(
            config.get("search_path", "components/search")
        ).lstrip("/")
        self.size = max(1, min(int(config.get("size", 500)), 5000))
        self.timeout = int(config.get("timeout_seconds", 20))
        self.verify_tls = bool(config.get("verify_tls", True))
        self.name_operator = str(config.get("name_operator", "likei"))
        self.version_operator = str(config.get("version_operator", "NTXEQ"))
        self.name_match = str(config.get("name_match", "contains")).lower()
        self.version_fallback = bool(config.get("version_fallback", True))
        self.maven_coordinate_fallback = bool(
            config.get("maven_coordinate_fallback", True)
        )
        self.token_provider = ScasTokenProvider(config)

    def find(self, component: Component) -> list[CatalogRecord]:
        for search_name, stage, exact_name in self._name_candidates(component):
            name_filter = self._name_filter(search_name, exact=exact_name)
            name_filters = [
                f"compName,{self.name_operator},{name_filter}"
            ]
            filters = list(name_filters)
            if component.version:
                filters.append(
                    f"compVersion,{self.version_operator},{component.version}"
                )

            records = _match_scas_records(self._search(filters), search_name)
            if records:
                return _mark_search_match(records, search_name, stage, exact_name)

            if component.version and self.version_fallback:
                # Name-only fallback distinguishes a version mismatch from a
                # component name that is not registered at this search stage.
                records = _match_scas_records(
                    self._search(name_filters), search_name
                )
                if records:
                    return _mark_search_match(
                        records, search_name, stage, exact_name
                    )
        return []

    def _name_candidates(
        self, component: Component
    ) -> list[tuple[str, str, bool]]:
        candidates = [(component.name, "full-name", False)]
        if (
            self.maven_coordinate_fallback
            and component.ecosystem.lower() == "maven"
            and ":" in component.name
        ):
            group = component.name.split(":", 1)[0].strip()
            library = group.rsplit(".", 1)[-1].strip()
            if group and normalize_name(group) != normalize_name(component.name):
                candidates.append((group, "maven-group", False))
            if (
                library
                and normalize_name(library) != normalize_name(group)
                and all(
                    normalize_name(library) != normalize_name(value[0])
                    for value in candidates
                )
            ):
                # The final query deliberately has no wildcard: for
                # com.itextpdf:io, search the exact library name "itextpdf".
                candidates.append((library, "maven-library-exact", True))
                # If the exact leaf is absent, allow a final partial lookup.
                # Its result is marked for manual review by the policy engine.
                candidates.append((library, "maven-library-partial", False))
        return candidates

    def _name_filter(self, name: str, exact: bool = False) -> str:
        if exact or self.name_match == "exact":
            return name
        if self.name_match == "starts_with":
            return f"{name}*"
        return f"*{name}*"

    def _search(
        self, filters: list[str], retry_after_unauthorized: bool = True
    ) -> list[CatalogRecord]:
        query = urllib.parse.urlencode(
            {"size": self.size, "filter": filters}, doseq=True
        )
        url = f"{self.base_url}{self.search_path}?{query}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {self.token_provider.access_token()}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=_ssl_context(self.verify_tls),
            ) as response:
                data = json.loads(
                    response.read().decode(
                        response.headers.get_content_charset() or "utf-8"
                    )
                )
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if code == 401 and retry_after_unauthorized:
                self.token_provider.access_token(force_refresh=True)
                return self._search(filters, retry_after_unauthorized=False)
            raise CatalogError(
                f"SCAS Search 3PP failed with HTTP {code}."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CatalogError(f"SCAS Search 3PP request failed: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise CatalogError(
                "SCAS Search 3PP did not return valid JSON."
            ) from exc
        return _records_from_response(data, default_status="available")


class HtmlCatalogAdapter(CatalogAdapter):
    def __init__(self, config: dict[str, Any]):
        self.url_template = config.get("url_template")
        if not self.url_template:
            raise CatalogError("catalog.url_template is required for HTML mode.")
        self.timeout = int(config.get("timeout_seconds", 20))
        self.token = _token(config)
        self.verify_tls = bool(config.get("verify_tls", True))

    def find(self, component: Component) -> list[CatalogRecord]:
        url = self.url_template.format(
            name=urllib.parse.quote(component.name),
            ecosystem=urllib.parse.quote(component.ecosystem),
            version=urllib.parse.quote(component.version or ""),
        )
        html = _http_get(url, self.token, self.timeout, self.verify_tls)
        parser = TableParser()
        parser.feed(html)
        records: list[CatalogRecord] = []
        for table in parser.tables:
            if len(table) < 2:
                continue
            headings = [normalize_name(cell) for cell in table[0]]
            for row in table[1:]:
                record = {headings[index]: value for index, value in enumerate(row) if index < len(headings)}
                records.append(_record_from_dict(record))
        return _match_records(records, component)


def build_catalog(config: dict[str, Any]) -> CatalogAdapter:
    catalog_config = config.get("catalog", {})
    mode = str(catalog_config.get("mode", "file")).lower()
    if mode == "file":
        path = resolve_config_path(config, catalog_config.get("path", "sample-scss-catalog.json"))
        return FileCatalogAdapter(path)
    if mode == "api":
        return ApiCatalogAdapter(catalog_config)
    if mode == "scas":
        return ScasCatalogAdapter(catalog_config)
    if mode == "html":
        return HtmlCatalogAdapter(catalog_config)
    raise CatalogError(f"Unsupported catalog mode: {mode}")


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


def _http_get(url: str, token: str | None, timeout: int, verify_tls: bool) -> str:
    headers = {"Accept": "application/json, text/html"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(
            request, timeout=timeout, context=_ssl_context(verify_tls)
        ) as response:
            return response.read().decode(response.headers.get_content_charset() or "utf-8")
    except Exception as exc:
        raise CatalogError(f"SCAS request failed for {url}: {exc}") from exc


def _token(config: dict[str, Any]) -> str | None:
    token_environment = config.get("token_env")
    return os.environ.get(token_environment) if token_environment else None


def _records_from_response(
    data: Any, default_status: str = "unknown"
) -> list[CatalogRecord]:
    if isinstance(data, dict):
        for key in ("content", "items", "results", "components", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
            if isinstance(data.get(key), dict):
                return _records_from_response(data[key], default_status)
        else:
            data = [data]
    if not isinstance(data, list):
        raise CatalogError("SCAS catalog response must contain a list of records.")
    return [
        _record_from_dict(item, default_status)
        for item in data
        if isinstance(item, dict)
    ]


def _record_from_dict(
    item: dict[str, Any], default_status: str = "unknown"
) -> CatalogRecord:
    normalized = {normalize_name(str(key)): value for key, value in item.items()}

    def value(*names: str) -> str | None:
        for name in names:
            candidate = normalized.get(normalize_name(name))
            if candidate is not None:
                return str(candidate)
        return None

    return CatalogRecord(
        name=value(
            "name", "framework", "component", "technology", "compName"
        )
        or "",
        ecosystem=value("ecosystem", "package_manager", "type"),
        version=value(
            "version", "approved_version", "available_version", "compVersion"
        ),
        status=value(
            "status",
            "approval_status",
            "state",
            "rag",
            "request3ppStatus",
        )
        or default_status,
        recommended_version=value("recommended_version", "target_version", "latest_version"),
        support_until=value("support_until", "eol_date", "end_of_support"),
        url=value("url", "details_url", "link", "compDownloadUrl"),
        raw=item,
    )


def _match_records(records: list[CatalogRecord], component: Component) -> list[CatalogRecord]:
    name = normalize_name(component.name)
    matches = [
        record
        for record in records
        if normalize_name(record.name) == name
        and (
            not record.ecosystem
            or normalize_name(record.ecosystem) == normalize_name(component.ecosystem)
        )
    ]
    return matches


def _match_scas_records(
    records: list[CatalogRecord], search_name: str
) -> list[CatalogRecord]:
    target = normalize_name(search_name)
    exact: list[CatalogRecord] = []
    fuzzy: list[CatalogRecord] = []
    for record in records:
        primary_name = record.name.split(",", 1)[0].split(" - ", 1)[0].strip()
        normalized_primary = normalize_name(primary_name)
        if normalized_primary == target:
            exact.append(record)
        elif target and (
            normalized_primary.startswith(target)
            or target.startswith(normalized_primary)
            or target in normalized_primary
            or normalized_primary in target
        ):
            # A fuzzy SCAS name match must be reviewed rather than treated as an
            # exact approved component.
            if record.status.lower() in {"available", "approved", "active", "green"}:
                record.status = "review"
            fuzzy.append(record)
    return exact or fuzzy


def _mark_search_match(
    records: list[CatalogRecord],
    search_name: str,
    stage: str,
    exact_name: bool,
) -> list[CatalogRecord]:
    for record in records:
        record.raw = dict(record.raw)
        record.raw["_governance_search_match"] = {
            "search_name": search_name,
            "stage": stage,
            "exact_name_query": exact_name,
        }
    return records


def _ssl_context(verify_tls: bool) -> ssl.SSLContext | None:
    return None if verify_tls else ssl._create_unverified_context()
