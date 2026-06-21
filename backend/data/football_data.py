"""football-data.org API client (World Cup fixtures — env key only; never log token)."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

# Diagnostic codes (safe for logs/API)
KEY_MISSING = "KEY_MISSING"
UNAUTHORIZED = "UNAUTHORIZED"
RATE_LIMITED = "RATE_LIMITED"
NETWORK_ERROR = "NETWORK_ERROR"
WC_NOT_AVAILABLE = "WC_NOT_AVAILABLE"
OK = "OK"

HTTP_401_UNAUTHORIZED = "HTTP_401_UNAUTHORIZED"
HTTP_403_FORBIDDEN = "HTTP_403_FORBIDDEN"
HTTP_404_NOT_FOUND = "HTTP_404_NOT_FOUND"
HTTP_429_RATE_LIMITED = "HTTP_429_RATE_LIMITED"
HTTP_400_BAD_REQUEST = "HTTP_400_BAD_REQUEST"
HTTP_5XX_UPSTREAM = "HTTP_5XX_UPSTREAM"
TIMEOUT = "TIMEOUT"
CONNECTION_ERROR = "CONNECTION_ERROR"
JSON_PARSE_ERROR = "JSON_PARSE_ERROR"
UNKNOWN_ERROR = "UNKNOWN_ERROR"

MAX_ERROR_BODY_LEN = 240
_SECRET_PATTERN = re.compile(
    r"(X-Auth-Token|api[_-]?key|token|Bearer|Auth-Token)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FootballDataErrorDetail:
    endpoint_path: str
    http_status: int | None
    category: str
    message: str
    fd_error_code: str | None = None
    fd_message: str | None = None
    likely_cause: str = "unknown"
    params: dict[str, Any] | None = None


class FootballDataRequestError(RuntimeError):
    """Structured football-data.org request failure (message is safe category code)."""

    def __init__(self, detail: FootballDataErrorDetail) -> None:
        self.detail = detail
        super().__init__(detail.category)


def _redact_secrets(text: str) -> str:
    return _SECRET_PATTERN.sub(r"\1=***", text)


def sanitize_fd_response_body(raw: str, *, max_len: int = MAX_ERROR_BODY_LEN) -> str:
    text = _redact_secrets(str(raw).replace("\n", " ").strip())
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


_RATE_LIMIT_WAIT_RE = re.compile(r"wait\s+(\d+)\s+seconds?", re.IGNORECASE)


def parse_rate_limit_wait_seconds(message: str) -> int | None:
    match = _RATE_LIMIT_WAIT_RE.search(message or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def category_from_http_status(status: int) -> str:
    if status == 401:
        return HTTP_401_UNAUTHORIZED
    if status == 403:
        return HTTP_403_FORBIDDEN
    if status == 404:
        return HTTP_404_NOT_FOUND
    if status == 429:
        return HTTP_429_RATE_LIMITED
    if status == 400:
        return HTTP_400_BAD_REQUEST
    if 500 <= status <= 599:
        return HTTP_5XX_UPSTREAM
    return UNKNOWN_ERROR


def infer_likely_cause(category: str, fd_error_code: str | None = None) -> str:
    if category in (HTTP_401_UNAUTHORIZED, KEY_MISSING):
        return "missing_or_invalid_key"
    if category == HTTP_403_FORBIDDEN:
        return "tier_or_permission_issue"
    if category == HTTP_404_NOT_FOUND:
        return "endpoint_unsupported_or_not_found"
    if category in (HTTP_429_RATE_LIMITED, RATE_LIMITED):
        return "rate_limit"
    if category == HTTP_400_BAD_REQUEST:
        return "bad_request_params"
    if category in (TIMEOUT, CONNECTION_ERROR, HTTP_5XX_UPSTREAM):
        return "transient_network_or_upstream"
    if category == JSON_PARSE_ERROR:
        return "unexpected_response_format"
    if fd_error_code:
        return "api_reported_error"
    return "unknown"


def parse_fd_error_fields(payload: Any) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    code = payload.get("errorCode") or payload.get("error")
    message = payload.get("message") or payload.get("errorMessage")
    if code is not None:
        code = str(code)
    if message is not None:
        message = sanitize_fd_response_body(str(message), max_len=120)
    return code, message


def build_error_detail(
    *,
    endpoint_path: str,
    http_status: int | None,
    category: str,
    raw_body: str = "",
    fd_error_code: str | None = None,
    fd_message: str | None = None,
    params: dict[str, Any] | None = None,
) -> FootballDataErrorDetail:
    message = sanitize_fd_response_body(raw_body) if raw_body else category
    if fd_message:
        message = fd_message
    elif fd_error_code and not raw_body:
        message = fd_error_code
    return FootballDataErrorDetail(
        endpoint_path=endpoint_path,
        http_status=http_status,
        category=category,
        message=message,
        fd_error_code=fd_error_code,
        fd_message=fd_message,
        likely_cause=infer_likely_cause(category, fd_error_code),
        params=dict(params) if params else None,
    )


def legacy_error_code(category: str) -> str:
    if category in (HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN):
        return UNAUTHORIZED
    if category in (HTTP_429_RATE_LIMITED,):
        return RATE_LIMITED
    if category in (TIMEOUT, CONNECTION_ERROR):
        return NETWORK_ERROR
    return category


class FootballDataClient:
    """Read-only football-data.org v4 client for WC fixture/status data."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        enabled: bool | None = None,
        timeout: int | None = None,
    ) -> None:
        if api_key is not None:
            self.api_key = api_key.strip()
        else:
            self.api_key = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
        self.base_url = (base_url or config.FOOTBALL_DATA_BASE_URL).rstrip("/")
        self.enabled = (
            config.FOOTBALL_DATA_ENABLED if enabled is None else enabled
        )
        self.timeout = timeout or config.FOOTBALL_DATA_REQUEST_TIMEOUT
        self.last_error_code: str | None = None
        self.last_error_detail: FootballDataErrorDetail | None = None

    @property
    def key_present(self) -> bool:
        return bool(self.api_key)

    @property
    def is_available(self) -> bool:
        return self.enabled and self.key_present

    def _headers(self) -> dict[str, str]:
        return {
            "X-Auth-Token": self.api_key,
            "Accept": "application/json",
        }

    def _set_error(self, detail: FootballDataErrorDetail) -> None:
        self.last_error_detail = detail
        self.last_error_code = legacy_error_code(detail.category)

    def _clear_error(self) -> None:
        self.last_error_code = OK
        self.last_error_detail = None

    def request_raw(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, FootballDataErrorDetail | None]:
        """Low-level GET; returns (payload, error_detail). Never raises."""
        safe_path = path.split("?")[0]
        req_params = dict(params or {})

        if not self.is_available:
            detail = build_error_detail(
                endpoint_path=safe_path,
                http_status=None,
                category=KEY_MISSING,
                params=req_params,
            )
            self._set_error(detail)
            return None, detail

        url = f"{self.base_url}{path}"
        try:
            response = requests.get(
                url,
                headers=self._headers(),
                params=req_params,
                timeout=self.timeout,
            )
        except requests.Timeout:
            detail = build_error_detail(
                endpoint_path=safe_path,
                http_status=None,
                category=TIMEOUT,
                raw_body="request timed out",
                params=req_params,
            )
            self._set_error(detail)
            return None, detail
        except requests.ConnectionError as exc:
            detail = build_error_detail(
                endpoint_path=safe_path,
                http_status=None,
                category=CONNECTION_ERROR,
                raw_body=sanitize_fd_response_body(str(exc)),
                params=req_params,
            )
            self._set_error(detail)
            return None, detail
        except requests.RequestException as exc:
            detail = build_error_detail(
                endpoint_path=safe_path,
                http_status=None,
                category=CONNECTION_ERROR,
                raw_body=sanitize_fd_response_body(str(exc)),
                params=req_params,
            )
            self._set_error(detail)
            return None, detail

        raw_text = response.text or ""
        if response.status_code >= 400:
            fd_code, fd_msg = None, None
            try:
                err_payload = response.json()
                fd_code, fd_msg = parse_fd_error_fields(err_payload)
            except ValueError:
                pass
            category = category_from_http_status(response.status_code)
            detail = build_error_detail(
                endpoint_path=safe_path,
                http_status=response.status_code,
                category=category,
                raw_body=raw_text,
                fd_error_code=fd_code,
                fd_message=fd_msg,
                params=req_params,
            )
            self._set_error(detail)
            return None, detail

        try:
            payload = response.json()
        except ValueError:
            detail = build_error_detail(
                endpoint_path=safe_path,
                http_status=response.status_code,
                category=JSON_PARSE_ERROR,
                raw_body=raw_text,
                params=req_params,
            )
            self._set_error(detail)
            return None, detail

        if not isinstance(payload, dict):
            detail = build_error_detail(
                endpoint_path=safe_path,
                http_status=response.status_code,
                category=JSON_PARSE_ERROR,
                raw_body=raw_text,
                params=req_params,
            )
            self._set_error(detail)
            return None, detail

        self._clear_error()
        return payload, None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload, detail = self.request_raw(path, params)
        if detail is not None:
            raise FootballDataRequestError(detail)
        assert payload is not None
        return payload

    def get_competitions(self) -> list[dict[str, Any]]:
        data = self._get("/competitions")
        return list(data.get("competitions") or [])

    def find_world_cup_competition(self) -> dict[str, Any] | None:
        for comp in self.get_competitions():
            if (comp.get("code") or "").upper() == config.FOOTBALL_DATA_WC_CODE:
                return comp
        self.last_error_code = WC_NOT_AVAILABLE
        return None

    def get_world_cup_matches(self, season: int | None = None) -> list[dict[str, Any]]:
        season = season or config.FOOTBALL_DATA_WC_SEASON
        data = self._get(
            f"/competitions/{config.FOOTBALL_DATA_WC_CODE}/matches",
            params={"season": season},
        )
        return list(data.get("matches") or [])

    def get_world_cup_matches_by_date_range(
        self,
        date_from: str,
        date_to: str,
        *,
        season: int | None = None,
    ) -> list[dict[str, Any]]:
        season = season or config.FOOTBALL_DATA_WC_SEASON
        data = self._get(
            f"/competitions/{config.FOOTBALL_DATA_WC_CODE}/matches",
            params={"season": season, "dateFrom": date_from, "dateTo": date_to},
        )
        return list(data.get("matches") or [])

    def get_competition_teams(
        self,
        competition_code: str | None = None,
        *,
        season: int | None = None,
    ) -> list[dict[str, Any]]:
        code = competition_code or config.FOOTBALL_DATA_WC_CODE
        season = season or config.FOOTBALL_DATA_WC_SEASON
        data = self._get(
            f"/competitions/{code}/teams",
            params={"season": season},
        )
        return list(data.get("teams") or [])

    def get_team_matches(
        self,
        team_id: int,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = "FINISHED",
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
        """Finished (or filtered) matches for a team — Phase 4R.2 recent form."""
        params: dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if limit is not None:
            params["limit"] = limit
        if date_from and date_to:
            params["dateFrom"] = date_from
            params["dateTo"] = date_to
        data = self._get(f"/teams/{team_id}/matches", params=params)
        return list(data.get("matches") or [])
