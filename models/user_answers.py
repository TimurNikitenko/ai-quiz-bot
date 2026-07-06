from sqlalchemy import String, Integer, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base

class UserAnswer(Base):
    __tablename__ = "user_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    ) 
    quiz_id: Mapped[int] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False
    )
    
    telegram_poll_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)

    user = relationship("User", back_populates="answers")
    quiz = relationship("Quiz") 