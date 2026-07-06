from sqlalchemy import String, Text, Integer, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, JSON 
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from models.base import Base, TimeStampMixin


class Digest(Base, TimeStampMixin):
    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(primary_key=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facts: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    posts = relationship("Post", back_populates="digest")
    quiz = relationship("Quiz", back_populates="digest", uselist=False)
    is_published: Mapped[bool] = mapped_column(default=False, server_default="false")

    published_records = relationship("PublishedDigest", back_populates="digest", cascade="all, delete-orphan")


class PublishedDigest(Base, TimeStampMixin):
    __tablename__ = "published_digests"

    id: Mapped[int] = mapped_column(primary_key=True)
    digest_id: Mapped[int] = mapped_column(ForeignKey("digests.id", ondelete="CASCADE"), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(100), nullable=False)

    digest = relationship("Digest", back_populates="published_records")


