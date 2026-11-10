from datetime import datetime, timezone as dt_timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress, model_validator


Protocol = Literal["icmp", "tcp", "http", "https"]


class MonitoringTargetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    target: str = Field(min_length=1, max_length=500)
    protocol: Protocol
    interval_seconds: int = Field(default=60, ge=5, le=86400)
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    is_enabled: bool = True
    device_id: int | None = None


class MonitoringTargetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    target: str | None = Field(default=None, min_length=1, max_length=500)
    protocol: Protocol | None = None
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    timeout_seconds: float | None = Field(default=None, gt=0, le=60)
    is_enabled: bool | None = None
    device_id: int | None = None


class MonitoringTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    target: str
    protocol: str
    interval_seconds: int
    timeout_seconds: float
    is_enabled: bool
    device_id: int | None
    created_at: datetime


class MeasurementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_id: int
    measured_at: datetime
    latency_ms: float | None
    packet_loss_percent: float | None
    is_available: bool
    error: str | None


class JobExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int | None
    job_name: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    error: str | None


class JobActionResponse(BaseModel):
    job_id: int
    message: str


class ScheduledJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    job_type: str
    interval_seconds: int | None
    schedule_type: str
    cron_expression: str | None
    timezone: str
    start_at: datetime | None
    end_at: datetime | None
    schedule_is_customized: bool
    skip_next_run: bool
    is_paused: bool
    execution_timeout_seconds: float
    is_enabled: bool
    target_id: int | None
    created_at: datetime
    updated_at: datetime
    latest_execution: JobExecutionResponse | None = None


class ScheduledJobScheduleUpdate(BaseModel):
    """Complete schedule configuration for a persisted scheduled job."""

    schedule_type: Literal["interval", "cron"]
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    cron_expression: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    start_at: datetime | None = None
    end_at: datetime | None = None
    execution_timeout_seconds: float = Field(
        default=300.0, ge=1.0, le=86400.0
    )
    is_enabled: bool | None = None

    @model_validator(mode="after")
    def validate_schedule_definition(self):
        if self.schedule_type == "interval" and self.interval_seconds is None:
            raise ValueError("Interval schedules require interval_seconds")

        if self.schedule_type == "cron" and not self.cron_expression:
            raise ValueError("Cron schedules require cron_expression")

        if self.start_at is not None and self.end_at is not None:
            start = self.start_at
            end = self.end_at

            if start.tzinfo is None:
                start = start.replace(tzinfo=dt_timezone.utc)
            else:
                start = start.astimezone(dt_timezone.utc)

            if end.tzinfo is None:
                end = end.replace(tzinfo=dt_timezone.utc)
            else:
                end = end.astimezone(dt_timezone.utc)

            if end <= start:
                raise ValueError("Schedule end_at must be later than start_at")

        return self


class SchedulerJobStatusResponse(BaseModel):
    id: str
    name: str
    next_run_at: datetime | None


class SchedulerStatusResponse(BaseModel):
    is_running: bool
    active_jobs: int
    jobs: list[SchedulerJobStatusResponse]


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    hostname: str | None = Field(default=None, max_length=255)
    ip_address: IPvAnyAddress | None = None
    mac_address: str | None = Field(
        default=None,
        pattern=r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$",
    )
    device_type: str | None = Field(default=None, max_length=50)
    notes: str | None = None
    is_active: bool = True


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    hostname: str | None = Field(default=None, max_length=255)
    ip_address: IPvAnyAddress | None = None
    mac_address: str | None = Field(
        default=None,
        pattern=r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$",
    )
    device_type: str | None = Field(default=None, max_length=50)
    notes: str | None = None
    is_active: bool | None = None


class DeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    hostname: str | None
    ip_address: str | None
    mac_address: str | None
    device_type: str | None
    notes: str | None
    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime | None


class DeviceTargetStatusResponse(BaseModel):
    id: int
    name: str
    target: str
    protocol: str
    is_enabled: bool
    latest_measurement: MeasurementResponse | None = None


class DeviceStatusResponse(BaseModel):
    device_id: int
    device_name: str
    status: Literal["online", "degraded", "offline", "unknown"]
    enabled_targets: int
    available_targets: int
    unavailable_targets: int
    targets: list[DeviceTargetStatusResponse]


class DiscoveryStatsResponse(BaseModel):
    total_scans: int
    active_scans: int
    total_observations: int
    discovered_devices: int
    enrolled_devices: int


class DiscoveryScanCreate(BaseModel):
    network_cidr: str = Field(min_length=1, max_length=43)


class DiscoveryEnrollRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    device_type: str | None = Field(default=None, max_length=50)
    notes: str | None = None


class DiscoveryResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scan_id: int
    device_id: int | None

    device_name: str | None = None
    ip_address: str
    mac_address: str | None
    hostname: str | None
    discovery_method: str
    response_time_ms: float | None
    icmp_latency_ms: float | None = None
    icmp_is_available: bool | None = None
    icmp_error: str | None = None
    is_this_device: bool = False
    open_ports: list[int]
    discovered_at: datetime


class DiscoveryScanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    network_cidr: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    devices_found: int
    error: str | None
    created_at: datetime
    results: list[DiscoveryResultResponse] = []
