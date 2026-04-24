from datetime import datetime
from enum import StrEnum
from typing import Optional  # Добавлено для корректной типизации

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Numeric, String, func, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class UserRole(StrEnum):
    ADMIN = "admin"
    CLIENT = "client"

class AppointmentStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    # ИЗМЕНЕНО: добавлена поддержка NULL (nullable=True) и тип Optional
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.CLIENT)
    full_name: Mapped[str] = mapped_column(String(255))
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    appointments: Mapped[list["Appointment"]] = relationship(back_populates="client")
    organizations: Mapped[list["Organization"]] = relationship(back_populates="owner")

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship(back_populates="organizations")
    services: Mapped[list["Service"]] = relationship(back_populates="organization")
    masters: Mapped[list["Master"]] = relationship(back_populates="organization", cascade="all, delete-orphan")

class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Numeric(10, 2))

    organization: Mapped["Organization"] = relationship(back_populates="services")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="service")

class Master(Base):
    __tablename__ = "masters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    specialty: Mapped[str | None] = mapped_column(String(255))
    photo_id: Mapped[str | None] = mapped_column(String(255))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))

    organization: Mapped["Organization"] = relationship(back_populates="masters")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="master")

class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    master_id: Mapped[int] = mapped_column(ForeignKey("masters.id", ondelete="CASCADE"))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=True
    )
    custom_client_data: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="CASCADE"))
    datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[AppointmentStatus] = mapped_column(Enum(AppointmentStatus), default=AppointmentStatus.CONFIRMED, index=True)
    
    reminder_24h_sent: Mapped[bool] = mapped_column(default=False, index=True)
    reminder_2h_sent: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    client: Mapped["User"] = relationship(back_populates="appointments")
    service: Mapped["Service"] = relationship(back_populates="appointments")
    master: Mapped["Master"] = relationship(back_populates="appointments")

