"""API client for Obi EnergyTracker."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import math
from typing import Any
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientSession
import jwt

_LOGGER = logging.getLogger(__name__)

# API endpoints
LOGIN_URL = "https://www.obi.de/regi/auth/api/public/login"
ENERGY_TRACKING_URL = "https://energy-tracking-backend.prod-eks.dbs.obi.solutions"

POWER_MEASURES = ("power", "active_power", "current_power", "16.7.0")
PROBE_MEASURES = (
    *POWER_MEASURES,
    "voltage",
    "current",
    "energy",
    "negative_energy",
)
POWER_ENDPOINTS = ("live", "current", "status", "meter", "hourly")
POWER_FIELD_ALIASES = {
    "power": {"power", "watt"},
    "active_power": {"activepower"},
    "current_power": {"currentpower"},
    "16.7.0": {"1670"},
}
USER_ANALYSIS_FIELDS = {
    "power",
    "activepower",
    "currentpower",
    "watt",
    "measurement",
    "telemetry",
    "status",
    "live",
    "1670",
    "energy",
    "negativeenergy",
}


class ObiEnergyTrackerAPI:
    """API client for Obi EnergyTracker."""

    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        country: str = "DE",
        bridge_id: str | None = None,
        device_id: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self.session = session
        self.email = email
        self.password = password
        self.country = country
        self.token: str | None = None
        self.account_id: str | None = None
        self.bridge_id = bridge_id
        self.device_id = device_id
        self.last_probe_summary: dict[str, Any] | None = None

    async def async_login(self) -> bool:
        """Authenticate with the Obi EnergyTracker API."""
        try:
            payload = {
                "email": self.email,
                "password": self.password,
                "country": self.country,
            }

            headers = {
                "Accept-Encoding": "gzip",
                "Connection": "Keep-Alive",
                "Content-Type": "application/json",
                "x-app-type": "b2c",
                "x-obi-locale": "de-DE",
                "User-Agent": "heyOBI APP / Android Phone 30",
            }

            async with self.session.post(
                LOGIN_URL, json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    _LOGGER.error(
                        "Login failed with status %d",
                        response.status,
                    )
                    return False

                data = await response.json()
                self.token = data.get("token")

                if not self.token:
                    _LOGGER.error("No token received from login response")
                    return False

                decoded_token = jwt.decode(
                    self.token, options={"verify_signature": False}
                )
                account_id = decoded_token.get("accountId")
                self.account_id = str(account_id) if account_id else None

                _LOGGER.debug("Successfully authenticated with Obi EnergyTracker")
                return True
        except (jwt.DecodeError, OSError, ClientError) as err:
            _LOGGER.error("Login error: %s", err)
            return False

    async def async_get_bridge_info(self) -> dict[str, str] | None:
        """Get bridge and device IDs from user profile."""
        if not self.token:
            return None

        try:
            # Decode JWT to get userId
            decoded_token = jwt.decode(self.token, options={"verify_signature": False})
            user_id = decoded_token.get("accountId")

            if not user_id:
                _LOGGER.error("No accountId found in token")
                return None
            self.account_id = str(user_id)

            url = f"{ENERGY_TRACKING_URL}/users/{user_id}"
            headers = {
                "Accept": "application/vnd.obi.companion.energy-tracking.user.v1+json",
                "Accept-Encoding": "gzip",
                "User-Agent": "app_client",
                "Authorization": f"Bearer {self.token}",
                "Connection": "Keep-Alive",
            }

            async with self.session.get(url, headers=headers) as response:
                body_text = await response.text()
                try:
                    data: Any = json.loads(body_text)
                except json.JSONDecodeError:
                    data = body_text
                _LOGGER.debug(
                    "OBI user GET response: url=%s params=%s status=%s body=%s",
                    url,
                    {},
                    response.status,
                    data,
                )
                if response.status != 200:
                    _LOGGER.error("Failed to get user info: %d", response.status)
                    return None

                if not isinstance(data, dict):
                    _LOGGER.error("User info response is not a JSON object")
                    return None
                self._log_user_response_matches(data)
                bridge = data.get("bridge")
                if not bridge:
                    _LOGGER.error("No bridge found in user info")
                    return None

                self.bridge_id = bridge.get("id")
                sensors = bridge.get("sensors", [])
                if sensors:
                    self.device_id = sensors[0].get("id")

                if not self.bridge_id or not self.device_id:
                    _LOGGER.error("Could not find bridge_id or device_id")
                    return None

                return {
                    "bridge_id": self.bridge_id,
                    "device_id": self.device_id,
                }
        except (jwt.DecodeError, OSError, ClientError) as err:
            _LOGGER.error("Error getting bridge info: %s", err)
            return None

    async def async_get_hourly_data(
        self,
        start_date: datetime | None = None,
        num_days: int = 1,
    ) -> dict[str, Any] | list[Any] | None:
        """Get hourly energy data for multiple days.

        Args:
            start_date: Start date for data retrieval (defaults to today)
            num_days: Number of days to fetch (default 1)

        Returns:
            Dictionary containing hourly energy data
        """
        if not self.token or not self.bridge_id or not self.device_id:
            return None

        try:
            if start_date is None:
                start_date = datetime.now()

            # Format as ISO 8601 datetime with Z suffix for UTC
            # The API expects: start_dateT23:00:00Z/PT{days}H format
            # So we use start_date at 23:00 UTC of previous day for 24-hour window
            duration_start = start_date.replace(
                hour=23, minute=0, second=0, microsecond=0
            )
            duration_hours = num_days * 24

            duration_str = f"{duration_start.isoformat()}Z/PT{duration_hours}H"

            url = (
                f"{ENERGY_TRACKING_URL}/historical-data/"
                f"{self.bridge_id}/{self.device_id}/hourly"
            )

            params = {
                "duration": duration_str,
                "measures": "energy,negative_energy",
            }

            headers = self._get_auth_headers()

            async with self.session.get(
                url, params=params, headers=headers
            ) as response:
                body_text = await response.text()
                try:
                    data: Any = json.loads(body_text)
                except json.JSONDecodeError:
                    data = body_text
                _LOGGER.debug(
                    "OBI hourly GET response: url=%s params=%s status=%s body=%s",
                    url,
                    params,
                    response.status,
                    data,
                )
                if response.status == 200:
                    return data if isinstance(data, (dict, list)) else None
                _LOGGER.error("Failed to get hourly data: %d", response.status)
                return None
        except OSError as err:
            _LOGGER.error("Error getting hourly data: %s", err)
            return None

    async def async_get_meter_data(self) -> dict[str, Any] | list[Any] | None:
        """Get meter reading data (Zählerstand)."""
        if not self.token or not self.bridge_id or not self.device_id:
            return None

        try:
            # Dynamic duration: a 6-hour window ending now
            # Meter readings represent the total state at points in time
            now = datetime.now()
            start_time = now - timedelta(hours=6)
            # Format: 2026-01-18T08:55:11.896Z
            start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            duration_str = f"{start_time_str}/PT6H"

            url = (
                f"{ENERGY_TRACKING_URL}/historical-data/"
                f"{self.bridge_id}/{self.device_id}/meter"
            )

            params = {
                "duration": duration_str,
                "measures": "energy",
            }

            headers = self._get_auth_headers()

            async with self.session.get(
                url, params=params, headers=headers
            ) as response:
                body_text = await response.text()
                try:
                    data: Any = json.loads(body_text)
                except json.JSONDecodeError:
                    data = body_text
                _LOGGER.debug(
                    "OBI meter GET response: url=%s params=%s status=%s body=%s",
                    url,
                    params,
                    response.status,
                    data,
                )
                if response.status == 200:
                    return data if isinstance(data, (dict, list)) else None
                _LOGGER.error("Failed to get meter data: %d", response.status)
                return None
        except OSError as err:
            _LOGGER.error("Error getting meter data: %s", err)
            return None

    def _get_auth_headers(self) -> dict[str, str]:
        """Get headers with authorization token."""
        accept_header = (
            "application/vnd.obi.companion.energy-tracking.historical-record.v1+json"
        )
        return {
            "Accept": accept_header,
            "Accept-Encoding": "gzip",
            "User-Agent": "app_client",
            "Authorization": f"Bearer {self.token}",
            "Connection": "Keep-Alive",
        }

    def _get_debug_auth_headers(self) -> dict[str, str]:
        """Get endpoint-neutral headers with authorization token."""
        return {
            "Accept": "application/json, application/problem+json, */*",
            "Accept-Encoding": "gzip",
            "User-Agent": "app_client",
            "Authorization": f"Bearer {self.token}",
            "Connection": "Keep-Alive",
        }

    @staticmethod
    def _normalise_debug_path(path: str) -> str:
        """Validate a relative API path before joining it to the API base URL."""
        parsed = urlsplit(path)
        if (
            not path.startswith("/")
            or parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Debug path must be a relative path without a query string")
        return parsed.path

    async def async_debug_get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """GET a relative Energy Tracker endpoint and log its complete response.

        This intentionally accepts only relative paths so the integration token can
        never be sent to an arbitrary host.
        """
        safe_path = self._normalise_debug_path(path)
        request_params = dict(params or {})
        url = f"{ENERGY_TRACKING_URL}{safe_path}"

        if not self.token:
            result = {
                "path": safe_path,
                "url": url,
                "params": request_params,
                "status": None,
                "body": None,
                "error": "Not authenticated",
            }
            _LOGGER.debug("OBI debug GET result: %s", result)
            return result

        try:
            async with self.session.get(
                url, params=request_params, headers=self._get_debug_auth_headers()
            ) as response:
                body_text = await response.text()
                try:
                    body: Any = json.loads(body_text)
                except json.JSONDecodeError:
                    body = body_text

                result = {
                    "path": safe_path,
                    "url": str(response.url),
                    "params": request_params,
                    "status": response.status,
                    "body": body,
                    "error": None,
                }
        except (OSError, TypeError, ValueError, ClientError) as err:
            result = {
                "path": safe_path,
                "url": url,
                "params": request_params,
                "status": None,
                "body": None,
                "error": str(err),
            }

        # Deliberately log only the result: it contains no Authorization header.
        _LOGGER.debug("OBI debug GET result: %s", result)
        return result

    @staticmethod
    def _numeric_values_for_measure(payload: Any, measure: str) -> list[float]:
        """Extract numeric values belonging to a measure from nested API data."""
        values: list[float] = []

        def add_value(value: Any) -> None:
            if isinstance(value, bool):
                return
            try:
                number = float(value)
            except (TypeError, ValueError):
                return
            if math.isfinite(number):
                values.append(number)

        def visit(item: Any) -> None:
            if isinstance(item, dict):
                aliases = POWER_FIELD_ALIASES.get(
                    measure, {ObiEnergyTrackerAPI._normalise_field_name(measure)}
                )
                for key, value in item.items():
                    if ObiEnergyTrackerAPI._normalise_field_name(str(key)) in aliases:
                        add_value(value)
                if (
                    ObiEnergyTrackerAPI._normalise_field_name(
                        str(item.get("measure", ""))
                    )
                    in aliases
                ):
                    add_value(item.get("value"))
                for value in item.values():
                    visit(value)
            elif isinstance(item, list):
                for value in item:
                    visit(value)

        visit(payload)
        return values

    @staticmethod
    def _normalise_field_name(name: str) -> str:
        """Compare JSON field names regardless of casing or separators."""
        return "".join(character for character in name.lower() if character.isalnum())

    @classmethod
    def _log_user_response_matches(cls, payload: Any) -> None:
        """Log every requested field in the complete user JSON structure."""
        def child_path(path: str, key: str | int) -> str:
            if isinstance(key, int):
                return f"{path}[{key}]"
            return f"{path}[{key!r}]"

        def visit(item: Any, path: str) -> None:
            if isinstance(item, dict):
                for key, value in item.items():
                    value_path = child_path(path, key)
                    if cls._normalise_field_name(str(key)) in USER_ANALYSIS_FIELDS:
                        _LOGGER.debug(
                            "OBI user JSON field: path=%s value=%s", value_path, value
                        )
                    visit(value, value_path)
            elif isinstance(item, list):
                for index, value in enumerate(item):
                    visit(value, child_path(path, index))

        visit(payload, "$")

    @staticmethod
    def _probe_duration() -> str:
        """Return a short UTC duration accepted by historical-data endpoints."""
        now = datetime.utcnow()
        start = now - timedelta(hours=1)
        start_text = start.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        return f"{start_text}/PT1H"

    async def async_get_power_data(
        self, source: dict[str, Any]
    ) -> float | None:
        """Retrieve the latest value from a previously confirmed power source."""
        measure = source.get("measure")
        if not isinstance(measure, str):
            return None

        path = source.get("path")
        source_params = source.get("params", {})
        params = dict(source_params) if isinstance(source_params, dict) else {}
        if not isinstance(path, str):
            endpoint = source.get("endpoint")
            if (
                not isinstance(endpoint, str)
                or not self.bridge_id
                or not self.device_id
            ):
                return None
            path = f"/historical-data/{self.bridge_id}/{self.device_id}/{endpoint}"
            params = {"measures": measure}
        if path.endswith("/meter") or path.endswith("/hourly"):
            params["duration"] = self._probe_duration()

        result = await self.async_debug_get(path, params)
        if result["status"] != 200:
            return None
        values = self._numeric_values_for_measure(result["body"], measure)
        return values[-1] if values else None

    async def async_probe_power_endpoints(self) -> dict[str, Any]:
        """Probe known OBI endpoints and measures for a live power value."""
        if not self.bridge_id or not self.device_id:
            summary = {
                "results": [],
                "selected_source": None,
                "error": "Bridge or device ID is unavailable",
            }
            self.last_probe_summary = summary
            return summary

        results: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        resources = [
            ("/users/" + self.account_id, "user")
            if self.account_id
            else None,
            ("/bridges", "bridges"),
            (f"/bridges/{self.bridge_id}", "bridge"),
            ("/sensors", "sensors"),
            (f"/sensors/{self.device_id}", "sensor"),
        ]
        for resource in resources:
            if resource is None:
                continue
            path, resource_name = resource
            result = await self.async_debug_get(path)
            results.append(result)
            if resource_name == "user" and result["status"] == 200:
                self._log_user_response_matches(result["body"])
            if result["status"] == 200:
                for measure in POWER_MEASURES:
                    values = self._numeric_values_for_measure(result["body"], measure)
                    if values:
                        candidates.append(
                            {
                                "path": path,
                                "params": {},
                                "endpoint": resource_name,
                                "measure": measure,
                                "value": values[-1],
                            }
                        )
        for endpoint in POWER_ENDPOINTS:
            path = f"/historical-data/{self.bridge_id}/{self.device_id}/{endpoint}"
            for measure in PROBE_MEASURES:
                params: dict[str, Any] = {"measures": measure}
                if endpoint in {"meter", "hourly"}:
                    params["duration"] = self._probe_duration()
                result = await self.async_debug_get(path, params)
                values = self._numeric_values_for_measure(result["body"], measure)
                result["value_found"] = bool(values)
                results.append(result)
                if result["status"] == 200 and measure in POWER_MEASURES and values:
                    candidates.append(
                        {
                            "path": path,
                            "params": params,
                            "endpoint": endpoint,
                            "measure": measure,
                            "value": values[-1],
                        }
                    )

        endpoint_order = {
            "live": 0,
            "current": 1,
            "status": 2,
            "user": 3,
            "bridges": 4,
            "bridge": 5,
            "sensors": 6,
            "sensor": 7,
            "meter": 8,
            "hourly": 9,
        }
        measure_order = {measure: index for index, measure in enumerate(POWER_MEASURES)}
        selected_source = None
        if candidates:
            selected = min(
                candidates,
                key=lambda candidate: (
                    endpoint_order[candidate["endpoint"]],
                    measure_order[candidate["measure"]],
                ),
            )
            selected_source = {
                "path": selected["path"],
                "params": selected["params"],
                "measure": selected["measure"],
            }

        summary = {
            "results": results,
            "selected_source": selected_source,
            "candidate_count": len(candidates),
            "error": None,
        }
        self.last_probe_summary = summary
        return summary
