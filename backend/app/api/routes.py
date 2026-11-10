import logging

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.database import Base, SessionLocal, engine
from app.models import (
    Device,
    DiscoveryResult,
    DiscoveryScan,
    JobExecution,
    Measurement,
    MonitoringTarget,
    ScheduledJob,
)
from app.schemas import (
    DiscoveryEnrollRequest,
    DiscoveryResultResponse,
    DiscoveryStatsResponse,
    DiscoveryScanCreate,
    DiscoveryScanResponse,
    DeviceCreate,
    DeviceResponse,
    DeviceUpdate,
    DeviceStatusResponse,
    DeviceTargetStatusResponse,
    JobExecutionResponse,
    MeasurementResponse,
    MonitoringTargetCreate,
    MonitoringTargetResponse,
    MonitoringTargetUpdate,
    ScheduledJobResponse,
    ScheduledJobScheduleUpdate,
    JobActionResponse,
    SchedulerJobStatusResponse,
    SchedulerStatusResponse,
)
from app.services.discovery import (
    create_discovery_scan,
    run_discovery_scan_background,
)
from app.services.monitoring import execute_target_probe
from app.services.reset import create_database_backup
from app.services.scheduler import monitoring_scheduler


logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health/live", tags=["Health"])
async def liveness() -> dict[str, str]:
    """Indicate that the API process is running."""
    return {"status": "alive"}


@router.get("/health/ready", tags=["Health"])
async def readiness() -> dict[str, str]:
    """Indicate that the API and its database are accessible."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database is unavailable",
        ) from exc

    return {"status": "ready", "database": "connected"}


@router.get(
    "/targets",
    response_model=list[MonitoringTargetResponse],
    tags=["Monitoring Targets"],
)
def list_targets(db: Session = Depends(get_db)):
    return db.scalars(
        select(MonitoringTarget).order_by(MonitoringTarget.id)
    ).all()


@router.post(
    "/targets",
    response_model=MonitoringTargetResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Monitoring Targets"],
)
def create_target(
    payload: MonitoringTargetCreate,
    db: Session = Depends(get_db),
):
    target = MonitoringTarget(**payload.model_dump())
    db.add(target)

    try:
        db.commit()
        db.refresh(target)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not create monitoring target",
        ) from exc

    monitoring_scheduler.reconcile()
    return target


@router.get(
    "/targets/{target_id}",
    response_model=MonitoringTargetResponse,
    tags=["Monitoring Targets"],
)
def get_target(target_id: int, db: Session = Depends(get_db)):
    target = db.get(MonitoringTarget, target_id)

    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")

    return target


@router.patch(
    "/targets/{target_id}",
    response_model=MonitoringTargetResponse,
    tags=["Monitoring Targets"],
)
def update_target(
    target_id: int,
    payload: MonitoringTargetUpdate,
    db: Session = Depends(get_db),
):
    target = db.get(MonitoringTarget, target_id)

    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(target, field, value)

    try:
        db.commit()
        db.refresh(target)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not update monitoring target",
        ) from exc

    monitoring_scheduler.reconcile()
    return target


@router.delete(
    "/targets/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Monitoring Targets"],
)
def delete_target(target_id: int, db: Session = Depends(get_db)):
    target = db.get(MonitoringTarget, target_id)

    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")

    db.delete(target)
    db.commit()

    monitoring_scheduler.reconcile()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/targets/{target_id}/probe",
    response_model=MeasurementResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Measurements"],
)
async def run_target_probe(
    target_id: int,
    db: Session = Depends(get_db),
):
    try:
        return await execute_target_probe(db, target_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/targets/{target_id}/measurements",
    response_model=list[MeasurementResponse],
    tags=["Measurements"],
)
def list_target_measurements(
    target_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=422,
            detail="Limit must be between 1 and 500",
        )

    target = db.get(MonitoringTarget, target_id)

    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")

    return db.scalars(
        select(Measurement)
        .where(Measurement.target_id == target_id)
        .order_by(Measurement.measured_at.desc())
        .limit(limit)
    ).all()


@router.get(
    "/jobs",
    response_model=list[ScheduledJobResponse],
    tags=["Scheduled Jobs"],
)
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.scalars(
        select(ScheduledJob).order_by(ScheduledJob.id)
    ).all()

    responses = []

    for job in jobs:
        latest_execution = db.scalar(
            select(JobExecution)
            .where(JobExecution.job_id == job.id)
            .order_by(JobExecution.started_at.desc())
            .limit(1)
        )

        responses.append(
            ScheduledJobResponse(
                id=job.id,
                name=job.name,
                job_type=job.job_type,
                interval_seconds=job.interval_seconds,
                schedule_type=job.schedule_type,
                cron_expression=job.cron_expression,
                timezone=job.timezone,
                start_at=job.start_at,
                end_at=job.end_at,
                schedule_is_customized=job.schedule_is_customized,
                skip_next_run=job.skip_next_run,
                is_paused=job.is_paused,
                is_enabled=job.is_enabled,
                target_id=job.target_id,
                created_at=job.created_at,
                updated_at=job.updated_at,
                latest_execution=latest_execution,
            )
        )

    return responses


@router.patch(
    "/jobs/{job_id}/schedule",
    response_model=ScheduledJobResponse,
    tags=["Scheduled Jobs"],
)
def update_job_schedule(
    job_id: int,
    payload: ScheduledJobScheduleUpdate,
    db: Session = Depends(get_db),
):
    job = db.get(ScheduledJob, job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    job.schedule_type = payload.schedule_type
    job.interval_seconds = (
        payload.interval_seconds
        if payload.schedule_type == "interval"
        else None
    )
    job.cron_expression = (
        payload.cron_expression
        if payload.schedule_type == "cron"
        else None
    )
    job.timezone = payload.timezone.strip()
    job.start_at = payload.start_at
    job.end_at = payload.end_at
    job.schedule_is_customized = True

    if payload.is_enabled is not None:
        job.is_enabled = payload.is_enabled

    # Validate the exact APScheduler trigger before persisting changes.
    try:
        monitoring_scheduler.build_trigger(job)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        db.commit()
        db.refresh(job)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not update scheduled job",
        ) from exc

    monitoring_scheduler.reconcile()

    latest_execution = db.scalar(
        select(JobExecution)
        .where(JobExecution.job_id == job.id)
        .order_by(JobExecution.started_at.desc())
        .limit(1)
    )

    return ScheduledJobResponse(
        id=job.id,
        name=job.name,
        job_type=job.job_type,
        interval_seconds=job.interval_seconds,
        schedule_type=job.schedule_type,
        cron_expression=job.cron_expression,
        timezone=job.timezone,
        start_at=job.start_at,
        end_at=job.end_at,
        schedule_is_customized=job.schedule_is_customized,
        skip_next_run=job.skip_next_run,
        is_paused=job.is_paused,
        is_enabled=job.is_enabled,
        target_id=job.target_id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        latest_execution=latest_execution,
    )


@router.post(
    "/jobs/{job_id}/run",
    response_model=JobActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Scheduled Jobs"],
)
async def run_job_now(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = db.get(ScheduledJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    if not job.is_enabled:
        raise HTTPException(
            status_code=409,
            detail="Cannot run a disabled scheduled job",
        )

    if job.job_type not in monitoring_scheduler.job_handlers:
        raise HTTPException(
            status_code=409,
            detail=f"No handler is registered for job type {job.job_type!r}",
        )

    if job.job_type == "connectivity_probe" and job.target_id is not None:
        target = db.get(MonitoringTarget, job.target_id)
        if target is None or not target.is_enabled:
            raise HTTPException(
                status_code=409,
                detail="Cannot run a job whose monitoring target is disabled",
            )

    try:
        queued = monitoring_scheduler.queue_run_now(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not queued:
        raise HTTPException(
            status_code=409,
            detail="A manual run is already queued or running for this job",
        )

    return JobActionResponse(
        job_id=job_id,
        message="Manual run queued",
    )


@router.post(
    "/jobs/{job_id}/skip-next",
    response_model=JobActionResponse,
    tags=["Scheduled Jobs"],
)
def skip_next_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = db.get(ScheduledJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    if job.skip_next_run:
        return JobActionResponse(
            job_id=job_id,
            message="The next scheduled run is already marked to be skipped",
        )

    job.skip_next_run = True
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not mark the next scheduled run to be skipped",
        ) from exc

    return JobActionResponse(
        job_id=job_id,
        message="The next scheduled run will be skipped",
    )


@router.post(
    "/jobs/{job_id}/pause",
    response_model=JobActionResponse,
    tags=["Scheduled Jobs"],
)
def pause_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = db.get(ScheduledJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    if job.is_paused:
        return JobActionResponse(
            job_id=job_id,
            message="Scheduled job is already paused",
        )

    job.is_paused = True
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not pause scheduled job",
        ) from exc

    monitoring_scheduler.reconcile()
    return JobActionResponse(
        job_id=job_id,
        message="Scheduled job paused. Any execution already in progress will finish.",
    )


@router.post(
    "/jobs/{job_id}/resume",
    response_model=JobActionResponse,
    tags=["Scheduled Jobs"],
)
def resume_job(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = db.get(ScheduledJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    if not job.is_paused:
        return JobActionResponse(
            job_id=job_id,
            message="Scheduled job is not paused",
        )

    job.is_paused = False
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not resume scheduled job",
        ) from exc

    monitoring_scheduler.reconcile()
    return JobActionResponse(
        job_id=job_id,
        message="Scheduled job resumed",
    )


@router.get(
    "/jobs/{job_id}/executions",
    response_model=list[JobExecutionResponse],
    tags=["Scheduled Jobs"],
)
def list_job_executions(
    job_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    if limit < 1 or limit > 500:
        raise HTTPException(
            status_code=422,
            detail="Limit must be between 1 and 500",
        )

    job = db.get(ScheduledJob, job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Scheduled job not found")

    return db.scalars(
        select(JobExecution)
        .where(JobExecution.job_id == job_id)
        .order_by(JobExecution.started_at.desc())
        .limit(limit)
    ).all()


@router.get(
    "/scheduler/status",
    response_model=SchedulerStatusResponse,
    tags=["Scheduled Jobs"],
)
def scheduler_status():
    jobs = monitoring_scheduler.scheduler.get_jobs()

    return SchedulerStatusResponse(
        is_running=monitoring_scheduler.scheduler.running,
        active_jobs=len(jobs),
        jobs=[
            SchedulerJobStatusResponse(
                id=job.id,
                name=job.name,
                next_run_at=job.next_run_time,
            )
            for job in jobs
        ],
    )


@router.get(
    "/devices",
    response_model=list[DeviceResponse],
    tags=["Devices"],
)
def list_devices(
    search: str | None = Query(default=None, min_length=1, max_length=100),
    device_type: str | None = Query(default=None, min_length=1, max_length=50),
    is_active: bool | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = select(Device)

    if search is not None:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                Device.name.ilike(pattern),
                Device.hostname.ilike(pattern),
                Device.ip_address.ilike(pattern),
                Device.mac_address.ilike(pattern),
            )
        )

    if device_type is not None:
        query = query.where(Device.device_type == device_type)

    if is_active is not None:
        query = query.where(Device.is_active == is_active)

    return db.scalars(
        query.order_by(Device.id).offset(offset).limit(limit)
    ).all()


@router.post(
    "/devices",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Devices"],
)
def create_device(
    payload: DeviceCreate,
    db: Session = Depends(get_db),
):
    device = Device(**payload.model_dump(mode="json"))
    db.add(device)

    try:
        db.commit()
        db.refresh(device)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not create device",
        ) from exc

    return device


@router.get(
    "/devices/{device_id}",
    response_model=DeviceResponse,
    tags=["Devices"],
)
def get_device(device_id: int, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    return device


@router.patch(
    "/devices/{device_id}",
    response_model=DeviceResponse,
    tags=["Devices"],
)
def update_device(
    device_id: int,
    payload: DeviceUpdate,
    db: Session = Depends(get_db),
):
    device = db.get(Device, device_id)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    for field, value in payload.model_dump(
        exclude_unset=True,
        mode="json",
    ).items():
        setattr(device, field, value)

    try:
        db.commit()
        db.refresh(device)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not update device",
        ) from exc

    return device


@router.delete(
    "/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Devices"],
)
def delete_device(device_id: int, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    db.delete(device)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not delete device",
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/devices/{device_id}/status",
    response_model=DeviceStatusResponse,
    tags=["Devices"],
)
def get_device_status(
    device_id: int,
    db: Session = Depends(get_db),
):
    device = db.get(Device, device_id)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    targets = db.scalars(
        select(MonitoringTarget)
        .where(MonitoringTarget.device_id == device_id)
        .order_by(MonitoringTarget.id)
    ).all()

    target_statuses = []
    available_targets = 0
    unavailable_targets = 0
    enabled_targets = 0
    has_missing_measurements = False

    for target in targets:
        latest_measurement = db.scalar(
            select(Measurement)
            .where(Measurement.target_id == target.id)
            .order_by(
                Measurement.measured_at.desc(),
                Measurement.id.desc(),
            )
            .limit(1)
        )

        if target.is_enabled:
            enabled_targets += 1

            if latest_measurement is None:
                has_missing_measurements = True
            elif latest_measurement.is_available:
                available_targets += 1
            else:
                unavailable_targets += 1

        target_statuses.append(
            DeviceTargetStatusResponse(
                id=target.id,
                name=target.name,
                target=target.target,
                protocol=target.protocol,
                is_enabled=target.is_enabled,
                latest_measurement=latest_measurement,
            )
        )

    if enabled_targets == 0 or has_missing_measurements:
        overall_status = "unknown"
    elif unavailable_targets == 0:
        overall_status = "online"
    elif available_targets == 0:
        overall_status = "offline"
    else:
        overall_status = "degraded"

    return DeviceStatusResponse(
        device_id=device.id,
        device_name=device.name,
        status=overall_status,
        enabled_targets=enabled_targets,
        available_targets=available_targets,
        unavailable_targets=unavailable_targets,
        targets=target_statuses,
    )



@router.get(
    "/discovery/stats",
    response_model=DiscoveryStatsResponse,
    tags=["Network Discovery"],
)
def get_discovery_stats(db: Session = Depends(get_db)):
    total_scans = db.scalar(
        select(func.count()).select_from(DiscoveryScan)
    ) or 0

    active_scans = db.scalar(
        select(func.count()).select_from(DiscoveryScan).where(
            DiscoveryScan.status.in_(("pending", "running"))
        )
    ) or 0

    total_observations = db.scalar(
        select(func.count()).select_from(DiscoveryResult)
    ) or 0

    linked_ids = set(
        db.scalars(
            select(DiscoveryResult.device_id)
            .where(DiscoveryResult.device_id.is_not(None))
            .distinct()
        ).all()
    )

    unlinked_rows = db.execute(
        select(DiscoveryResult.mac_address, DiscoveryResult.ip_address)
        .where(DiscoveryResult.device_id.is_(None))
    ).all()

    unlinked_identities = {
        (
            "mac",
            mac_address.strip().lower(),
        ) if mac_address and mac_address.strip() else (
            "ip",
            ip_address,
        )
        for mac_address, ip_address in unlinked_rows
    }

    return DiscoveryStatsResponse(
        total_scans=total_scans,
        active_scans=active_scans,
        total_observations=total_observations,
        discovered_devices=len(linked_ids) + len(unlinked_identities),
        enrolled_devices=len(linked_ids),
    )


@router.post(
    "/discovery/scans",
    response_model=DiscoveryScanResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Network Discovery"],
)
def start_discovery_scan(
    payload: DiscoveryScanCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        scan = create_discovery_scan(db, payload.network_cidr)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not create discovery scan",
        ) from exc

    background_tasks.add_task(run_discovery_scan_background, scan.id)
    return scan


@router.get(
    "/discovery/scans",
    response_model=list[DiscoveryScanResponse],
    tags=["Network Discovery"],
)
def list_discovery_scans(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(DiscoveryScan)
        .order_by(DiscoveryScan.created_at.desc(), DiscoveryScan.id.desc())
        .limit(limit)
    ).all()


@router.get(
    "/discovery/scans/{scan_id}",
    response_model=DiscoveryScanResponse,
    tags=["Network Discovery"],
)
def get_discovery_scan(
    scan_id: int,
    db: Session = Depends(get_db),
):
    scan = db.get(DiscoveryScan, scan_id)

    if scan is None:
        raise HTTPException(status_code=404, detail="Discovery scan not found")

    return scan


@router.get(
    "/discovery/results",
    response_model=list[DiscoveryResultResponse],
    tags=["Network Discovery"],
)
def list_discovery_results(
    scan_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = select(DiscoveryResult)

    if scan_id is not None:
        if db.get(DiscoveryScan, scan_id) is None:
            raise HTTPException(status_code=404, detail="Discovery scan not found")
        query = query.where(DiscoveryResult.scan_id == scan_id)

    return db.scalars(
        query.order_by(
            DiscoveryResult.discovered_at.desc(),
            DiscoveryResult.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()

@router.post(
    "/discovery/results/{result_id}/enroll",
    response_model=DeviceResponse,
    tags=["Network Discovery"],
)
def enroll_discovery_result(
    result_id: int,
    payload: DiscoveryEnrollRequest,
    db: Session = Depends(get_db),
):
    result = db.get(DiscoveryResult, result_id)

    if result is None:
        raise HTTPException(status_code=404, detail="Discovery result not found")

    if result.device_id is not None:
        linked_device = db.get(Device, result.device_id)
        if linked_device is not None:
            if payload.name and payload.name.strip():
                linked_device.name = payload.name.strip()
                try:
                    db.commit()
                    db.refresh(linked_device)
                except SQLAlchemyError as exc:
                    db.rollback()
                    raise HTTPException(
                        status_code=400,
                        detail="Could not update the enrolled device name",
                    ) from exc
            return linked_device

    mac_matches = []
    if result.mac_address:
        mac_matches = db.scalars(
            select(Device).where(
                func.lower(Device.mac_address) == result.mac_address.lower()
            )
        ).all()

    ip_matches = db.scalars(
        select(Device).where(Device.ip_address == result.ip_address)
    ).all()

    matching_ids = {device.id for device in mac_matches + ip_matches}

    if len(matching_ids) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "The discovered MAC address and IP address match different "
                "registered devices. Resolve the device records before enrolling."
            ),
        )

    if len(mac_matches) > 1 or len(ip_matches) > 1:
        raise HTTPException(
            status_code=409,
            detail="Multiple registered devices match this discovery result.",
        )

    existing_device = (mac_matches or ip_matches or [None])[0]

    if existing_device is not None:
        result.device_id = existing_device.id
        if payload.name and payload.name.strip():
            existing_device.name = payload.name.strip()
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail="Could not link discovery result to existing device",
            ) from exc
        return existing_device

    device = Device(
        name=payload.name or result.hostname or result.ip_address,
        hostname=result.hostname,
        ip_address=result.ip_address,
        mac_address=result.mac_address.lower() if result.mac_address else None,
        device_type=payload.device_type,
        notes=payload.notes,
    )
    db.add(device)

    try:
        db.flush()
        result.device_id = device.id
        db.commit()
        db.refresh(device)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Could not enroll discovered device",
        ) from exc

    return device

@router.post(
    "/system/reset",
    tags=["System"],
)
async def reset_system(
    confirmation: str = Body(embed=True),
    db: Session = Depends(get_db),
):
    """Back up the database, then remove all application data and settings."""
    if confirmation != "RESET":
        raise HTTPException(
            status_code=422,
            detail='Confirmation must be exactly "RESET".',
        )

    scheduler = monitoring_scheduler.scheduler
    scheduler_was_running = scheduler.running
    committed = False
    backup_path = None

    try:
        if scheduler_was_running:
            scheduler.pause()
            scheduler.remove_all_jobs()

        async with monitoring_scheduler.execution_lock:
            # Take the backup only after active scheduled probes have finished.
            backup_path = create_database_backup()

            # Preserve Alembic's migration history; clear application tables only.
            for table in reversed(Base.metadata.sorted_tables):
                db.execute(table.delete())

            db.commit()
            committed = True

            # Rebuild the scheduler from the now-empty database.
            monitoring_scheduler.reconcile()

        if scheduler_was_running:
            scheduler.resume()

    except Exception as exc:
        if not committed:
            db.rollback()

        if scheduler_was_running:
            try:
                # Rebuild jobs from the database whether the reset committed or not.
                monitoring_scheduler.reconcile()
                scheduler.resume()
            except Exception:
                logger.exception("Could not recover scheduler after reset failure")

        if not committed:
            if backup_path is None:
                detail = f"Reset cancelled because the database backup failed: {exc}"
            else:
                detail = (
                    "Reset failed; application data was not committed. "
                    f"The pre-reset backup is available at {backup_path.name}."
                )

            raise HTTPException(
                status_code=500,
                detail=detail,
            ) from exc

        raise HTTPException(
            status_code=500,
            detail=(
                "The data reset completed, but scheduler reconciliation failed. "
                f"The pre-reset backup is available at {backup_path.name}."
            ),
        ) from exc

    return {
        "status": "reset",
        "message": "All application data and configurations were reset.",
        "backup_file": backup_path.name,
    }
