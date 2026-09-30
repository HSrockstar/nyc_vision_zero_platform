"""M1的23张关系表；源记录键、观察地点和派生结果分别建模。"""

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
    Identity, Index, Integer, Numeric, SmallInteger, String, Text, Time,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


def internal_id():
    return Column(BigInteger, Identity(), primary_key=True)


def reference(target, *, nullable=False, unique=False, primary_key=False):
    return Column(BigInteger, ForeignKey(target, ondelete="RESTRICT"),
                  nullable=nullable, unique=unique, primary_key=primary_key)


def timestamp():
    return Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


def json_object():
    return Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


def version():
    return Column(Integer, nullable=False, server_default=text("1"))


def enum_check(column, values, name):
    quoted = ", ".join("'" + value + "'" for value in values.split())
    return CheckConstraint(f"{column} IN ({quoted})", name=name)


def hash_check(column, name):
    return CheckConstraint(f"{column} ~ '^[0-9a-f]{{64}}$'", name=name)


TASK_STATUSES = "DRAFT OPEN IN_PROGRESS PENDING_REVIEW COMPLETED CANCELLED"


class Borough(Base):
    __tablename__ = "borough"
    borough_id = Column(SmallInteger, primary_key=True)
    borough_name = Column(String(40), nullable=False, unique=True)
    display_name = Column(String(80))
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    __table_args__ = (CheckConstraint("borough_id BETWEEN 1 AND 5", name="ck_borough_id"),)


class Role(Base):
    __tablename__ = "role"
    role_id = Column(SmallInteger, primary_key=True)
    role_code = Column(String(20), nullable=False, unique=True)
    role_name = Column(String(60), nullable=False)
    __table_args__ = (CheckConstraint(
        "(role_id = 1 AND role_code = 'ADMIN') OR "
        "(role_id = 2 AND role_code = 'MANAGER') OR "
        "(role_id = 3 AND role_code = 'VIEWER')", name="ck_role_fixed"),)


class AppUser(Base):
    __tablename__ = "app_user"
    user_id = internal_id()
    username = Column(String(80), nullable=False)
    password_hash = Column(Text, nullable=False)
    display_name = Column(String(80), nullable=False)
    role_id = Column(SmallInteger, ForeignKey("role.role_id", ondelete="RESTRICT"), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    auth_version = version()
    created_at = timestamp()
    updated_at = timestamp()
    version = version()
    __table_args__ = (
        Index("uq_app_user_username_lower", text("lower(username)"), unique=True),
        CheckConstraint("auth_version > 0 AND version > 0", name="ck_user_versions"),
        CheckConstraint("btrim(username) <> '' AND btrim(display_name) <> ''", name="ck_user_names"),
    )


class ImportBatch(Base):
    __tablename__ = "import_batch"
    batch_id = internal_id()
    request_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    request_hash = Column(String(64), nullable=False)
    manifest_hash = Column(String(64), nullable=False)
    publish_request_id = Column(UUID(as_uuid=True), unique=True)
    publish_request_hash = Column(String(64))
    publish_requested_by = reference("app_user.user_id", nullable=True)
    cleaning_version = Column(String(40), nullable=False)
    input_manifest = json_object()
    requested_start = Column(Date)
    requested_end = Column(Date)
    status = Column(String(30), nullable=False)
    rows_read = Column(BigInteger, nullable=False, server_default=text("0"))
    rows_accepted = Column(BigInteger, nullable=False, server_default=text("0"))
    rows_rejected = Column(BigInteger, nullable=False, server_default=text("0"))
    rows_skipped = Column(BigInteger, nullable=False, server_default=text("0"))
    created_by = reference("app_user.user_id")
    created_at = timestamp()
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    published_revision = Column(BigInteger)
    worker_token = Column(UUID(as_uuid=True))
    lease_expires_at = Column(DateTime(timezone=True))
    attempt_no = Column(Integer, nullable=False, server_default=text("0"))
    error_summary = Column(Text)
    __table_args__ = (
        Index("ix_import_lease", "status", "lease_expires_at"),
        enum_check("status", "UPLOADED VALIDATING READY PUBLISHING SUCCEEDED FAILED CANCELLED", "ck_import_status"),
        CheckConstraint("rows_read >= 0 AND rows_accepted >= 0 AND rows_rejected >= 0 AND rows_skipped >= 0 AND attempt_no >= 0", name="ck_import_counts"),
        CheckConstraint("(requested_start IS NULL AND requested_end IS NULL) OR (requested_start IS NOT NULL AND requested_end IS NOT NULL AND requested_start < requested_end)", name="ck_import_period"),
        CheckConstraint("status NOT IN ('READY', 'PUBLISHING', 'SUCCEEDED') OR rows_read = rows_accepted + rows_rejected + rows_skipped", name="ck_import_balance"),
        CheckConstraint("status <> 'SUCCEEDED' OR (published_revision IS NOT NULL AND published_revision > 0 AND finished_at IS NOT NULL)", name="ck_import_published"),
        hash_check("request_hash", "ck_import_request_hash"),
        hash_check("manifest_hash", "ck_import_manifest_hash"),
        hash_check("publish_request_hash", "ck_import_publish_hash"),
        CheckConstraint("(publish_request_id IS NULL AND publish_request_hash IS NULL AND publish_requested_by IS NULL) OR (publish_request_id IS NOT NULL AND publish_request_hash IS NOT NULL AND publish_requested_by IS NOT NULL)", name="ck_import_publish_request"),
        CheckConstraint("jsonb_typeof(input_manifest) = 'object'", name="ck_import_manifest_object"),
    )


class RawRecord(Base):
    __tablename__ = "raw_record"
    raw_record_id = internal_id()
    batch_id = reference("import_batch.batch_id")
    source_kind = Column(String(12), nullable=False)
    row_no = Column(BigInteger, nullable=False)
    source_key = Column(Text)
    payload = json_object()
    row_hash = Column(String(64), nullable=False)
    validation_status = Column(String(20), nullable=False)
    created_at = timestamp()
    __table_args__ = (
        UniqueConstraint("batch_id", "source_kind", "row_no", name="uq_raw_batch_line"),
        Index("ix_raw_batch_source_key", "batch_id", "source_kind", "source_key"),
        enum_check("source_kind", "CRASHES PERSON VEHICLES", "ck_raw_source"),
        enum_check("validation_status", "UNVALIDATED ACCEPTED REJECTED SKIPPED", "ck_raw_validation"),
        CheckConstraint("row_no > 0", name="ck_raw_line"),
        hash_check("row_hash", "ck_raw_hash"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_raw_payload"),
    )


class Location(Base):
    __tablename__ = "location"
    location_id = internal_id()
    location_key = Column(Text, nullable=False, unique=True)
    key_input = json_object()
    borough_id = Column(SmallInteger, ForeignKey("borough.borough_id", ondelete="RESTRICT"))
    zip_code = Column(String(20))
    on_street_name = Column(Text)
    cross_street_name = Column(Text)
    off_street_name = Column(Text)
    geom = Column(Geometry("POINT", srid=4326, spatial_index=False))
    created_at = timestamp()
    __table_args__ = (
        Index("ix_location_borough", "borough_id", "location_id"),
        Index("ix_location_geom", "geom", postgresql_using="gist", postgresql_where=text("geom IS NOT NULL")),
        Index("ix_location_geography", text("(geom::geography)"), postgresql_using="gist", postgresql_where=text("geom IS NOT NULL")),
        CheckConstraint("geom IS NULL OR (NOT ST_IsEmpty(geom) AND ST_X(geom) BETWEEN -180 AND 180 AND ST_Y(geom) BETWEEN -90 AND 90)", name="ck_location_coordinates"),
        CheckConstraint("jsonb_typeof(key_input) = 'object'", name="ck_location_key_input"),
    )


class Intersection(Base):
    __tablename__ = "intersection"
    intersection_id = internal_id()
    intersection_code = Column(String(40), nullable=False, unique=True)
    borough_id = Column(SmallInteger, ForeignKey("borough.borough_id", ondelete="RESTRICT"))
    street_a = Column(Text, nullable=False)
    street_b = Column(Text, nullable=False)
    center_geom = Column(Geometry("POINT", srid=4326, spatial_index=False), nullable=False)
    status = Column(String(20), nullable=False)
    source_method = Column(String(30), nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    supersedes_id = reference("intersection.intersection_id", nullable=True)
    confirmation_note = Column(Text)
    confirmed_by = reference("app_user.user_id", nullable=True)
    confirmed_at = Column(DateTime(timezone=True))
    created_at = timestamp()
    updated_at = timestamp()
    version = version()
    __table_args__ = (
        Index("ix_intersection_center", "center_geom", postgresql_using="gist"),
        Index("ix_intersection_geography", text("(center_geom::geography)"), postgresql_using="gist"),
        enum_check("status", "CANDIDATE CONFIRMED REJECTED", "ck_intersection_status"),
        enum_check("source_method", "DERIVED MANUAL EXTERNAL", "ck_intersection_source"),
        CheckConstraint("version > 0 AND btrim(street_a) <> '' AND btrim(street_b) <> ''", name="ck_intersection_fields"),
        CheckConstraint("supersedes_id IS NULL OR supersedes_id <> intersection_id", name="ck_intersection_supersedes"),
        CheckConstraint("status <> 'CONFIRMED' OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL AND confirmation_note IS NOT NULL AND btrim(confirmation_note) <> '')", name="ck_intersection_confirmation"),
        CheckConstraint("NOT ST_IsEmpty(center_geom) AND ST_X(center_geom) BETWEEN -180 AND 180 AND ST_Y(center_geom) BETWEEN -90 AND 90", name="ck_intersection_coordinates"),
    )


class LocationAssignment(Base):
    __tablename__ = "location_assignment"
    location_id = reference("location.location_id", primary_key=True)
    intersection_id = reference("intersection.intersection_id", nullable=True)
    match_status = Column(String(30), nullable=False)
    match_method = Column(String(40), nullable=False)
    algorithm_version = Column(String(40), nullable=False)
    distance_m = Column(Numeric(10, 2))
    evidence = json_object()
    reviewed_by = reference("app_user.user_id", nullable=True)
    reviewed_at = Column(DateTime(timezone=True))
    updated_at = timestamp()
    version = version()
    __table_args__ = (
        Index("ix_assignment_intersection", "intersection_id", "location_id"),
        enum_check("match_status", "UNMATCHED CANDIDATE AUTO_MATCHED MANUAL_CONFIRMED REJECTED", "ck_assignment_status"),
        CheckConstraint("match_status NOT IN ('AUTO_MATCHED', 'MANUAL_CONFIRMED') OR intersection_id IS NOT NULL", name="ck_assignment_target"),
        CheckConstraint("match_status <> 'MANUAL_CONFIRMED' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)", name="ck_assignment_review"),
        CheckConstraint("distance_m >= 0 AND distance_m <> 'NaN'::numeric", name="ck_assignment_distance"),
        CheckConstraint("version > 0", name="ck_assignment_version"),
    )


class Collision(Base):
    __tablename__ = "collision"
    collision_id = Column(BigInteger, primary_key=True)
    location_id = reference("location.location_id")
    crash_date = Column(Date, nullable=False)
    crash_time = Column(Time)
    source_record_id = reference("raw_record.raw_record_id", unique=True)
    imported_at = timestamp()
    updated_at = timestamp()
    __table_args__ = (
        Index("ix_collision_date_id", text("crash_date DESC"), text("collision_id DESC")),
        Index("ix_collision_location_date", "location_id", "crash_date"),
        CheckConstraint("collision_id > 0", name="ck_collision_source_id"),
    )


class Person(Base):
    __tablename__ = "person"
    person_id = Column(BigInteger, primary_key=True)
    collision_id = reference("collision.collision_id")
    source_person_id = Column(Text)
    source_vehicle_id = Column(Text)
    person_type = Column(Text)
    person_injury = Column(Text)
    person_age = Column(SmallInteger)
    person_sex = Column(Text)
    source_record_id = reference("raw_record.raw_record_id", unique=True)
    updated_at = timestamp()
    __table_args__ = (
        Index("ix_person_collision", "collision_id"),
        CheckConstraint("person_id > 0", name="ck_person_source_id"),
        CheckConstraint("person_age BETWEEN 0 AND 120", name="ck_person_age_quality"),
    )


class VehicleType(Base):
    __tablename__ = "vehicle_type"
    vehicle_type_id = internal_id()
    canonical_name = Column(Text, nullable=False, unique=True)
    display_name = Column(Text)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    __table_args__ = (CheckConstraint("btrim(canonical_name) <> ''", name="ck_vehicle_type_name"),)


class Vehicle(Base):
    __tablename__ = "vehicle"
    vehicle_id = Column(BigInteger, primary_key=True)
    collision_id = reference("collision.collision_id")
    source_vehicle_id = Column(Text)
    vehicle_type_id = reference("vehicle_type.vehicle_type_id", nullable=True)
    vehicle_year = Column(SmallInteger)
    travel_direction = Column(Text)
    pre_crash = Column(Text)
    point_of_impact = Column(Text)
    vehicle_damage = Column(Text)
    source_record_id = reference("raw_record.raw_record_id", unique=True)
    updated_at = timestamp()
    __table_args__ = (
        Index("ix_vehicle_collision", "collision_id"),
        Index("ix_vehicle_type_collision", "vehicle_type_id", "collision_id"),
        CheckConstraint("vehicle_id > 0", name="ck_vehicle_source_id"),
        CheckConstraint("vehicle_year BETWEEN 1886 AND 2100", name="ck_vehicle_year_quality"),
    )


class ContributingFactor(Base):
    __tablename__ = "contributing_factor"
    factor_id = internal_id()
    canonical_name = Column(Text, nullable=False, unique=True)
    display_name = Column(Text)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    __table_args__ = (CheckConstraint("btrim(canonical_name) <> ''", name="ck_factor_name"),)


class CollisionFactor(Base):
    __tablename__ = "collision_factor"
    collision_id = reference("collision.collision_id", primary_key=True)
    factor_order = Column(SmallInteger, primary_key=True)
    factor_id = reference("contributing_factor.factor_id")
    __table_args__ = (
        CheckConstraint("factor_order BETWEEN 1 AND 5", name="ck_factor_order"),
        Index("ix_factor_collision", "factor_id", "collision_id"),
    )


class CasualtyStat(Base):
    __tablename__ = "casualty_stat"
    collision_id = reference("collision.collision_id", primary_key=True)
    persons_injured = Column(Integer)
    persons_killed = Column(Integer)
    pedestrians_injured = Column(Integer)
    pedestrians_killed = Column(Integer)
    cyclists_injured = Column(Integer)
    cyclists_killed = Column(Integer)
    motorists_injured = Column(Integer)
    motorists_killed = Column(Integer)
    __table_args__ = tuple(CheckConstraint(f"{field} >= 0", name=f"ck_casualty_{field}") for field in (
        "persons_injured", "persons_killed", "pedestrians_injured", "pedestrians_killed",
        "cyclists_injured", "cyclists_killed", "motorists_injured", "motorists_killed"))


class RiskRule(Base):
    __tablename__ = "risk_rule"
    rule_id = internal_id()
    rule_code = Column(String(40), nullable=False)
    version_no = Column(Integer, nullable=False)
    rule_name = Column(Text, nullable=False)
    weight_collision = Column(Numeric(10, 2), nullable=False)
    weight_injured = Column(Numeric(10, 2), nullable=False)
    weight_killed = Column(Numeric(10, 2), nullable=False)
    weight_vru = Column(Numeric(10, 2), nullable=False)
    threshold_medium = Column(Numeric(12, 2), nullable=False)
    threshold_high = Column(Numeric(12, 2), nullable=False)
    status = Column(String(20), nullable=False)
    rationale = Column(Text, nullable=False)
    created_by = reference("app_user.user_id", nullable=True)
    created_at = timestamp()
    __table_args__ = (
        UniqueConstraint("rule_code", "version_no", name="uq_rule_version"),
        enum_check("status", "DRAFT PUBLISHED RETIRED", "ck_rule_status"),
        CheckConstraint("version_no > 0 AND weight_collision >= 0 AND weight_injured >= 0 AND weight_killed >= 0 AND weight_vru >= 0 AND threshold_medium >= 0 AND threshold_high > threshold_medium AND weight_collision <> 'NaN'::numeric AND weight_injured <> 'NaN'::numeric AND weight_killed <> 'NaN'::numeric AND weight_vru <> 'NaN'::numeric AND threshold_medium <> 'NaN'::numeric AND threshold_high <> 'NaN'::numeric", name="ck_rule_values"),
    )


class RiskRun(Base):
    __tablename__ = "risk_run"
    run_id = internal_id()
    request_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    request_hash = Column(String(64), nullable=False)
    rule_id = reference("risk_rule.rule_id")
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    input_revision = Column(BigInteger)
    status = Column(String(20), nullable=False)
    input_manifest = json_object()
    coverage_summary = json_object()
    requested_by = reference("app_user.user_id")
    created_at = timestamp()
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    worker_token = Column(UUID(as_uuid=True))
    lease_expires_at = Column(DateTime(timezone=True))
    attempt_no = Column(Integer, nullable=False, server_default=text("0"))
    error_summary = Column(Text)
    __table_args__ = (
        enum_check("status", "QUEUED RUNNING SUCCEEDED FAILED", "ck_run_status"),
        CheckConstraint("period_start < period_end", name="ck_run_period"),
        CheckConstraint("attempt_no >= 0 AND (input_revision IS NULL OR input_revision >= 0)", name="ck_run_counts"),
        CheckConstraint("status <> 'SUCCEEDED' OR (input_revision IS NOT NULL AND finished_at IS NOT NULL)", name="ck_run_complete"),
        hash_check("request_hash", "ck_run_request_hash"),
    )


class RiskProfile(Base):
    __tablename__ = "risk_profile"
    profile_id = internal_id()
    run_id = reference("risk_run.run_id")
    intersection_id = reference("intersection.intersection_id")
    collision_count = Column(BigInteger, nullable=False)
    injured_count = Column(BigInteger, nullable=False)
    killed_count = Column(BigInteger, nullable=False)
    vulnerable_road_user_count = Column(BigInteger, nullable=False)
    incomplete_casualty_collision_count = Column(BigInteger, nullable=False)
    __table_args__ = (
        UniqueConstraint("run_id", "intersection_id", name="uq_profile_run_intersection"),
        Index("ix_profile_intersection_run", "intersection_id", text("run_id DESC")),
        CheckConstraint("collision_count > 0 AND injured_count >= 0 AND killed_count >= 0 AND vulnerable_road_user_count >= 0 AND incomplete_casualty_collision_count BETWEEN 0 AND collision_count", name="ck_profile_counts"),
    )


class GovernanceTask(Base):
    __tablename__ = "governance_task"
    task_id = internal_id()
    task_code = Column(String(40), nullable=False, unique=True)
    request_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    request_hash = Column(String(64), nullable=False)
    profile_id = reference("risk_profile.profile_id")
    title = Column(String(160), nullable=False)
    description = Column(Text, nullable=False)
    measure_type = Column(String(40), nullable=False)
    priority = Column(String(20), nullable=False)
    status = Column(String(30), nullable=False)
    created_by = reference("app_user.user_id")
    assignee_id = reference("app_user.user_id", nullable=True)
    due_date = Column(Date)
    effective_on = Column(Date)
    assessment_scope = json_object()
    is_simulated = Column(Boolean, nullable=False, server_default=text("true"))
    deleted_at = Column(DateTime(timezone=True))
    created_at = timestamp()
    updated_at = timestamp()
    version = version()
    __table_args__ = (
        Index("ix_task_assignee_status", "assignee_id", "status", text("updated_at DESC"), postgresql_where=text("deleted_at IS NULL")),
        Index("ix_task_profile", "profile_id"),
        enum_check("status", TASK_STATUSES, "ck_task_status"),
        enum_check("priority", "LOW MEDIUM HIGH URGENT", "ck_task_priority"),
        enum_check("measure_type", "MARKING_MAINTENANCE SIGNAL_REVIEW PEDESTRIAN_FACILITY_REVIEW FIELD_SURVEY OTHER", "ck_task_measure"),
        CheckConstraint("version > 0 AND btrim(title) <> '' AND btrim(description) <> ''", name="ck_task_fields"),
        CheckConstraint("is_simulated", name="ck_task_simulated"),
        CheckConstraint("deleted_at IS NULL OR status = 'DRAFT'", name="ck_task_draft_delete"),
        hash_check("request_hash", "ck_task_request_hash"),
    )


class TaskHistory(Base):
    __tablename__ = "task_history"
    history_id = internal_id()
    task_id = reference("governance_task.task_id")
    sequence_no = Column(Integer, nullable=False)
    request_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    request_hash = Column(String(64), nullable=False)
    event_type = Column(String(30), nullable=False)
    from_status = Column(String(30))
    to_status = Column(String(30), nullable=False)
    actor_id = reference("app_user.user_id")
    note = Column(Text, nullable=False)
    changed_fields = json_object()
    created_at = timestamp()
    __table_args__ = (
        UniqueConstraint("task_id", "sequence_no", name="uq_history_sequence"),
        enum_check("event_type", "CREATE EDIT PUBLISH ASSIGN START PROGRESS SUBMIT APPROVE REJECT CANCEL DELETE_DRAFT", "ck_history_event"),
        enum_check("from_status", TASK_STATUSES, "ck_history_from"),
        enum_check("to_status", TASK_STATUSES, "ck_history_to"),
        CheckConstraint("sequence_no > 0 AND btrim(note) <> ''", name="ck_history_fields"),
        hash_check("request_hash", "ck_history_request_hash"),
    )


class DataIssue(Base):
    __tablename__ = "data_issue"
    issue_id = internal_id()
    batch_id = reference("import_batch.batch_id")
    raw_record_id = reference("raw_record.raw_record_id", nullable=True)
    issue_code = Column(String(50), nullable=False)
    severity = Column(String(10), nullable=False)
    field_name = Column(Text)
    description = Column(Text, nullable=False)
    status = Column(String(20), nullable=False)
    resolution_note = Column(Text)
    resolved_by = reference("app_user.user_id", nullable=True)
    resolved_at = Column(DateTime(timezone=True))
    created_at = timestamp()
    __table_args__ = (
        UniqueConstraint("batch_id", "raw_record_id", "issue_code", "field_name", name="uq_issue_diagnostic", postgresql_nulls_not_distinct=True),
        Index("ix_issue_batch_status", "batch_id", "status"),
        enum_check("severity", "INFO WARNING ERROR", "ck_issue_severity"),
        enum_check("status", "OPEN ACKNOWLEDGED RESOLVED", "ck_issue_status"),
        CheckConstraint("status <> 'RESOLVED' OR (resolved_by IS NOT NULL AND resolved_at IS NOT NULL AND resolution_note IS NOT NULL AND btrim(resolution_note) <> '')", name="ck_issue_resolution"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    audit_id = internal_id()
    actor_id = reference("app_user.user_id", nullable=True)
    action = Column(String(60), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(Text)
    request_id = Column(UUID(as_uuid=True))
    details = json_object()
    created_at = timestamp()


class DatasetState(Base):
    __tablename__ = "dataset_state"
    state_id = Column(SmallInteger, primary_key=True)
    revision = Column(BigInteger, nullable=False, server_default=text("0"))
    updated_at = timestamp()
    last_change_note = Column(Text, nullable=False)
    __table_args__ = (CheckConstraint("state_id = 1 AND revision >= 0", name="ck_dataset_singleton"),)
