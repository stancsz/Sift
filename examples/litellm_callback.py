"""Example callback instance for LiteLLM Proxy's `litellm_settings.callbacks`."""

from sift.litellm_proxy import SiftLiteLLMHook


sift_callback = SiftLiteLLMHook(
    {"local-chat": 24_576},
    raw_limit=1_000_000,
)
