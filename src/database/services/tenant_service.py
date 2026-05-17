"""
📁 File: src/database/services/tenant_service.py
Layer: Database (Infrastructure)
Purpose: Tenant CRUD operations
Depends on: src/database/models, src/database/session
Used by: API routes, Layer 4 (Platform)

Handles all tenant-related database operations.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from src.database.models import Tenant, TenantCreate, TenantUpdate
from src.shared.errors import TenantNotFoundError
from src.shared.logger import get_logger

logger = get_logger(__name__)


class TenantService:
    """Service for tenant database operations."""
    
    @staticmethod
    async def create_tenant(
        session: AsyncSession,
        tenant_data: TenantCreate,
    ) -> Tenant:
        """
        Create a new tenant.
        
        Args:
            session: Database session
            tenant_data: Tenant creation data
            
        Returns:
            Created tenant
        """
        tenant = Tenant(**tenant_data.model_dump())
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
        
        logger.info("tenant_created", tenant_id=str(tenant.id), slug=tenant.slug)
        
        return tenant
    
    @staticmethod
    async def get_tenant(
        session: AsyncSession,
        tenant_id: UUID,
    ) -> Tenant:
        """
        Get tenant by ID.
        
        Args:
            session: Database session
            tenant_id: Tenant UUID
            
        Returns:
            Tenant
            
        Raises:
            TenantNotFoundError: If tenant not found
        """
        result = await session.execute(
            select(Tenant).where(
                Tenant.id == tenant_id,
                Tenant.deleted_at.is_(None),
            )
        )
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            raise TenantNotFoundError(str(tenant_id))
        
        return tenant
    
    @staticmethod
    async def get_tenant_by_slug(
        session: AsyncSession,
        slug: str,
    ) -> Optional[Tenant]:
        """
        Get tenant by slug.
        
        Args:
            session: Database session
            slug: Tenant slug
            
        Returns:
            Tenant or None
        """
        result = await session.execute(
            select(Tenant).where(
                Tenant.slug == slug,
                Tenant.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def list_tenants(
        session: AsyncSession,
        skip: int = 0,
        limit: int = 100,
        only_active: bool = True,
    ) -> list[Tenant]:
        """
        List tenants with pagination.
        
        Args:
            session: Database session
            skip: Number of records to skip
            limit: Maximum number of records to return
            only_active: Only return active tenants
            
        Returns:
            List of tenants
        """
        query = select(Tenant).where(Tenant.deleted_at.is_(None))
        
        if only_active:
            query = query.where(Tenant.is_active.is_(True))
        
        query = query.offset(skip).limit(limit)
        
        result = await session.execute(query)
        return list(result.scalars().all())
    
    @staticmethod
    async def update_tenant(
        session: AsyncSession,
        tenant_id: UUID,
        tenant_data: TenantUpdate,
    ) -> Tenant:
        """
        Update tenant.
        
        Args:
            session: Database session
            tenant_id: Tenant UUID
            tenant_data: Update data
            
        Returns:
            Updated tenant
            
        Raises:
            TenantNotFoundError: If tenant not found
        """
        tenant = await TenantService.get_tenant(session, tenant_id)
        
        # Update only provided fields
        for field, value in tenant_data.model_dump(exclude_unset=True).items():
            setattr(tenant, field, value)
        
        session.add(tenant)
        await session.commit()
        await session.refresh(tenant)
        
        logger.info("tenant_updated", tenant_id=str(tenant_id))
        
        return tenant
    
    @staticmethod
    async def delete_tenant(
        session: AsyncSession,
        tenant_id: UUID,
        hard_delete: bool = False,
    ) -> None:
        """
        Delete tenant (soft or hard delete).
        
        Args:
            session: Database session
            tenant_id: Tenant UUID
            hard_delete: If True, permanently delete. If False, soft delete.
            
        Raises:
            TenantNotFoundError: If tenant not found
        """
        tenant = await TenantService.get_tenant(session, tenant_id)
        
        if hard_delete:
            await session.delete(tenant)
            logger.info("tenant_hard_deleted", tenant_id=str(tenant_id))
        else:
            tenant.soft_delete()
            session.add(tenant)
            logger.info("tenant_soft_deleted", tenant_id=str(tenant_id))
        
        await session.commit()
