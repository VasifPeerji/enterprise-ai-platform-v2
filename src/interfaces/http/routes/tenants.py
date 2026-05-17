"""
📁 File: src/interfaces/http/routes/tenants.py
Layer: Interfaces (HTTP)
Purpose: Tenant management API endpoints
Depends on: src/database
Used by: Admin users, platform management

Endpoints for managing tenants (multi-tenancy).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import TenantCreate, TenantRead, TenantUpdate
from src.database.services import TenantService
from src.database.session import get_session
from src.shared.errors import TenantNotFoundError
from src.shared.logger import get_logger

# Initialize
router = APIRouter(prefix="/tenants", tags=["Tenants"])
logger = get_logger(__name__)


@router.post(
    "",
    response_model=TenantRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Tenant",
    description="Create a new tenant organization",
)
async def create_tenant(
    tenant_data: TenantCreate,
    session: AsyncSession = Depends(get_session),
) -> TenantRead:
    """
    Create a new tenant.
    
    Args:
        tenant_data: Tenant creation data
        session: Database session (injected)
        
    Returns:
        Created tenant
    """
    logger.info("create_tenant_requested", name=tenant_data.name, slug=tenant_data.slug)
    
    try:
        tenant = await TenantService.create_tenant(session, tenant_data)
        
        return TenantRead(
            id=str(tenant.id),
            name=tenant.name,
            slug=tenant.slug,
            is_active=tenant.is_active,
            monthly_budget_usd=tenant.monthly_budget_usd,
            monthly_request_limit=tenant.monthly_request_limit,
            allowed_models=tenant.allowed_models,
            default_model_id=tenant.default_model_id,
            enable_ollama=tenant.enable_ollama,
            contact_email=tenant.contact_email,
            contact_name=tenant.contact_name,
            metadata=tenant.metadata,
            created_at=tenant.created_at.isoformat(),
            updated_at=tenant.updated_at.isoformat(),
        )
    
    except Exception as e:
        logger.error("create_tenant_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create tenant: {str(e)}",
        )


@router.get(
    "/{tenant_id}",
    response_model=TenantRead,
    summary="Get Tenant",
    description="Get tenant by ID",
)
async def get_tenant(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TenantRead:
    """
    Get tenant by ID.
    
    Args:
        tenant_id: Tenant UUID
        session: Database session (injected)
        
    Returns:
        Tenant details
        
    Raises:
        HTTPException: If tenant not found
    """
    logger.info("get_tenant_requested", tenant_id=str(tenant_id))
    
    try:
        tenant = await TenantService.get_tenant(session, tenant_id)
        
        return TenantRead(
            id=str(tenant.id),
            name=tenant.name,
            slug=tenant.slug,
            is_active=tenant.is_active,
            monthly_budget_usd=tenant.monthly_budget_usd,
            monthly_request_limit=tenant.monthly_request_limit,
            allowed_models=tenant.allowed_models,
            default_model_id=tenant.default_model_id,
            enable_ollama=tenant.enable_ollama,
            contact_email=tenant.contact_email,
            contact_name=tenant.contact_name,
            metadata=tenant.metadata,
            created_at=tenant.created_at.isoformat(),
            updated_at=tenant.updated_at.isoformat(),
        )
    
    except TenantNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    
    except Exception as e:
        logger.error("get_tenant_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tenant: {str(e)}",
        )


@router.get(
    "",
    response_model=list[TenantRead],
    summary="List Tenants",
    description="List all tenants with pagination",
)
async def list_tenants(
    skip: int = 0,
    limit: int = 100,
    only_active: bool = True,
    session: AsyncSession = Depends(get_session),
) -> list[TenantRead]:
    """
    List tenants with pagination.
    
    Args:
        skip: Number of records to skip
        limit: Maximum number of records
        only_active: Only return active tenants
        session: Database session (injected)
        
    Returns:
        List of tenants
    """
    logger.info("list_tenants_requested", skip=skip, limit=limit)
    
    try:
        tenants = await TenantService.list_tenants(session, skip, limit, only_active)
        
        return [
            TenantRead(
                id=str(t.id),
                name=t.name,
                slug=t.slug,
                is_active=t.is_active,
                monthly_budget_usd=t.monthly_budget_usd,
                monthly_request_limit=t.monthly_request_limit,
                allowed_models=t.allowed_models,
                default_model_id=t.default_model_id,
                enable_ollama=t.enable_ollama,
                contact_email=t.contact_email,
                contact_name=t.contact_name,
                metadata=t.metadata,
                created_at=t.created_at.isoformat(),
                updated_at=t.updated_at.isoformat(),
            )
            for t in tenants
        ]
    
    except Exception as e:
        logger.error("list_tenants_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tenants: {str(e)}",
        )


@router.patch(
    "/{tenant_id}",
    response_model=TenantRead,
    summary="Update Tenant",
    description="Update tenant details",
)
async def update_tenant(
    tenant_id: UUID,
    tenant_data: TenantUpdate,
    session: AsyncSession = Depends(get_session),
) -> TenantRead:
    """
    Update tenant.
    
    Args:
        tenant_id: Tenant UUID
        tenant_data: Update data
        session: Database session (injected)
        
    Returns:
        Updated tenant
        
    Raises:
        HTTPException: If tenant not found
    """
    logger.info("update_tenant_requested", tenant_id=str(tenant_id))
    
    try:
        tenant = await TenantService.update_tenant(session, tenant_id, tenant_data)
        
        return TenantRead(
            id=str(tenant.id),
            name=tenant.name,
            slug=tenant.slug,
            is_active=tenant.is_active,
            monthly_budget_usd=tenant.monthly_budget_usd,
            monthly_request_limit=tenant.monthly_request_limit,
            allowed_models=tenant.allowed_models,
            default_model_id=tenant.default_model_id,
            enable_ollama=tenant.enable_ollama,
            contact_email=tenant.contact_email,
            contact_name=tenant.contact_name,
            metadata=tenant.metadata,
            created_at=tenant.created_at.isoformat(),
            updated_at=tenant.updated_at.isoformat(),
        )
    
    except TenantNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    
    except Exception as e:
        logger.error("update_tenant_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update tenant: {str(e)}",
        )


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Tenant",
    description="Soft delete a tenant",
)
async def delete_tenant(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """
    Soft delete a tenant.
    
    Args:
        tenant_id: Tenant UUID
        session: Database session (injected)
        
    Raises:
        HTTPException: If tenant not found
    """
    logger.info("delete_tenant_requested", tenant_id=str(tenant_id))
    
    try:
        await TenantService.delete_tenant(session, tenant_id, hard_delete=False)
    
    except TenantNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=e.message,
        )
    
    except Exception as e:
        logger.error("delete_tenant_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete tenant: {str(e)}",
        )
