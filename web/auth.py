"""
API 认证模块 —— 多用户支持

提供 FastAPI 依赖注入式的认证中间件：
- get_optional_user: 可选认证（未提供 token 时返回 None）
- authenticate: 强制认证（未提供或无效 token 返回 401）
- require_admin: 管理员权限检查（非管理员返回 403）

认证方式：HTTP Bearer Token (API Key)
"""

import logging
from typing import Optional, Dict
from fastapi import HTTPException, Depends, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.user_manager import get_user_by_apikey

logger = logging.getLogger(__name__)

# HTTP Bearer 认证方案（auto_error=False 允许不传 token 的请求）
security = HTTPBearer(auto_error=False)


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> Optional[Dict]:
    """
    可选认证依赖：从 Bearer Token 中解析用户，无 token 时返回 None。
    
    用于既支持匿名访问又支持认证访问的端点（如视频列表）。
    
    Args:
        credentials: FastAPI Security 自动注入的 HTTP 凭证
        
    Returns:
        dict: 用户信息字典，无有效 token 时返回 None
    """
    if credentials is None:
        return None
    user = get_user_by_apikey(credentials.credentials)
    return user


async def authenticate(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> Dict:
    """
    强制认证依赖：必须提供有效的 Bearer Token，否则返回 401。
    
    用于需要登录才能访问的端点（如添加视频、触发预测等）。
    
    Args:
        credentials: FastAPI Security 自动注入的 HTTP 凭证
        
    Returns:
        dict: 用户信息字典
        
    Raises:
        HTTPException 401: 缺少认证信息或 API Key 无效
    """
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
    """
    管理员权限依赖：先强制认证，再检查 is_admin 标记。
    
    用于管理员专属端点（如配置修改、引擎状态查询）。
    
    Args:
        user: authenticate() 返回的用户信息
        
    Returns:
        dict: 管理员用户信息
        
    Raises:
        HTTPException 403: 非管理员用户
    """
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user
