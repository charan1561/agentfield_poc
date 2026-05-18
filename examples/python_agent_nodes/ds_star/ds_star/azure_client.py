import os
from typing import List, Dict, Any, Optional
from openai import AzureOpenAI


class AzureLLM:
    """
    Thin Azure OpenAI client wrapper for Chat Completions (gpt-5-chat) and Embeddings.
    Environment variables:
      - AZURE_OPENAI_ENDPOINT
      - AZURE_OPENAI_API_KEY
      - AZURE_OPENAI_API_VERSION
      - AZURE_OPENAI_API_VERSION_CHAT      (optional; overrides chat API version)
      - AZURE_OPENAI_API_VERSION_EMBEDDING (optional; overrides embeddings API version)
      - AZURE_OPENAI_DEPLOYMENT           (chat model deployment, e.g., gpt-5-chat)
      - AZURE_OPENAI_EMBEDDING_DEPLOYMENT (embedding model deployment, e.g., text-embedding-3-large)
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        api_version: Optional[str] = None,
        chat_deployment: Optional[str] = None,
        embedding_deployment: Optional[str] = None,
        chat_api_version: Optional[str] = None,
        embedding_api_version: Optional[str] = None,
    ) -> None:
        endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
        # Backward compatibility: allow a single API version via AZURE_OPENAI_API_VERSION
        base_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION")
        chat_api_version = chat_api_version or os.getenv("AZURE_OPENAI_API_VERSION_CHAT") or base_version
        embedding_api_version = embedding_api_version or os.getenv("AZURE_OPENAI_API_VERSION_EMBEDDING") or base_version
        chat_deployment = chat_deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        embedding_deployment = embedding_deployment or os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")

        if not endpoint or not api_key or not chat_api_version:
            raise RuntimeError(
                "Azure OpenAI credentials not set. Please set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_API_VERSION or AZURE_OPENAI_API_VERSION_CHAT."
            )
        if not chat_deployment:
            raise RuntimeError("Chat deployment name not set. Please set AZURE_OPENAI_DEPLOYMENT (e.g., gpt-5-chat).")
        if not embedding_deployment:
            # Embeddings are optional unless retriever is used. Warn but allow override later.
            os.environ.setdefault("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")

        # Separate clients so chat and embeddings can use different API versions
        self._chat_client = AzureOpenAI(api_key=api_key, azure_endpoint=endpoint, api_version=chat_api_version)
        self._embed_client = AzureOpenAI(api_key=api_key, azure_endpoint=endpoint, api_version=embedding_api_version or chat_api_version)
        self.chat_deployment = chat_deployment
        self.embedding_deployment = embedding_deployment

    def chat_complete(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Call Azure OpenAI Chat Completions API.
        messages: list of {role: 'system'|'user'|'assistant', content: str}
        """
        # Determine param name: new Azure deployments (e.g., gpt-5, gpt-4.1, preview) require 'max_completion_tokens' instead of 'max_tokens'
        model_str = str(self.chat_deployment or "").lower()
        use_completion_tokens = (
            ("gpt-5" in model_str) or
            ("gpt-4.1" in model_str) or
            ("-preview" in model_str) or
            ("-2" in model_str)  # heuristically catch versioned deployments
        )
        if max_tokens is None:
            max_tokens = 1024

        kwargs = dict(
            model=self.chat_deployment,
            messages=messages,
        )
        # Only pass temperature for legacy models. For GPT-5/preview, omit entirely.
        if not use_completion_tokens:
            kwargs["temperature"] = temperature
        # Always set token param
        if use_completion_tokens:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

        resp = self._chat_client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Call Azure OpenAI Embeddings API. Requires AZURE_OPENAI_EMBEDDING_DEPLOYMENT.
        """
        if not (self.embedding_deployment or os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")):
            raise RuntimeError("Embedding deployment name not set. Please set AZURE_OPENAI_EMBEDDING_DEPLOYMENT.")
        model = self.embedding_deployment or os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        resp = self._embed_client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]


def get_default_llm() -> AzureLLM:
    """Convenience constructor using environment variables."""
    return AzureLLM()
