from sqlalchemy import String, Text, DateTime, Integer, JSON, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, JSON 
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from datetime import datetime
from models.base import Base, TimeStampMixin


class Post(Base, TimeStampMixin):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    digest_id: Mapped[int] = mapped_column(ForeignKey("digests.id"), nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    post_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    is_ad_or_trash: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    facts: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    questions: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    llm_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    model_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    digest = relationship("Digest", back_populates="posts")
