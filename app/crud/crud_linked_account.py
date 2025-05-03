import uuid
import logging

from sqlalchemy import func, TEXT, cast
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.models.linked_account import LinkedAccount

logger = logging.getLogger(__name__)


def get_linked_account(db: Session, account_id: uuid.UUID) -> LinkedAccount | None:
    """Gets a linked account by its ID."""
    return db.query(LinkedAccount).filter(LinkedAccount.id == account_id).first()


async def aget_linked_account(db: AsyncSession, account_id: uuid.UUID) -> LinkedAccount | None:
    """Gets a linked account by its ID asynchronously."""
    stmt = select(LinkedAccount).filter(LinkedAccount.id == account_id)
    result = await db.execute(stmt)
    return result.scalars().first()


def get_linked_account_by_user_and_shop(
    db: Session, *, user_id: uuid.UUID, shop_domain: str
) -> LinkedAccount | None:
    """Gets a Shopify linked account by user ID and shop domain."""
    return (
        db.query(LinkedAccount)
        .filter(
            LinkedAccount.user_id == user_id,
            LinkedAccount.account_type == "shopify",
            LinkedAccount.account_name == shop_domain,
        )
        .first()
    )


async def aget_linked_account_by_user_and_shop(
    db: AsyncSession, *, user_id: uuid.UUID, shop_domain: str
) -> LinkedAccount | None:
    """Gets a Shopify linked account by user ID and shop domain asynchronously."""
    stmt = select(LinkedAccount).filter(
        LinkedAccount.user_id == user_id,
        LinkedAccount.account_type == "shopify",
        LinkedAccount.account_name == shop_domain,
    )
    result = await db.execute(stmt)
    return result.scalars().first()


def save_shopify_account(
    db: Session,
    *,
    user_id: uuid.UUID,
    shop_domain: str,
    encrypted_token,
    scopes: str,
) -> LinkedAccount:
    """Saves (creates or updates) a Shopify linked account without committing.

    Accepts the pre-encrypted token.
    Flushes and refreshes the object before returning.
    """
    existing_account = get_linked_account_by_user_and_shop(
        db, user_id=user_id, shop_domain=shop_domain
    )

    if existing_account:
        # Update existing account
        existing_account.encrypted_credentials = encrypted_token
        existing_account.scopes = scopes
        existing_account.status = 'active'
        db_obj = existing_account
    else:
        # Create new account
        db_obj = LinkedAccount(
            user_id=user_id,
            account_type="shopify",
            account_name=shop_domain,
            encrypted_credentials=encrypted_token,
            scopes=scopes,
            status='active', # Set status on creation
        )
        db.add(db_obj)

    db.flush()
    db.refresh(db_obj)
    return db_obj


def get_decrypted_token_for_shopify_account(
    db: Session, *, user_id: uuid.UUID, shop_domain: str
) -> str | None:
    """Retrieves and decrypts the access token for a specific Shopify account."""
    try:
        decrypted_token = (
            db.query(
                cast(
                    func.pgp_sym_decrypt(
                        LinkedAccount.encrypted_credentials, settings.PGCRYPTO_SYM_KEY
                    ),
                    TEXT,
                )
            )
            .filter(
                LinkedAccount.user_id == user_id,
                LinkedAccount.account_type == "shopify",
                LinkedAccount.account_name == shop_domain,
            )
            .scalar()
        )
        return decrypted_token
    except Exception:
        logger.exception(
            f"Error decrypting Shopify credentials for user {user_id}, shop {shop_domain}"
        ) # Use logger.exception
        return None


async def aget_decrypted_token_for_shopify_account(
    db: AsyncSession, *, user_id: uuid.UUID, shop_domain: str
) -> str | None:
    """Retrieves and decrypts the access token for a specific Shopify account asynchronously."""
    try:
        # Construct the decryption query
        decrypt_stmt = select(
            cast(
                func.pgp_sym_decrypt(
                    LinkedAccount.encrypted_credentials, settings.PGCRYPTO_SYM_KEY
                ),
                TEXT,
            )
        ).filter(
            LinkedAccount.user_id == user_id,
            LinkedAccount.account_type == "shopify",
            LinkedAccount.account_name == shop_domain,
        )
        # Execute asynchronously
        result = await db.execute(decrypt_stmt)
        decrypted_token = result.scalar_one_or_none()
        return decrypted_token
    except Exception as e:
        logger.error(
            f"Error during async decryption for user {user_id}, shop {shop_domain}: {e}",
            exc_info=True
        )
        return None


# New function to get first shopify account for a user
async def get_first_shopify_account_for_user(db: AsyncSession, user_id: uuid.UUID) -> LinkedAccount | None:
    """Fetches the first active Shopify linked account for a given user asynchronously."""
    stmt = select(LinkedAccount).filter(
        LinkedAccount.user_id == user_id,
        LinkedAccount.account_type == "shopify",
        LinkedAccount.status == 'active' # Assuming status field exists
    ).order_by(LinkedAccount.created_at.asc()).limit(1)
    result = await db.execute(stmt)
    return result.scalars().first()


async def asave_shopify_account(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    shop_domain: str,
    encrypted_token,
    scopes: str,
) -> LinkedAccount:
    """Saves (creates or updates) a Shopify linked account asynchronously without committing.

    Accepts the pre-encrypted token.
    Flushes and refreshes the object before returning.
    """
    existing_account = await aget_linked_account_by_user_and_shop(
        db, user_id=user_id, shop_domain=shop_domain
    )

    if existing_account:
        # Update existing account
        existing_account.encrypted_credentials = encrypted_token
        existing_account.scopes = scopes
        existing_account.status = 'active'
        db_obj = existing_account
    else:
        # Create new account
        db_obj = LinkedAccount(
            user_id=user_id,
            account_type="shopify",
            account_name=shop_domain,
            encrypted_credentials=encrypted_token,
            scopes=scopes,
            status='active', # Set status on creation
        )
        db.add(db_obj)

    await db.flush() # Flush to ensure persistence before returning
    await db.refresh(db_obj)
    return db_obj


# Add get_multi, remove functions later if needed 