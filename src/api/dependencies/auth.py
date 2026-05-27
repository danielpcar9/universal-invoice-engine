from typing import Annotated

from fastapi import Header, HTTPException, status, Depends


async def verify_api_key(
    x_api_key: str = Header(..., description="API Key for tenant authentication"),
) -> dict[str, str]:
    """
    Placeholder for API key authentication.
    Will be implemented with database lookup in Fase 2.
    """
    # TODO: Query database for valid API keys
    if not x_api_key or len(x_api_key) < 10:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return {"tenant_id": "placeholder", "api_key": x_api_key}


# Reusable dependency alias for routes that need the tenant context
TenantDep = Annotated[dict, Depends(verify_api_key)]
