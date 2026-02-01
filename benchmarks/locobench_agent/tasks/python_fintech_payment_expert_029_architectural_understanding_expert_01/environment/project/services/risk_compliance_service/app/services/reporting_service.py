```python
"""
CrowdPay Connect – Risk & Compliance Service
------------------------------------------------
reporting_service.py

The ReportingService is responsible for generating internal and external
risk- and compliance-oriented reports, aggregating data from the event store,
KYC service, and risk-scoring engine.  Reports are persisted for audit purposes
and can be exported in multiple formats (JSON, CSV).

Author: CrowdPay Connect Risk & Compliance Team
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import pathlib
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from tempfile import NamedTemporaryFile
from typing import Dict, Iterable, List, Optional, Protocol

# Third-party (soft) dependencies
try:
    # Pydantic is used for strong validation of metrics payload
    from pydantic import BaseModel, Field, validator
except ImportError:  # pragma: no cover
    raise RuntimeError(
        "pydantic is required by reporting_service.py. "
        "Install with `pip install pydantic`."
    )

try:
    # SQLAlchemy is the reference ORM in the codebase
    from sqlalchemy import Column, DateTime, JSON, String
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import Session, scoped_session, sessionmaker
except ImportError:  # pragma: no cover
    raise RuntimeError(
        "SQLAlchemy is required by reporting_service.py. "
        "Install with `pip install sqlalchemy`."
    )

# --------------------------------------------------------------------------- #
#                               ORM / DATABASE                                #
# --------------------------------------------------------------------------- #

Base = declarative_base()


class _ReportORM(Base):
    """
    SQLAlchemy ORM entity for storing generated compliance reports.  We keep the
    ORM class private to avoid leaking DB concerns outside the service layer.
    """

    __tablename__ = "compliance_reports"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    generated_at = Column(DateTime(timezone=True), nullable=False, index=True)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    # Metrics payload is stored as JSONB; the schema is validated by Pydantic
    metrics = Column(JSON, nullable=False)
    export_uri = Column(String(length=512), nullable=True)

    # Convenience constructor
    def __init__(
        self,
        *,
        id: uuid.UUID,
        generated_at: datetime,
        period_start: datetime,
        period_end: datetime,
        metrics: Dict,
    ):
        self.id = id
        self.generated_at = generated_at
        self.period_start = period_start
        self.period_end = period_end
        self.metrics = metrics


# --------------------------------------------------------------------------- #
#                          Data Models / Validation                           #
# --------------------------------------------------------------------------- #


class ComplianceMetrics(BaseModel):
    """
    Strongly-typed metrics payload for a compliance report.
    This is version-controlled: bump `schema_version` on breaking changes.
    """

    schema_version: str = Field("1.0.0", const=True)
    gross_volume: float = Field(..., ge=0, description="Total tx volume in USD.")
    transaction_count: int = Field(..., ge=0)
    flagged_transaction_count: int = Field(..., ge=0)
    kyc_checks_performed: int = Field(..., ge=0)
    kyc_check_failures: int = Field(..., ge=0)
    sanctions_hits: int = Field(..., ge=0)
    pods_created: int = Field(..., ge=0)
    unique_users_active: int = Field(..., ge=0)

    @validator("flagged_transaction_count")
    def _flagged_cannot_exceed_total(cls, v, values):
        total = values.get("transaction_count", 0)
        if v > total:
            raise ValueError("flagged_transaction_count cannot exceed transaction_count")
        return v

    def suspicious_activity_ratio(self) -> float:
        """
        Returns the ratio of flagged to total transactions. Defaults to 0.
        """
        if self.transaction_count == 0:
            return 0.0
        return self.flagged_transaction_count / self.transaction_count


class ComplianceReport(BaseModel):
    """
    Public representation of a compliance report that can be consumed by
    external systems (regulators, auditors) or other CrowdPay micro-services.
    """

    report_id: uuid.UUID
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    metrics: ComplianceMetrics

    class Config:
        orm_mode = True  # Enable .from_orm conversion from ORM entity


# --------------------------------------------------------------------------- #
#                        Event-store Query Abstractions                       #
# --------------------------------------------------------------------------- #


class EventRecord(BaseModel):
    """
    Lightweight representation of an event bus record.  Only the fields
    required for reporting are modeled here.
    """

    event_type: str
    payload: Dict
    created_at: datetime


class EventStoreClient(Protocol):
    """
    Minimalistic protocol for event-store clients.
    """

    def fetch_events(
        self,
        *,
        event_types: Optional[Iterable[str]],
        start_time: datetime,
        end_time: datetime,
    ) -> Iterable[EventRecord]:
        ...


# --------------------------------------------------------------------------- #
#                             Repository Layer                                #
# --------------------------------------------------------------------------- #


class ReportRepository:
    """
    Repository abstraction for persisting and retrieving compliance reports.
    """

    def __init__(self, db_session_factory: sessionmaker):
        self._session_factory = scoped_session(db_session_factory)
        self._log = logging.getLogger(self.__class__.__name__)

    @contextmanager
    def session_scope(self) -> Iterable[Session]:
        """
        Provide a transactional scope around a series of operations.
        """
        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as exc:  # pragma: no cover
            session.rollback()
            self._log.exception("DB transaction rolled back due to error: %s", exc)
            raise
        finally:
            session.close()

    # ---------- Persistence ------------------------------------------------ #

    def save_report(
        self, report: ComplianceReport, export_uri: Optional[str] = None
    ) -> None:
        """
        Persist the given report to the database.
        """
        orm_obj = _ReportORM(
            id=report.report_id,
            generated_at=report.generated_at,
            period_start=report.period_start,
            period_end=report.period_end,
            metrics=report.metrics.dict(),
        )
        orm_obj.export_uri = export_uri
        with self.session_scope() as session:
            session.add(orm_obj)
            self._log.info("Compliance report persisted: %s", orm_obj.id)

    # ---------- Retrieval -------------------------------------------------- #

    def get_report(self, report_id: uuid.UUID) -> Optional[ComplianceReport]:
        with self.session_scope() as session:
            orm_obj: Optional[_ReportORM] = (
                session.query(_ReportORM).filter_by(id=report_id).one_or_none()
            )
            if orm_obj is None:
                return None
            return ComplianceReport.from_orm(orm_obj)


# --------------------------------------------------------------------------- #
#                            Reporting Service                                #
# --------------------------------------------------------------------------- #


class ReportingService:
    """
    Coordinates generation of periodic compliance reports, encapsulating all
    domain rules, aggregation logic, and side-effects such as persistence and
    export.
    """

    _EXPORT_DIR = pathlib.Path(os.getenv("REPORT_EXPORT_DIR", "/var/crowdpay/reports"))

    def __init__(
        self,
        *,
        event_store_client: EventStoreClient,
        repository: ReportRepository,
        logger: Optional[logging.Logger] = None,
    ):
        self._event_store_client = event_store_client
        self._repository = repository
        self._log = logger or logging.getLogger(self.__class__.__name__)

        self._EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------- Public API ---------------------------------- #

    def generate_report(
        self, *, period_start: datetime, period_end: datetime
    ) -> ComplianceReport:
        """
        Generate a compliance report for the specified period.  The report is
        automatically persisted.
        """
        # Step 1 ‑ Fetch relevant events
        events = list(
            self._event_store_client.fetch_events(
                event_types=None,  # None == all event types
                start_time=period_start,
                end_time=period_end,
            )
        )
        if not events:
            self._log.warning(
                "No events found between %s and %s", period_start, period_end
            )

        # Step 2 ‑ Aggregate metrics
        metrics = self._aggregate_metrics(events)

        # Step 3 ‑ Build domain object
        report = ComplianceReport(
            report_id=uuid.uuid4(),
            generated_at=datetime.now(tz=timezone.utc),
            period_start=period_start,
            period_end=period_end,
            metrics=metrics,
        )

        # Step 4 ‑ Persist report
        self._repository.save_report(report)

        self._log.info(
            "Compliance report generated: %s (period %s → %s)",
            report.report_id,
            period_start.isoformat(),
            period_end.isoformat(),
        )
        return report

    def export_report(
        self,
        report: ComplianceReport,
        *,
        export_format: str = "json",
        open_file: bool = False,
    ) -> str:
        """
        Export the given report to the configured directory.  Supports `json`
        and `csv` formats.  Returns the file URI.

        If `open_file` is True, the file handle is returned to the caller
        instead of closing the file (useful for immediate streaming).
        """
        export_format = export_format.lower()
        if export_format not in {"json", "csv"}:
            raise ValueError("Unsupported export format: %s" % export_format)

        # Use temporary file to guarantee atomic move to final destination
        tmp_file: NamedTemporaryFile
        suffix = f".{export_format}"
        with NamedTemporaryFile("w+b", delete=False, suffix=suffix) as tmp_file:
            if export_format == "json":
                data = report.json(indent=2, by_alias=False, exclude_none=True).encode()
                tmp_file.write(data)
            else:
                buf = io.StringIO()
                self._write_csv(report, buf)
                tmp_file.write(buf.getvalue().encode())

        # Finalize move
        final_path = self._EXPORT_DIR / f"{report.report_id}{suffix}"
        os.replace(tmp_file.name, final_path)

        # Update DB with export URI
        self._repository.save_report(report, export_uri=str(final_path))

        self._log.info(
            "Report %s exported to %s (format=%s)",
            report.report_id,
            final_path,
            export_format,
        )

        if open_file:
            return final_path.open("rb")  # type: ignore[return-value]

        return str(final_path)

    # ------------------------- Internal Helpers ---------------------------- #

    def _aggregate_metrics(self, events: Iterable[EventRecord]) -> ComplianceMetrics:
        """
        Aggregate raw events into `ComplianceMetrics`.
        """
        total_volume = 0.0
        tx_count = 0
        flagged_tx_count = 0
        kyc_checks = 0
        kyc_fails = 0
        sanctions_hits = 0
        pods_created = 0
        active_users = set()

        for ev in events:
            et = ev.event_type
            pld = ev.payload

            # Transaction events
            if et == "transaction.completed":
                amount = float(pld.get("amount_usd", 0))
                total_volume += amount
                tx_count += 1
                active_users.update(pld.get("participants", []))

                if pld.get("flagged_by_risk_engine", False):
                    flagged_tx_count += 1

            # Pod creation events
            elif et == "crowdpod.created":
                pods_created += 1
                creator_id = pld.get("creator_user_id")
                if creator_id:
                    active_users.add(creator_id)

            # KYC events
            elif et == "kyc.performed":
                kyc_checks += 1
                if pld.get("status") == "failed":
                    kyc_fails += 1

            # Sanction screening events
            elif et == "sanctions.hit":
                sanctions_hits += 1

        metrics = ComplianceMetrics(
            gross_volume=round(total_volume, 2),
            transaction_count=tx_count,
            flagged_transaction_count=flagged_tx_count,
            kyc_checks_performed=kyc_checks,
            kyc_check_failures=kyc_fails,
            sanctions_hits=sanctions_hits,
            pods_created=pods_created,
            unique_users_active=len(active_users),
        )

        self._log.debug("Aggregated metrics: %s", metrics.json())

        return metrics

    @staticmethod
    def _write_csv(report: ComplianceReport, buffer: io.StringIO) -> None:
        """
        Write CSV representation of a report into buffer.
        """
        writer = csv.writer(buffer)
        # Header
        writer.writerow(
            [
                "report_id",
                "generated_at",
                "period_start",
                "period_end",
                *report.metrics.dict().keys(),
            ]
        )
        # Single row
        writer.writerow(
            [
                report.report_id,
                report.generated_at.isoformat(),
                report.period_start.isoformat(),
                report.period_end.isoformat(),
                *report.metrics.dict().values(),
            ]
        )


# --------------------------------------------------------------------------- #
#                           Service Factory Helpers                           #
# --------------------------------------------------------------------------- #


def build_reporting_service(
    *,
    db_engine,
    event_store_client: EventStoreClient,
) -> ReportingService:
    """
    Convenience factory to wire all dependencies.  Used by FastAPI, CLI, or
    background worker entrypoints.
    """
    _session_factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    repository = ReportRepository(_session_factory)
    service = ReportingService(
        event_store_client=event_store_client, repository=repository
    )
    return service
```