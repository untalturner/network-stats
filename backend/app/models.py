from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45), index=True)
    mac_address: Mapped[str | None] = mapped_column(String(17), index=True)
    device_type: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)

    targets: Mapped[list["MonitoringTarget"]] = relationship(
        back_populates="device"
    )


class MonitoringTarget(Base):
    __tablename__ = "monitoring_targets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    target: Mapped[str] = mapped_column(String(500), nullable=False)
    protocol: Mapped[str] = mapped_column(String(20), nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False
    )

    device: Mapped[Device | None] = relationship(back_populates="targets")
    measurements: Mapped[list["Measurement"]] = relationship(
        back_populates="target"
    )


class Measurement(Base):
    __tablename__ = "measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("monitoring_targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    measured_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, index=True
    )
    latency_ms: Mapped[float | None] = mapped_column(Float)
    packet_loss_percent: Mapped[float | None] = mapped_column(Float)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    target: Mapped[MonitoringTarget] = relationship(back_populates="measurements")


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    schedule_type: Mapped[str] = mapped_column(
        String(20), default="interval", nullable=False
    )
    cron_expression: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC", nullable=False
    )
    start_at: Mapped[datetime | None] = mapped_column(DateTime)
    end_at: Mapped[datetime | None] = mapped_column(DateTime)
    schedule_is_customized: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    skip_next_run: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    target_id: Mapped[int | None] = mapped_column(
        ForeignKey("monitoring_targets.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    target: Mapped[MonitoringTarget | None] = relationship()
    executions: Mapped[list["JobExecution"]] = relationship(
        back_populates="job",
        order_by="JobExecution.started_at.desc()",
    )


class JobExecution(Base):
    __tablename__ = "job_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("scheduled_jobs.id", ondelete="SET NULL"),
        index=True,
    )
    job_name: Mapped[str | None] = mapped_column(String(150))
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    job: Mapped[ScheduledJob | None] = relationship(back_populates="executions")


class DiscoveryScan(Base):
    __tablename__ = "discovery_scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    network_cidr: Mapped[str] = mapped_column(String(43), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    devices_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False
    )

    results: Mapped[list["DiscoveryResult"]] = relationship(
        back_populates="scan",
        cascade="all, delete-orphan",
        order_by="DiscoveryResult.ip_address",
    )


class DiscoveryResult(Base):
    __tablename__ = "discovery_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("discovery_scans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    mac_address: Mapped[str | None] = mapped_column(String(17))
    hostname: Mapped[str | None] = mapped_column(String(255))
    discovery_method: Mapped[str] = mapped_column(String(20), nullable=False)
    response_time_ms: Mapped[float | None] = mapped_column(Float)
    icmp_latency_ms: Mapped[float | None] = mapped_column(Float)
    icmp_is_available: Mapped[bool | None] = mapped_column(Boolean)
    icmp_error: Mapped[str | None] = mapped_column(Text)
    is_this_device: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    open_ports: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False
    )

    scan: Mapped[DiscoveryScan] = relationship(back_populates="results")
    device: Mapped[Device | None] = relationship()

    @property
    def device_name(self) -> str | None:
        return self.device.name if self.device is not None else None
