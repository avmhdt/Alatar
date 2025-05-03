import uuid

from sqlalchemy import Column, DateTime, ForeignKey, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class LinkedAccount(Base):
    __tablename__ = "linked_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    account_type = Column(String(50), nullable=False, index=True)  # e.g., 'shopify'
    account_name = Column(String(255))  # e.g., Shopify shop domain or user-given name
    encrypted_credentials = Column(
        LargeBinary, nullable=False
    )  # Store encrypted access token, etc.
    scopes = Column(Text)  # Store granted scopes (comma-separated or JSON)
    # Add status field as per design doc
    status = Column(
        String(50),
        nullable=False,
        default='active',
        index=True
    )
    # Add other metadata as needed (e.g., expiry, refresh token placeholder)
    # expires_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationship to User
    user = relationship("User", back_populates="linked_accounts")

    def __repr__(self):
        return f"<LinkedAccount(id={self.id}, user_id={self.user_id}, type='{self.account_type}')>"
