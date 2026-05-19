from sqlalchemy import String, BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from .base import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    username: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    global_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    answers = relationship("UserAnswer", back_populates="user", cascade="all, delete-orphan")