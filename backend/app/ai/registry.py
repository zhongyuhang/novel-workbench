"""Select a provider from the endpoint. Business code does not import vendor clients."""

from app.ai.mock_provider import MockProvider
from app.ai.openai_provider import OpenAICompatibleProvider
from app.ai.provider import ModelEndpoint, ModelProvider, ProviderError


def get_provider(endpoint: ModelEndpoint) -> ModelProvider:
    if endpoint.provider_type == "mock":
        return MockProvider()
    if endpoint.provider_type == "openai_compatible":
        return OpenAICompatibleProvider()
    raise ProviderError("MODEL_CONFIG_INVALID", "不支持的模型服务类型。")
