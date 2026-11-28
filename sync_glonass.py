#!/usr/bin/env python3
"""GLONASSSoft -> Firestore telemetry sync.

Reads mileage and fuel level for the configured vehicles and writes:
- `glonass_vehicles/{vehicleId}` for the app's telemetry panel;
- `gazelle_app/main_data` cars[].odometer / cars[].fuelLevel, matching by name,
  so older clients and direct Firestore readers see the same raw GLONASS data.

The main_data write uses a merge and only touches the matched car fields.

Usage:
    python sync_glonass.py --probe        # print parsed values, no Firestore write
    python sync_glonass.py --dry-run      # fetch + log, no Firestore write
    python sync_glonass.py                # fetch + write telemetry and main_data
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any


LOG = logging.getLogger("glonass-sync")

BASE_URL = os.getenv("GLONASS_BASE_URL", "https://hosting.glonasssoft.ru").rstrip("/")
LOGIN = os.getenv("GLONASS_LOGIN", "")
PASSWORD = os.getenv("GLONASS_PASSWORD", "")
VEHICLE_IDS = [
    int(value)
    for value in os.getenv("GLONASS_VEHICLE_IDS", "").replace(" ", "").split(",")
    if value
]
MILEAGE_FIELD = os.getenv("GLONASS_MILEAGE_FIELD", "mileage")
MILEAGE_DIVISOR = float(os.getenv("GLONASS_MILEAGE_DIVISOR", "1"))
FUEL_SENSOR = os.getenv("GLONASS_FUEL_SENSOR", "Топливо")
TIMEZONE = int(os.getenv("GLONASS_TIMEZONE", "3"))
FIREBASE_CREDENTIALS = os.getenv("FIREBASE_CREDENTIALS", "")
WRITE_MAIN_DATA = os.getenv("GLONASS_WRITE_MAIN_DATA", "1").strip().lower() not in {"0", "false", "no", "off"}


def parse_tank_map(raw: str) -> dict[int, float]:
    result: dict[int, float] = {}
    for item in (raw or "").replace(" ", "").split(","):
        if not item:
            continue
        vehicle_id, _, tank = item.partition(":")
        try:
            result[int(vehicle_id)] = float(tank)
        except (TypeError, ValueError):
            continue
    return result


# Fuel sensor values are litres. For a percent-mode vehicle, also store percent
# using its known tank so the web UI can use the native unit for that car.
FUEL_TANKS = parse_tank_map(os.getenv("GLONASS_FUEL_TANKS", "505725:70"))


def norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def http_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> Any:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, method=method, headers=request_headers)
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"HTTP {error.code} for {url}: {body}") from error
        except urllib.error.URLError as error:
            last_error = RuntimeError(f"Network error for {url}: {error.reason}")
        except TimeoutError as error:
            last_error = RuntimeError(f"Timeout for {url}")
        if attempt == 0:
            time.sleep(1)
    raise last_error or RuntimeError(f"Request failed for {url}")


class GlonassClient:
    def __init__(self, base_url: str, login: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.login = login
        self.password = password
        self.token: str | None = None

    def authenticate(self) -> None:
        if not self.login or not self.password:
            raise RuntimeError("GLONASS_LOGIN / GLONASS_PASSWORD are not set")
        data = http_json(
            "POST",
            f"{self.base_url}/api/v3/auth/login",
            {"login": self.login, "password": self.password},
        )
        token = (data or {}).get("AuthId") or (data or {}).get("authId")
        if not token:
            raise RuntimeError("GLONASS auth response has no AuthId")
        self.token = str(token)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        if not self.token:
            self.authenticate()
        try:
            return http_json(
                "POST",
                f"{self.base_url}{path}",
                payload,
                {"X-Auth": self.token or ""},
            )
        except RuntimeError as error:
            if "HTTP 401" not in str(error):
                raise
            self.authenticate()
            return http_json(
                "POST",
                f"{self.base_url}{path}",
                payload,
                {"X-Auth": self.token or ""},
            )

    def vehicles(self) -> list[dict[str, Any]]:
        data = self.post("/api/v3/vehicles/find", {})
        return data if isinstance(data, list) else (data or {}).get("items", [])

    def mileage(
        self,
        vehicle_ids: list[int],
        from_dt: datetime,
        to_dt: datetime,
        sampling: int = 86400,
    ) -> list[dict[str, Any]]:
        data = self.post(
            "/api/v3/vehicles/mileageAndMotohours",
            {
                "sampling": sampling,
                "vehicleIds": vehicle_ids,
                "from": iso_utc(from_dt),
                "to": iso_utc(to_dt),
                "timezone": TIMEZONE,
            },
        )
        return data if isinstance(data, list) else []

    def mileage_totals(self, vehicle_ids: list[int], from_dt: datetime, to_dt: datetime) -> dict[int, float]:
        """Sum mileage in <=90-day windows because the API rejects longer ranges."""
        totals = {vehicle_id: 0.0 for vehicle_id in vehicle_ids}
        cursor = from_dt
        while cursor < to_dt:
            end = min(cursor + timedelta(days=90), to_dt)
            rows = self.mileage(vehicle_ids, cursor, end, sampling=86400)
            for row in rows:
                try:
                    vehicle_id = int(row.get("vehicleId"))
                except (TypeError, ValueError):
                    continue
                if vehicle_id not in totals:
                    continue
                for period in row.get("periods") or []:
                    try:
                        totals[vehicle_id] += float(period.get("mileage") or 0)
                    except (TypeError, ValueError):
                        continue
            cursor = end
            if cursor < to_dt:
                time.sleep(1)  # GLONASS limit: one request per second
        return totals

    def mileage_total(self, vehicle_id: int, from_dt: datetime, to_dt: datetime) -> float:
        return self.mileage_totals([vehicle_id], from_dt, to_dt).get(vehicle_id, 0.0)

    def last_data(self, vehicle_ids: list[int]) -> list[dict[str, Any]]:
        # The wiki email says vehicleIds, but the live endpoint accepts
        # vehiclesIds; vehicleIds returns HTTP 400. Try both for compatibility.
        last_error: Exception | None = None
        for key in ("vehiclesIds", "vehicleIds"):
            try:
                data = self.post(
                    "/api/v3/vehicles/getlastdata",
                    {key: vehicle_ids, "includeSensors": True},
                )
                return data if isinstance(data, list) else []
            except RuntimeError as error:
                last_error = error
                if "HTTP 400" not in str(error):
                    raise
        raise last_error or RuntimeError("getlastdata failed")


def parse_vehicles(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in rows or []:
        try:
            vehicle_id = int(row.get("vehicleId"))
        except (TypeError, ValueError):
            continue
        result[vehicle_id] = {
            "name": str(row.get("name") or "").strip(),
            "vehicleNumber": str(row.get("vehicleNumber") or "").strip(),
            "vehicleGuid": str(row.get("vehicleGuid") or "").strip(),
            "createdAt": str(row.get("createdAt") or "").strip(),
        }
    return result


def parse_mileage(
    rows: list[dict[str, Any]],
    field: str = MILEAGE_FIELD,
    divisor: float = MILEAGE_DIVISOR,
) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for row in rows or []:
        try:
            vehicle_id = int(row.get("vehicleId"))
        except (TypeError, ValueError):
            continue
        periods = [item for item in (row.get("periods") or []) if item.get(field) is not None]
        if not periods:
            continue
        raw = sum(float(item.get(field) or 0) for item in periods)
        mileage = raw / divisor if divisor else raw
        result[vehicle_id] = {
            "mileage": round(mileage, 2),
            "raw": raw,
            "field": field,
            "periodStart": periods[0].get("start"),
            "periodEnd": periods[-1].get("end"),
        }
    return result


def parse_fuel(rows: list[dict[str, Any]], sensor_name: str = FUEL_SENSOR) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    wanted = norm(sensor_name)
    for row in rows or []:
        try:
            vehicle_id = int(row.get("vehicleId"))
        except (TypeError, ValueError):
            continue
        sensors = row.get("sensors") or []
        candidates = [
            item
            for item in sensors
            if "топлив" in norm(item.get("name"))
            or "fuel" in norm(item.get("name"))
            or "flex" in norm(item.get("name"))
        ]
        sensor = next((item for item in candidates if norm(item.get("name")) == wanted), None)
        if sensor is None:
            sensor = next(
                (
                    item
                    for item in candidates
                    if "температур" not in norm(item.get("name"))
                    and "temp" not in norm(item.get("name"))
                ),
                None,
            )
        if sensor is None:
            continue
        raw_value = sensor.get("rawValue")
        if raw_value is None:
            raw_value = sensor.get("displayValue")
        try:
            fuel_level = float(str(raw_value).replace(",", ".").split()[0])
        except (TypeError, ValueError, IndexError):
            continue
        result[vehicle_id] = {
            "fuelLevel": round(fuel_level, 2),
            "fuelUnit": str(sensor.get("unit") or "л").strip(),
            "sensorName": sensor.get("name"),
            "rawValue": sensor.get("rawValue"),
            "vehicleNumber": str(row.get("vehicleNumber") or "").strip(),
        }
    return result


def build_records(
    vehicle_ids: list[int],
    vehicles: dict[int, dict[str, Any]],
    mileage: dict[int, dict[str, Any]],
    fuel: dict[int, dict[str, Any]],
    plate_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    plate_map = plate_map or {}
    records: list[dict[str, Any]] = []
    for vehicle_id in vehicle_ids:
        vehicle = vehicles.get(vehicle_id, {})
        mileage_row = mileage.get(vehicle_id, {})
        fuel_row = fuel.get(vehicle_id, {})
        if not mileage_row and not fuel_row:
            continue
        record: dict[str, Any] = {
            "vehicleId": vehicle_id,
            "name": vehicle.get("name") or "",
            "plate": plate_map.get(str(vehicle_id)) or vehicle.get("vehicleNumber") or fuel_row.get("vehicleNumber") or "",
            "vehicleNumber": vehicle.get("vehicleNumber") or fuel_row.get("vehicleNumber") or "",
            "source": "glonasssoft",
        }
        if mileage_row:
            record["dailyMileage"] = mileage_row["mileage"]
            record["dailyMileageRaw"] = mileage_row["raw"]
            record["mileageField"] = mileage_row["field"]
            record["mileageFrom"] = mileage_row["periodStart"]
            record["mileageTo"] = mileage_row["periodEnd"]
        if fuel_row:
            record["fuelLevel"] = fuel_row["fuelLevel"]
            record["fuelUnit"] = fuel_row["fuelUnit"]
            record["fuelSensor"] = fuel_row["sensorName"]
            tank = FUEL_TANKS.get(vehicle_id)
            if tank and tank > 0:
                unit = str(fuel_row.get("fuelUnit") or "").lower()
                percent = fuel_row["fuelLevel"] if "%" in unit else (fuel_row["fuelLevel"] / tank) * 100
                record["fuelPercent"] = round(percent, 2)
                record["fuelTank"] = tank
        records.append(record)
    return records


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def update_main_data(
    db: Any,
    firestore_module: Any,
    records: list[dict[str, Any]],
) -> list[str]:
    """Merge telemetry into gazelle_app/main_data cars by name.

    Firestore stores cars as an array, so the whole array is rewritten in one
    transaction. Other document fields and unmatched cars are left untouched.
    """
    if not records:
        return []
    ref = db.collection("gazelle_app").document("main_data")
    by_name = {norm(record.get("name")): record for record in records if norm(record.get("name"))}
    by_plate = {
        norm(record.get("plate") or record.get("vehicleNumber")): record
        for record in records
        if norm(record.get("plate") or record.get("vehicleNumber"))
    }

    @firestore_module.transactional
    def apply(transaction: Any) -> list[str]:
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            LOG.warning("main_data document does not exist; telemetry written only")
            return []
        data = snapshot.to_dict() or {}
        cars = data.get("cars")
        if not isinstance(cars, list):
            LOG.warning("main_data has no cars array; telemetry written only")
            return []
        updated: list[str] = []
        for car in cars:
            if not isinstance(car, dict):
                continue
            record = by_name.get(norm(car.get("name"))) or by_plate.get(norm(car.get("plate")))
            if not record:
                continue
            changed = False
            if record.get("odometer") is not None:
                car["odometer"] = round(float(record["odometer"]), 2)
                changed = True
            if record.get("fuelLevel") is not None:
                car["fuelLevel"] = round(float(record["fuelLevel"]), 2)
                changed = True
            if changed:
                updated.append(str(car.get("name") or car.get("id") or "?"))
        if updated:
            transaction.set(ref, {"cars": cars}, merge=True)
        return updated

    return apply(db.transaction())


def write_firestore(
    records: list[dict[str, Any]],
    errors: list[str],
    duration_ms: int,
    client: GlonassClient,
    vehicles: dict[int, dict[str, Any]],
) -> None:
    if not FIREBASE_CREDENTIALS:
        raise RuntimeError("FIREBASE_CREDENTIALS is not set")
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError as error:
        raise RuntimeError("firebase-admin is not installed; run pip install -r requirements.txt") from error

    raw = FIREBASE_CREDENTIALS.strip()
    if raw.startswith("{"):
        credential = credentials.Certificate(json.loads(raw))
    else:
        credential = credentials.Certificate(raw)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credential)
    db = firestore.client()
    now = datetime.now(timezone.utc)
    batch = db.batch()
    pending: list[tuple[dict[str, Any], Any, dict[str, Any]]] = []
    first_sync_ids: list[int] = []
    first_sync_start = now
    for record in records:
        vehicle_id = int(record["vehicleId"])
        ref = db.collection("glonass_vehicles").document(str(vehicle_id))
        existing = ref.get().to_dict() or {}
        synced_at = parse_dt(existing.get("mileageSyncedAt"))
        pending.append((record, ref, existing))
        if synced_at is None:
            created_at = parse_dt(vehicles.get(vehicle_id, {}).get("createdAt")) or (now - timedelta(days=90))
            first_sync_ids.append(vehicle_id)
            first_sync_start = min(first_sync_start, created_at)
        else:
            since = max(synced_at, now - timedelta(days=93))
            record["odometer"] = round(float(existing.get("odometer") or 0) + client.mileage_total(vehicle_id, since, now), 2)
    first_totals = client.mileage_totals(first_sync_ids, first_sync_start, now) if first_sync_ids else {}
    for record, ref, existing in pending:
        vehicle_id = int(record["vehicleId"])
        if "odometer" not in record:
            record["odometer"] = round(first_totals.get(vehicle_id, 0.0), 2)
        record["mileageSyncedAt"] = iso_utc(now)
        batch.set(ref, {**record, "updatedAt": firestore.SERVER_TIMESTAMP}, merge=True)
    batch.commit()
    db.collection("glonass_sync").document("status").set(
        {
            "lastRun": firestore.SERVER_TIMESTAMP,
            "ok": not errors,
            "vehicles": len(records),
            "errors": errors[:20],
            "durationMs": duration_ms,
            "source": "glonasssoft",
        },
        merge=True,
    )
    if WRITE_MAIN_DATA:
        updated = update_main_data(db, firestore, records)
        LOG.info("Updated main_data cars: %s", ", ".join(updated) if updated else "none")


def run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    client = GlonassClient(BASE_URL, LOGIN, PASSWORD)
    client.authenticate()
    LOG.info("Authenticated in GLONASSSoft")

    vehicles_rows = client.vehicles()
    vehicles = parse_vehicles(vehicles_rows)
    vehicle_ids = args.vehicle_id or VEHICLE_IDS or sorted(vehicles)
    if not vehicle_ids:
        raise RuntimeError("No vehicle IDs configured and /vehicles/find returned nothing")

    now = datetime.now(timezone.utc)
    local_tz = timezone(timedelta(hours=TIMEZONE))
    day_start = now.astimezone(local_tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    mileage_rows = client.mileage(vehicle_ids, day_start, now, sampling=86400)
    fuel_rows = client.last_data(vehicle_ids)
    mileage = parse_mileage(mileage_rows, MILEAGE_FIELD, MILEAGE_DIVISOR)
    fuel = parse_fuel(fuel_rows, FUEL_SENSOR)
    for vehicle_id in vehicle_ids:
        if vehicle_id not in mileage:
            # An idle vehicle legitimately has no mileage periods since 00:00.
            mileage[vehicle_id] = {
                "mileage": 0.0,
                "raw": 0.0,
                "field": MILEAGE_FIELD,
                "periodStart": iso_utc(day_start),
                "periodEnd": iso_utc(now),
            }
            LOG.warning("%s: no mileage period since day start; using 0", vehicle_id)
    plate_map = json.loads(os.getenv("GLONASS_VEHICLE_MAP", "{}") or "{}")
    records = build_records(vehicle_ids, vehicles, mileage, fuel, plate_map)

    errors: list[str] = []
    for vehicle_id in vehicle_ids:
        if vehicle_id not in fuel:
            errors.append(f"{vehicle_id}: no fuel sensor '{FUEL_SENSOR}'")
    for record in records:
        LOG.info(
            "vehicle=%s plate=%s dailyMileage=%s fuel=%s",
            record["vehicleId"],
            record.get("plate") or "-",
            record.get("dailyMileage", "-"),
            record.get("fuelLevel", "-"),
        )
    for error in errors:
        LOG.warning(error)

    if args.probe:
        print(
            json.dumps(
                {
                    "vehicles": vehicles,
                    "mileage": mileage,
                    "fuel": fuel,
                    "records": records,
                    "errors": errors,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.dry_run:
        LOG.info("Dry run: Firestore was not changed")
        return 0

    write_firestore(records, errors, int((time.monotonic() - started) * 1000), client, vehicles)
    LOG.info("Wrote %s telemetry documents", len(records))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync GLONASSSoft mileage/fuel to Firestore")
    parser.add_argument("--probe", action="store_true", help="print parsed values and exit")
    parser.add_argument("--dry-run", action="store_true", help="fetch but do not write Firestore")
    parser.add_argument("--vehicle-id", type=int, action="append", help="vehicle ID (repeatable)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run(args)
    except Exception as error:  # noqa: BLE001
        LOG.error("Sync failed: %s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
