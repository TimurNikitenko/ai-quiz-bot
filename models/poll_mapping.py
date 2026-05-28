from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from models.base import Base, TimeStampMixin

class PollMapping(Base, TimeStampMixin):
    __tablename__ = "poll_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    poll_id: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    quiz_id: Mapped[int] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False
    )
    correct_option_id: Mapped[int] = mapped_column(Integer, nullable=False)
