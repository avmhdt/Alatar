from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union, TYPE_CHECKING
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session

# Import the actual Base for runtime usage
from app.database import Base

# Use Any instead of a bound parameter to avoid type issues
ModelType = TypeVar("ModelType")  # No bound constraint
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: Type[ModelType]):
        """
        CRUD object with default methods to Create, Read, Update, Delete (CRUD).
        
        **Parameters**
        
        * `model`: A SQLAlchemy model class
        * `schema`: A Pydantic model (schema) class
        """
        self.model = model

    def get(self, db: Session, id: UUID) -> Optional[ModelType]:
        return db.query(self.model).filter(self.model.id == id).first()

    async def aget(self, db: AsyncSession, id: UUID) -> Optional[ModelType]:
        result = await db.execute(select(self.model).filter(self.model.id == id))
        return result.scalars().first()

    def get_multi(self, db: Session, *, skip: int = 0, limit: int = 100) -> List[ModelType]:
        return db.query(self.model).offset(skip).limit(limit).all()

    async def aget_multi(self, db: AsyncSession, *, skip: int = 0, limit: int = 100) -> List[ModelType]:
        result = await db.execute(select(self.model).offset(skip).limit(limit))
        return result.scalars().all()

    def create(self, db: Session, *, obj_in: CreateSchemaType) -> ModelType:
        obj_in_data = jsonable_encoder(obj_in)
        db_obj = self.model(**obj_in_data)
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return db_obj

    async def acreate(self, db: AsyncSession, *, obj_in: CreateSchemaType) -> ModelType:
        obj_in_data = jsonable_encoder(obj_in)
        db_obj = self.model(**obj_in_data)
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    def update(
        self,
        db: Session,
        *,
        db_obj: ModelType,
        obj_in: Union[UpdateSchemaType, Dict[str, Any]]
    ) -> ModelType:
        obj_data = jsonable_encoder(db_obj)
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.dict(exclude_unset=True)
        for field in obj_data:
            if field in update_data:
                setattr(db_obj, field, update_data[field])
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return db_obj

    async def aupdate(
        self,
        db: AsyncSession,
        *,
        db_obj: ModelType,
        obj_in: Union[UpdateSchemaType, Dict[str, Any]]
    ) -> ModelType:
        obj_data = jsonable_encoder(db_obj)
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.dict(exclude_unset=True)
        for field in obj_data:
            if field in update_data:
                setattr(db_obj, field, update_data[field])
        db.add(db_obj)
        await db.flush()
        await db.refresh(db_obj)
        return db_obj

    def remove(self, db: Session, *, id: UUID) -> ModelType:
        obj = db.query(self.model).get(id)
        db.delete(obj)
        db.flush()
        return obj

    async def aremove(self, db: AsyncSession, *, id: UUID) -> ModelType:
        result = await db.execute(select(self.model).filter(self.model.id == id))
        obj = result.scalars().first()
        await db.delete(obj)
        await db.flush()
        return obj 