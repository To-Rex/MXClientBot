from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Bot(Base):
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    token = Column(String, nullable=False, unique=True)
    company_name = Column(String, nullable=True)
    base_url = Column(String, nullable=True)
    one_c_login = Column(String, nullable=True)
    one_c_password = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    users = relationship("User", back_populates="bot", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, nullable=False)
    phone_number = Column(String, nullable=True)
    client_id = Column(String, nullable=True)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    bot = relationship("Bot", back_populates="users")
