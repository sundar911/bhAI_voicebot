"""
Abstract base class for LLM backends.
All LLM implementations should inherit from this class.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseLLM(ABC):
    """
    Abstract base class for LLM backends.

    Implementations should handle:
    - System prompt construction with knowledge base
    - API/model inference
    - Response parsing and escalation detection
    """

    @abstractmethod
    def generate(self, transcript: str, domain: str = "hr_admin") -> Dict[str, Any]:
        """
        Generate a response for the given transcript.

        Args:
            transcript: User's transcribed speech
            domain: Knowledge domain (hr_admin, helpdesk, production)

        Returns:
            Dictionary containing:
                - "text": Generated response text (str)
                - "raw": Raw response text before cleanup
                - "escalate": Whether to escalate to human (bool)
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier for logging."""
        pass
