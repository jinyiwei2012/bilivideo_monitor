"""API 认证模块 —— 多用户支持"""

import logging
from typing import Optional, Dict
from fastapi import HTTPException, Depends, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.user_manager import get_user_by_apikey

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> Optional[Dict]:
    if credentials is None:
        return None
    user = get_user_by_apikey(credentials.credentials)
    return user


async def authenticate(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> Dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证信息，请提供 Bearer Token (API Key)",
        )
    user = get_user_by_apikey(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 API Key",
        )
    return user


async def require_admin(user: Dict = Depends(authenticate)) -> Dict:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user
