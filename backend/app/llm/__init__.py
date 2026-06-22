"""LLM abstraction layer — provider-agnostic extraction protocol.

``LLMClient`` is the protocol every provider implements. ``GeminiClient`` is the
default (Gemini 2.0 Flash). ``FakeLLMClient`` returns inline content from the
submission, keeping the deterministic eval suite at 12/12 with zero API calls.

Swapping Claude in is a one-file change: implement ``LLMClient`` in ``claude.py``
and pass it to ``run_claim()``.
"""

from .base import ExtractionResult, LLMClient
from .fake import FakeLLMClient
from .gemini import GeminiClient

__all__ = ["ExtractionResult", "FakeLLMClient", "GeminiClient", "LLMClient"]
