from sqlalchemy import String, Text, Date, Time, ForeignKey, Integer, Index, JSON
from sqlalchemy.dialects.postgresql import JSONB, JSON as PGJSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from datetime import date, time
from models.base import Base, TimeStampMixin


class Quiz(Base, TimeStampMixin):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    digest_id: Mapped[int] = mapped_column(
        ForeignKey("digests.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    questions: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    digest = relationship("Digest", back_populates="quiz")


