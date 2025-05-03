from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.config import settings  # For default model values
from app.database import Base


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)

    # Preferred LLM models - nullable, fallback to defaults from settings
    preferred_planner_model = Column(String(255), nullable=True)
    preferred_aggregator_model = Column(String(255), nullable=True)
    preferred_tool_model = Column(String(255), nullable=True)
    preferred_creative_model = Column(String(255), nullable=True)

    # Relationship back to User (one-to-one)
    user = relationship("User", back_populates="preferences")

    def __repr__(self):
        return f"<UserPreferences(user_id={self.user_id})>"

    # Helper methods to get effective model, falling back to defaults
    def get_effective_planner_model(self) -> str:
        return self.preferred_planner_model or settings.DEFAULT_PLANNER_MODEL

    def get_effective_aggregator_model(self) -> str:
        return self.preferred_aggregator_model or settings.DEFAULT_AGGREGATOR_MODEL

    def get_effective_tool_model(self) -> str:
        return self.preferred_tool_model or settings.DEFAULT_TOOL_MODEL

    def get_effective_creative_model(self) -> str:
        return self.preferred_creative_model or settings.DEFAULT_CREATIVE_MODEL
