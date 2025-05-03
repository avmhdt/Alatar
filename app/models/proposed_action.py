import enum
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
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


# Enum for ProposedAction status
class ProposedActionStatus(enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"


class ProposedAction(Base):
    __tablename__ = "proposed_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("analysis_requests.id"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    linked_account_id = Column(
        UUID(as_uuid=True), ForeignKey("linked_accounts.id"), nullable=False, index=True
    )
    action_type = Column(
        String(100), nullable=False
    )  # e.g., 'shopify_update_product', 'shopify_create_discount'
    description = Column(
        Text, nullable=False
    )  # Human-readable description of the proposed action
    parameters = Column(
        JSONB
    )  # Parameters needed to execute the action (e.g., product_id, new_price)
    status = Column(
        SQLAlchemyEnum(ProposedActionStatus),
        nullable=False,
        default=ProposedActionStatus.PROPOSED,
        index=True,
    )
    execution_logs = Column(Text)  # Logs or error messages from execution attempt
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    approved_at = Column(DateTime(timezone=True))
    executed_at = Column(DateTime(timezone=True))

    # Relationships
    analysis_request = relationship(
        "AnalysisRequest", back_populates="proposed_actions"
    )
    # Optional direct relationships
    # user = relationship("User")
    # linked_account = relationship("LinkedAccount")

    def __repr__(self):
        return f"<ProposedAction(id={self.id}, analysis_request_id={self.analysis_request_id}, type='{self.action_type}', status='{self.status.value}')>"
