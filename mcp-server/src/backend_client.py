"""Backend API HTTP client for MCP Server.

All tool calls go through this client to the Backend API with Bearer token authorization.
"""
import httpx
import logging
from typing import Any, Dict, Optional
from .config import settings

logger = logging.getLogger(__name__)


class BackendClient:
    """HTTP client for Backend API communication."""
    
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or settings.BACKEND_URL
        logger.info(f"BackendClient initialized with base_url: {self.base_url}")
    
    async def request(
        self,
        method: str,
        path: str,
        token: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make an authorized request to the Backend API.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            path: API path (e.g., /items/)
            token: Bearer token for authorization
            json_data: JSON body for POST/PUT requests
            params: Query parameters
            
        Returns:
            Response JSON data
            
        Raises:
            PermissionError: If unauthorized or forbidden
            httpx.HTTPStatusError: For other HTTP errors
        """
        logger.info(f"[BackendClient] {method} {path}")
        logger.debug(f"[BackendClient] Token: {token[:20]}..." if token else "[BackendClient] No token")
        logger.debug(f"[BackendClient] JSON: {json_data}")
        logger.debug(f"[BackendClient] Params: {params}")
        
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30.0) as client:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            
            response = await client.request(
                method=method,
                url=path,
                headers=headers,
                json=json_data,
                params=params
            )
            
            logger.info(f"[BackendClient] Response status: {response.status_code}")
            
            if response.status_code == 401:
                logger.error("[BackendClient] Unauthorized - invalid token")
                raise PermissionError("Unauthorized - invalid or expired token")
            
            if response.status_code == 403:
                logger.error("[BackendClient] Forbidden - insufficient permissions")
                raise PermissionError("Forbidden - insufficient permissions")
            
            if response.status_code == 404:
                logger.warning(f"[BackendClient] Resource not found: {path}")
                return {"error": "Not found", "status_code": 404}
            
            response.raise_for_status()
            
            result = response.json()
            logger.debug(f"[BackendClient] Response: {result}")
            return result
    
    # Item CRUD operations
    async def create_item(self, token: str, name: str, description: str = "", data: Optional[Dict] = None) -> Dict:
        """Create a new item via Backend API."""
        return await self.request(
            "POST", "/items/",
            token=token,
            json_data={"name": name, "description": description, "data": data or {}}
        )
    
    async def read_item(self, token: str, item_id: str) -> Dict:
        """Read an item by ID via Backend API."""
        return await self.request("GET", f"/items/{item_id}", token=token)
    
    async def update_item(self, token: str, item_id: str, name: Optional[str] = None, 
                          description: Optional[str] = None, data: Optional[Dict] = None) -> Dict:
        """Update an item via Backend API."""
        update_data = {}
        if name is not None:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if data is not None:
            update_data["data"] = data
        return await self.request("PUT", f"/items/{item_id}", token=token, json_data=update_data)
    
    async def delete_item(self, token: str, item_id: str) -> Dict:
        """Delete an item via Backend API."""
        return await self.request("DELETE", f"/items/{item_id}", token=token)
    
    async def list_items(self, token: str, skip: int = 0, limit: int = 100) -> Dict:
        """List items via Backend API."""
        return await self.request("GET", "/items/", token=token, params={"skip": skip, "limit": limit})
    
    async def search_items(self, token: str, query: str, field: str = "all", 
                           limit: int = 20, offset: int = 0) -> Dict:
        """Search items via Backend API."""
        return await self.request(
            "GET", "/items/search",
            token=token,
            params={"q": query, "field": field, "limit": limit, "offset": offset}
        )
    
    # Batch operations
    async def bulk_create(self, token: str, items: list) -> Dict:
        """Bulk create items via Backend API."""
        return await self.request("POST", "/items/batch/create", token=token, json_data={"items": items})
    
    async def bulk_delete(self, token: str, item_ids: list) -> Dict:
        """Bulk delete items via Backend API."""
        return await self.request("POST", "/items/batch/delete", token=token, json_data={"item_ids": item_ids})
    
    # Statistics and reports
    async def get_statistics(self, token: str) -> Dict:
        """Get item statistics via Backend API."""
        return await self.request("GET", "/items/stats", token=token)
    
    async def generate_report(self, token: str, report_type: str, filters: Optional[Dict] = None) -> Dict:
        """Generate a report via Backend API."""
        return await self.request(
            "POST", "/reports/generate",
            token=token,
            json_data={"report_type": report_type, "filters": filters or {}}
        )
    
    # User operations
    async def get_user_profile(self, token: str) -> Dict:
        """Get current user profile via Backend API."""
        return await self.request("GET", "/users/me", token=token)
    
    async def update_user_profile(self, token: str, profile_data: Dict) -> Dict:
        """Update current user profile via Backend API."""
        return await self.request("PUT", "/users/me", token=token, json_data=profile_data)


# Global client instance
backend_client = BackendClient()
