import uuid

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    # Add other user fields as needed (e.g., name, is_active)
    # name = Column(String(100))
    # is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    linked_accounts = relationship(
        "LinkedAccount", back_populates="user", cascade="all, delete-orphan"
    )
    analysis_requests = relationship(
        "AnalysisRequest", back_populates="user", cascade="all, delete-orphan"
    )
    # Add relationship to UserPreferences (one-to-one)
    preferences = relationship(
        "UserPreferences",
        back_populates="user",
        uselist=False,  # Important for one-to-one
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}')>"
