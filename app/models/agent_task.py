import enum
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


# Enum for AgentTask status
class AgentTaskStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_requests.id"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )  # Denormalized for easier access/RLS
    task_type = Column(
        String(100), nullable=False
    )  # e.g., 'data_retrieval', 'quantitative_analysis'
    status = Column(
        SQLAlchemyEnum(AgentTaskStatus),
        nullable=False,
        default=AgentTaskStatus.PENDING,
        index=True,
    )
    input_data = Column(JSONB)  # Input parameters for the task
    output_data = Column(JSONB)  # Result of the task
    logs = Column(Text)  # Logs or error messages specific to this task
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # Relationships
    analysis_request = relationship("AnalysisRequest", back_populates="agent_tasks")
    # Optional: Direct relationship to user if needed, though analysis_request provides it
    # user = relationship("User")

    def __repr__(self):
        return f"<AgentTask(id={self.id}, analysis_request_id={self.analysis_request_id}, type='{self.task_type}', status='{self.status.value}')>"
