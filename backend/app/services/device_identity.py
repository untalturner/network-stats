"""Shared identity resolution for discovered and enrolled network devices."""

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Device


@dataclass(frozen=True)
class DeviceIdentityResolution:
    device: Device | None = None
    conflict: bool = False
    reason: str | None = None
    matched_by: tuple[str, ...] = ()


def normalize_mac_address(value: str | None) -> str | None:
    """Normalize common MAC formats to lowercase colon-separated notation."""
    if not value:
        return None

    compact = re.sub(r"[:.\-]", "", value.strip().lower())
    if re.fullmatch(r"[0-9a-f]{12}", compact) is None:
        return None

    return ":".join(compact[index:index + 2] for index in range(0, 12, 2))


def normalize_hostname(value: str | None) -> str | None:
    """Normalize hostnames for matching without removing meaningful suffixes."""
    if not value:
        return None

    hostname = value.strip().rstrip(".").casefold()
    return hostname or None


def resolve_device_identity(
    db: Session,
    *,
    ip_address: str,
    mac_address: str | None,
    hostname: str | None,
) -> DeviceIdentityResolution:
    """Resolve an observation only when all matching identity evidence agrees."""
    normalized_mac = normalize_mac_address(mac_address)
    normalized_hostname = normalize_hostname(hostname)

    conditions = [Device.ip_address == ip_address]
    if normalized_mac:
        compact_mac = normalized_mac.replace(":", "")
        mac_variants = {
            normalized_mac,
            normalized_mac.replace(":", "-"),
            compact_mac,
            ".".join(compact_mac[index:index + 4] for index in range(0, 12, 4)),
        }
        conditions.append(func.lower(Device.mac_address).in_(mac_variants))

    if normalized_hostname:
        conditions.append(
            func.lower(Device.hostname).in_(
                (normalized_hostname, f"{normalized_hostname}.")
            )
        )

    candidates = db.scalars(
        select(Device).where(or_(*conditions)).order_by(Device.id)
    ).unique().all()

    matches = {
        "mac": [
            device for device in candidates
            if normalized_mac
            and normalize_mac_address(device.mac_address) == normalized_mac
        ],
        "hostname": [
            device for device in candidates
            if normalized_hostname
            and normalize_hostname(device.hostname) == normalized_hostname
        ],
        "ip": [
            device for device in candidates
            if device.ip_address == ip_address
        ],
    }

    for identifier, devices in matches.items():
        if len(devices) > 1:
            return DeviceIdentityResolution(
                conflict=True,
                reason=f"Multiple registered devices match the discovered {identifier}.",
            )

    candidate_ids = {
        device.id
        for devices in matches.values()
        for device in devices
    }
    if len(candidate_ids) > 1:
        return DeviceIdentityResolution(
            conflict=True,
            reason=(
                "The discovered identifiers match different registered devices. "
                "Resolve the device records before linking them."
            ),
        )

    if not candidate_ids:
        return DeviceIdentityResolution()

    device = next(
        device
        for devices in matches.values()
        for device in devices
        if device.id in candidate_ids
    )

    stored_mac = normalize_mac_address(device.mac_address)
    if normalized_mac and stored_mac and normalized_mac != stored_mac:
        return DeviceIdentityResolution(
            conflict=True,
            reason=(
                "The discovered MAC address conflicts with the known MAC "
                "address of the registered device."
            ),
        )

    matched_by = tuple(
        identifier for identifier, devices in matches.items() if devices
    )
    return DeviceIdentityResolution(device=device, matched_by=matched_by)


def update_device_observation(
    device: Device,
    *,
    ip_address: str,
    mac_address: str | None,
    hostname: str | None,
    observed_at: datetime,
) -> bool:
    """Update current attributes without overwriting newer or conflicting data."""
    if device.last_seen_at is not None and observed_at < device.last_seen_at:
        return False

    stored_mac = normalize_mac_address(device.mac_address)
    incoming_mac = normalize_mac_address(mac_address)
    if stored_mac and incoming_mac and stored_mac != incoming_mac:
        return False

    device.ip_address = ip_address
    if incoming_mac:
        device.mac_address = incoming_mac

    normalized_hostname = normalize_hostname(hostname)
    if normalized_hostname:
        device.hostname = normalized_hostname

    device.last_seen_at = observed_at
    return True
