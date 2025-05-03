import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class CachedShopifyData(Base):
    __tablename__ = "cached_shopify_data"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    linked_account_id = Column(
        UUID(as_uuid=True), ForeignKey("linked_accounts.id"), nullable=False, index=True
    )
    cache_key = Column(
        String(512), nullable=False, index=True
    )  # Unique key for the cached data (e.g., 'products:list:params_hash')
    data = Column(JSONB, nullable=False)  # The cached JSON data from Shopify
    cached_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    expires_at = Column(
        DateTime(timezone=True), nullable=False, index=True
    )  # TTL implemented via this field

    # Optional relationships if needed for querying, but user_id/linked_account_id might be sufficient
    # user = relationship("User")
    # linked_account = relationship("LinkedAccount")

    def __repr__(self):
        return f"<CachedShopifyData(id={self.id}, user_id={self.user_id}, key='{self.cache_key}')>"
