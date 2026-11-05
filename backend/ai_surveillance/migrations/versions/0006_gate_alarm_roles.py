"""Roles, gate lines and crossings, alerts, event footage, face attribute estimates.

Revision ID: 0006_gate_alarm_roles
Revises: 0005_recognition
Create Date: 2026-11-05

Existing accounts become administrators (they were the only kind). Every other new column is
nullable or has a server default, and is added in place (SQLite ADD COLUMN): no existing table
is rebuilt, so no rows are copied or lost.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_gate_alarm_roles"
down_revision = "0005_recognition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("admin_users", recreate="never") as batch:
        batch.add_column(sa.Column("role", sa.String(16), nullable=False, server_default="admin"))
        batch.add_column(sa.Column("disabled", sa.Boolean, nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("captures", recreate="never") as batch:
        batch.add_column(sa.Column("source", sa.String(64), nullable=True))
        batch.add_column(sa.Column("clip_start", sa.Float, nullable=True))
        batch.add_column(sa.Column("clip_end", sa.Float, nullable=True))
    op.create_index("ix_captures_source", "captures", ["source"])
    with op.batch_alter_table("face_detections", recreate="never") as batch:
        batch.add_column(sa.Column("attributes", sa.Text, nullable=True))
        batch.add_column(sa.Column("liveness", sa.Text, nullable=True))

    op.create_table(
        "gate_lines",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("camera", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("x1", sa.Float, nullable=False),
        sa.Column("y1", sa.Float, nullable=False),
        sa.Column("x2", sa.Float, nullable=False),
        sa.Column("y2", sa.Float, nullable=False),
        sa.Column("in_side", sa.String(8), nullable=False),
        sa.Column("record_exits", sa.Boolean, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("alarm_on_unauthorized", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("cooldown_seconds", sa.Integer, nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "gate_crossings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("line_id", sa.String(32), sa.ForeignKey("gate_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera", sa.String(64), nullable=False),
        sa.Column("frigate_event_id", sa.String(30), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("crossed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("frame_time", sa.Float, nullable=False),
        sa.Column("point_x", sa.Float, nullable=False),
        sa.Column("point_y", sa.Float, nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(48), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=True),
        sa.Column("similarity", sa.Float, nullable=True),
        sa.Column("person_id", sa.String(32), sa.ForeignKey("people.id", ondelete="SET NULL"), nullable=True),
        sa.Column("face_event_id", sa.String(32), sa.ForeignKey("face_events.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("line_id", "frigate_event_id", "sequence", name="uq_gate_crossing"),
    )
    for column in ("line_id", "camera", "frigate_event_id", "crossed_at", "verdict", "face_event_id"):
        op.create_index(f"ix_gate_crossings_{column}", "gate_crossings", [column])
    op.create_table(
        "alerts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("camera", sa.String(64), nullable=True),
        sa.Column("crossing_id", sa.String(32), sa.ForeignKey("gate_crossings.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("detail", sa.String(500), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("acknowledged_by", sa.String(64), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alarm", sa.String(16), nullable=False),
        sa.Column("delivery", sa.String(500), nullable=True),
    )
    for column in ("created_at", "crossing_id", "status"):
        op.create_index(f"ix_alerts_{column}", "alerts", [column])


def downgrade() -> None:
    # Drops alerts, crossings and lines; accounts lose their roles (all become administrators again
    # by the meaning of the old schema), captures lose their event link, faces their estimates.
    op.drop_table("alerts")
    op.drop_table("gate_crossings")
    op.drop_table("gate_lines")
    op.drop_index("ix_captures_source", "captures")
    for table, column in (("face_detections", "liveness"), ("face_detections", "attributes"),
                          ("captures", "clip_end"), ("captures", "clip_start"), ("captures", "source"),
                          ("admin_users", "password_changed_at"), ("admin_users", "disabled"),
                          ("admin_users", "role")):
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
