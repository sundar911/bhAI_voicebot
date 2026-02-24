"""
Abstract base class for Speech-to-Text (STT) backends.
All STT implementations should inherit from this class.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict


class BaseSTT(ABC):
    """
    Abstract base class for STT backends.

    Implementations should handle:
    - Audio format conversion if needed
    - API/model inference
    - Error handling and retries
    """

    @abstractmethod
    def transcribe(self, audio_path: Path) -> Dict[str, Any]:
        """
        Transcribe audio file to text.

        Args:
            audio_path: Path to input audio file

        Returns:
            Dictionary containing:
                - "text": Transcribed text (str)
                - "raw": Raw response from model/API (dict)
                - Additional backend-specific fields
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier for logging."""
        pass

    def cleanup(self) -> None:
        """Release resources (e.g. GPU memory). Override in subclasses."""
        pass
