import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Text, func
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


# Enum for AnalysisRequest status
class AnalysisRequestStatus(enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisRequest(Base):
    __tablename__ = "analysis_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    prompt = Column(Text, nullable=False)
    status = Column(
        SQLAlchemyEnum(AnalysisRequestStatus),
        nullable=False,
        default=AnalysisRequestStatus.PENDING,
        index=True,
    )
    result_summary = Column(Text)  # High-level summary/answer
    result_data = Column(JSONB)  # Detailed data, charts, etc.
    agent_state = Column(JSONB)  # For LangGraph state persistence
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at = Column(DateTime(timezone=True))

    # Relationship to User
    user = relationship("User", back_populates="analysis_requests")
    # Relationship to AgentTasks
    agent_tasks = relationship(
        "AgentTask", back_populates="analysis_request", cascade="all, delete-orphan"
    )
    # Relationship to ProposedActions
    proposed_actions = relationship(
        "ProposedAction",
        back_populates="analysis_request",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<AnalysisRequest(id={self.id}, user_id={self.user_id}, status='{self.status.value}')>"
