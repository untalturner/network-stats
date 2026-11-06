from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Measurement, MonitoringTarget
from app.probes import probe_target


async def execute_target_probe(
    db: Session,
    target_id: int,
) -> Measurement:
    target = db.scalar(
        select(MonitoringTarget).where(MonitoringTarget.id == target_id)
    )

    if target is None:
        raise LookupError("Target not found")

    if not target.is_enabled:
        raise PermissionError("Target is disabled")

    result = await probe_target(
        target=target.target,
        protocol=target.protocol,
        timeout_seconds=target.timeout_seconds,
    )

    measurement = Measurement(
        target_id=target.id,
        measured_at=result.measured_at,
        latency_ms=result.latency_ms,
        packet_loss_percent=result.packet_loss_percent,
        is_available=result.is_available,
        error=result.error,
    )

    db.add(measurement)

    try:
        db.commit()
        db.refresh(measurement)
    except Exception:
        db.rollback()
        raise

    return measurement
