from datetime import datetime
from enum import Enum as PyEnum

from geoalchemy2 import Geometry
from sqlalchemy import (JSON, Boolean, Column, DateTime, Enum, Float,
                        ForeignKey, Index, Integer, String)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class VehicleTypeEnum(str, PyEnum):
    refrigerated_truck = "refrigerated_truck"
    van = "van"
    truck = "truck"


class BookingStatusEnum(str, PyEnum):
    pending = "pending"
    scheduled = "scheduled"
    confirmed = "confirmed"
    en_route = "en_route"
    goods_collected = "goods_collected"
    delivered = "delivered"
    cancelled = "cancelled"
    completed = "completed"


class RoleEnum(str, PyEnum):
    admin = "admin"
    user = "user"
    driver = "driver"


# For RBAC
class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(Enum(RoleEnum), unique=True, nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    phone_number = Column(String, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    payment_info = Column(
        String, nullable=True
    )  # Assuming payment info is stored as a string
    bookings = relationship(
        "Booking", back_populates="user", cascade="all, delete-orphan"
    )
    role_id = Column(Integer, ForeignKey("roles.id"))
    role = relationship("Role")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Driver(Base):
    __tablename__ = "drivers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    phone_number = Column(String, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    vehicle_type = Column(Enum(VehicleTypeEnum), nullable=False, index=True)
    car_info = Column(String, nullable=True)
    location = Column(Geometry("POINT"), nullable=True)
    is_available = Column(Boolean, default=True)
    role_id = Column(Integer, ForeignKey("roles.id"))
    role = relationship("Role")
    bookings = relationship("Booking", back_populates="driver")


class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True, index=True)
    vehicle_type = Column(Enum(VehicleTypeEnum), nullable=False, index=True)
    make = Column(String, nullable=False)
    model = Column(String, nullable=False)
    year = Column(Integer, nullable=False)
    license_plate = Column(String, nullable=False, unique=True, index=True)
    capacity = Column(Integer, nullable=False)
    status = Column(String, default="available")
    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=True)
    driver = relationship("Driver")


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    driver_id = Column(Integer, ForeignKey("drivers.id"), nullable=True, index=True)
    pickup_location = Column(Geometry("POINT"))
    dropoff_location = Column(Geometry("POINT"))
    vehicle_type = Column(Enum(VehicleTypeEnum))
    price = Column(Float)
    date = Column(DateTime, nullable=False)
    status = Column(
        Enum(BookingStatusEnum),
        nullable=False,
        default=BookingStatusEnum.pending,
        index=True,
    )
    scheduled_time = Column(DateTime, nullable=True)
    user = relationship("User", back_populates="bookings")
    driver = relationship("Driver", back_populates="bookings")
    status_history = relationship(
        "BookingStatusHistory", back_populates="booking", cascade="all, delete-orphan"
    )
    version = Column(Integer, nullable=False, server_default="0")
    __mapper_args__ = {"version_id_col": version}


# Create indexes for frequently queried fields
Index("idx_booking_status", Booking.status)
Index("idx_booking_driver_id", Booking.driver_id)


class Pricing(Base):
    __tablename__ = "pricing"
    id = Column(Integer, primary_key=True, index=True)
    vehicle_type = Column(String, nullable=False)
    base_fare = Column(Float, nullable=False)
    cost_per_km = Column(Float, nullable=False)


class Analytics(Base):
    __tablename__ = "analytics"
    id = Column(Integer, primary_key=True, index=True)
    metric = Column(String, nullable=False)
    value = Column(Float, nullable=False)


class MaintenancePeriod(Base):
    __tablename__ = "maintenance_periods"
    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    reason = Column(String, nullable=True)

    vehicle = relationship("Vehicle")


class BookingStatusHistory(Base):
    __tablename__ = "booking_status_history"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    status = Column(Enum(BookingStatusEnum), nullable=False)
    timestamp = Column(DateTime, nullable=False)

    booking = relationship("Booking", back_populates="status_history")
