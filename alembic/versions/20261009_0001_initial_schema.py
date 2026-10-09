"""Create initial logistics schema.

Revision ID: 20261009_0001
Revises:
"""

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision = "20261009_0001"
down_revision = None
branch_labels = None
depends_on = None

vehicle_type = sa.Enum("refrigerated_truck", "van", "truck", name="vehicletypeenum")
booking_status = sa.Enum(
    "pending", "scheduled", "confirmed", "en_route", "goods_collected",
    "delivered", "cancelled", "completed", name="bookingstatusenum",
)
role_type = sa.Enum("admin", "user", "driver", name="roleenum")


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", role_type, nullable=False, unique=True),
    )
    op.create_index("ix_roles_id", "roles", ["id"])
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("phone_number", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("payment_info", sa.String()),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name, columns in (("ix_users_id", ["id"]), ("ix_users_email", ["email"]),
                          ("ix_users_phone_number", ["phone_number"])):
        op.create_index(name, "users", columns)
    op.create_table(
        "drivers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("phone_number", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("vehicle_type", vehicle_type, nullable=False),
        sa.Column("car_info", sa.String()),
        sa.Column("location", Geometry("POINT", spatial_index=False)),
        sa.Column("is_available", sa.Boolean()),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id")),
    )
    for name, columns in (("ix_drivers_id", ["id"]), ("ix_drivers_email", ["email"]),
                          ("ix_drivers_phone_number", ["phone_number"]),
                          ("ix_drivers_vehicle_type", ["vehicle_type"])):
        op.create_index(name, "drivers", columns)
    op.create_index("idx_drivers_location", "drivers", ["location"], postgresql_using="gist")
    op.create_table(
        "pricing",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vehicle_type", sa.String(), nullable=False),
        sa.Column("base_fare", sa.Float(), nullable=False),
        sa.Column("cost_per_km", sa.Float(), nullable=False),
    )
    op.create_index("ix_pricing_id", "pricing", ["id"])
    op.create_table(
        "analytics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
    )
    op.create_index("ix_analytics_id", "analytics", ["id"])
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("drivers.id")),
        sa.Column("pickup_location", Geometry("POINT", spatial_index=False)),
        sa.Column("dropoff_location", Geometry("POINT", spatial_index=False)),
        sa.Column("vehicle_type", vehicle_type),
        sa.Column("price", sa.Float()),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("status", booking_status, nullable=False),
        sa.Column("scheduled_time", sa.DateTime()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
    )
    for name, columns in (("ix_bookings_id", ["id"]),
                          ("ix_bookings_driver_id", ["driver_id"]),
                          ("idx_booking_driver_id", ["driver_id"]),
                          ("ix_bookings_status", ["status"]),
                          ("idx_booking_status", ["status"])):
        op.create_index(name, "bookings", columns)
    op.create_index("idx_bookings_pickup_location", "bookings", ["pickup_location"], postgresql_using="gist")
    op.create_index("idx_bookings_dropoff_location", "bookings", ["dropoff_location"], postgresql_using="gist")
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vehicle_type", vehicle_type, nullable=False),
        sa.Column("make", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("license_plate", sa.String(), nullable=False, unique=True),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String()),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("drivers.id")),
    )
    for name, columns in (("ix_vehicles_id", ["id"]),
                          ("ix_vehicles_vehicle_type", ["vehicle_type"]),
                          ("ix_vehicles_license_plate", ["license_plate"])):
        op.create_index(name, "vehicles", columns)
    op.create_table(
        "booking_status_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("status", booking_status, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_booking_status_history_id", "booking_status_history", ["id"])
    op.create_table(
        "maintenance_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id"), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.String()),
    )
    op.create_index("ix_maintenance_periods_id", "maintenance_periods", ["id"])


def downgrade():
    for table in ("maintenance_periods", "booking_status_history", "vehicles",
                  "bookings", "analytics", "pricing", "drivers", "users", "roles"):
        op.drop_table(table)
    booking_status.drop(op.get_bind(), checkfirst=True)
    vehicle_type.drop(op.get_bind(), checkfirst=True)
    role_type.drop(op.get_bind(), checkfirst=True)
