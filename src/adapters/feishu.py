"""FeishuAdapter placeholder -- not implemented in this phase."""
from adapters.base import SearchAdapter, BackendQuery, BackendResponse, ContentType


class FeishuAdapter(SearchAdapter):
    """Placeholder for future Feishu knowledge base integration."""

    @property
    def backend_name(self) -> str:
        return "feishu"

    @property
    def supported_content_types(self) -> list[ContentType]:
        return [ContentType.DOCUMENT]

    async def search(self, query: BackendQuery) -> BackendResponse:
        raise NotImplementedError("FeishuAdapter not yet implemented")

    async def get_content(self, item_id: str) -> dict:
        raise NotImplementedError("FeishuAdapter not yet implemented")

    async def health_check(self) -> bool:
        return False
