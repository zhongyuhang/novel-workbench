"""Select a provider from the endpoint. Business code does not import vendor clients."""

import httpx

from app.ai.mock_provider import MockProvider
from app.ai.openai_provider import OpenAICompatibleProvider
from app.ai.provider import ModelEndpoint, ModelProvider, ProviderError

_transport: httpx.BaseTransport | None = None


def set_test_transport(transport: httpx.BaseTransport | None) -> None:
    """Install a mock transport for tests. Production leaves this unset."""

    global _transport
    _transport = transport


def get_provider(endpoint: ModelEndpoint) -> ModelProvider:
    if endpoint.provider_type == "mock":
        return MockProvider()
    if endpoint.provider_type == "openai_compatible":
        return OpenAICompatibleProvider(transport=_transport)
    raise ProviderError("MODEL_CONFIG_INVALID", "不支持的模型服务类型。")
