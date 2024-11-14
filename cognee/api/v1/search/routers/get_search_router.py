from cognee.api.v1.search import SearchType
from fastapi.responses import JSONResponse
from cognee.modules.users.models import User
from fastapi import Depends, APIRouter
from cognee.api.DTO import InDTO
from cognee.modules.users.methods import get_authenticated_user


class SearchPayloadDTO(InDTO):
    search_type: SearchType
    query: str

def get_search_router() -> APIRouter:
    router = APIRouter()

    @router.post("/", response_model = list)
    async def search(payload: SearchPayloadDTO, user: User = Depends(get_authenticated_user)):
        """ This endpoint is responsible for searching for nodes in the graph."""
        from cognee.api.v1.search import search as cognee_search

        try:
            results = await cognee_search(payload.search_type, payload.query, user)

            return results
        except Exception as error:
            return JSONResponse(
                status_code = 409,
                content = {"error": str(error)}
            )

    return router