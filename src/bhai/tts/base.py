"""
Abstract base class for Text-to-Speech (TTS) backends.
All TTS implementations should inherit from this class.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict


class BaseTTS(ABC):
    """
    Abstract base class for TTS backends.

    Implementations should handle:
    - Text preprocessing if needed
    - API/model inference
    - Audio file output
    """

    @abstractmethod
    def synthesize(self, text: str, output_path: Path) -> Dict[str, Any]:
        """
        Synthesize speech from text.

        Args:
            text: Input text to convert to speech
            output_path: Path where audio file should be saved

        Returns:
            Dictionary containing:
                - "audio_path": Path to generated audio file
                - "raw": Raw response from model/API (dict or None)
        """
        pass

    @property
    @abstractmethod
    def voice_name(self) -> str:
        """Return the voice identifier for logging."""
        pass
