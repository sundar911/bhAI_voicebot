"""AI4Bharat IndicConformer STT backend (600M multilingual)."""

from pathlib import Path
from typing import Any, Dict

from .gpu_base import GPUModelSTT

_DEFAULT_MODEL_ID = "ai4bharat/indic-conformer-600m-multilingual"


class IndicConformerSTT(GPUModelSTT):
    """
    Conformer-based model with CTC decoding.
    Uses trust_remote_code=True — the model exposes a custom __call__ API.
    """

    def __init__(
        self,
        work_dir: Path,
        device: str = "auto",
        model_id: str = _DEFAULT_MODEL_ID,
        language: str = "hi",
        **kwargs: Any,
    ):
        super().__init__(work_dir, device, model_id)
        self.language = language

    @property
    def model_name(self) -> str:
        return self.model_id

    def _load_model(self) -> None:
        from transformers import AutoModel

        self._model = AutoModel.from_pretrained(
            self.model_id, trust_remote_code=True
        )

    def transcribe(self, audio_path: Path) -> Dict[str, Any]:
        import torch
        import torchaudio

        if self._model is None:
            self._load_model()

        wav_path = self._ensure_wav(audio_path)
        waveform, sr = torchaudio.load(str(wav_path))
        # Ensure mono
        waveform = torch.mean(waveform, dim=0, keepdim=True)

        # The model's custom __call__ expects (waveform_tensor, language, decoder)
        with torch.no_grad():
            result = self._model(waveform, self.language, "ctc")

        # Result format varies — handle string, list, or dict
        if isinstance(result, str):
            text = result
        elif isinstance(result, (list, tuple)) and len(result) > 0:
            text = result[0] if isinstance(result[0], str) else str(result[0])
        elif isinstance(result, dict):
            text = result.get("text", result.get("transcription", str(result)))
        else:
            text = str(result)

        return {"text": text.strip(), "raw": {"result": str(result)}, "wav_path": wav_path}
