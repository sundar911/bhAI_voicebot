"""Meta MMS (Massive Multilingual Speech) STT backend."""

from pathlib import Path
from typing import Any, Dict

from .gpu_base import GPUModelSTT

_DEFAULT_MODEL_ID = "facebook/mms-1b-all"


class MetaMmsSTT(GPUModelSTT):
    """
    Wav2Vec2-based model with language adapters.
    Uses ISO 639-3 codes: Hindi = "hin", Marathi = "mar".
    """

    def __init__(
        self,
        work_dir: Path,
        device: str = "auto",
        model_id: str = _DEFAULT_MODEL_ID,
        language: str = "hin",
        **kwargs: Any,
    ):
        super().__init__(work_dir, device, model_id)
        self.language = language  # ISO 639-3

    @property
    def model_name(self) -> str:
        return f"{self.model_id} (lang={self.language})"

    def _load_model(self) -> None:
        from transformers import AutoProcessor, Wav2Vec2ForCTC

        self._processor = AutoProcessor.from_pretrained(self.model_id)
        self._model = Wav2Vec2ForCTC.from_pretrained(self.model_id)
        # Load language-specific adapter
        self._processor.tokenizer.set_target_lang(self.language)
        self._model.load_adapter(self.language)
        self._model.to(self.device)

    def transcribe(self, audio_path: Path) -> Dict[str, Any]:
        import torch

        if self._model is None:
            self._load_model()

        wav_path = self._ensure_wav(audio_path)
        waveform, sr = self._load_audio_tensor(wav_path)

        inputs = self._processor(
            waveform.squeeze().numpy(),
            sampling_rate=sr,
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            logits = self._model(**inputs).logits

        ids = torch.argmax(logits, dim=-1)[0]
        text = self._processor.decode(ids)

        return {"text": text.strip(), "raw": {}, "wav_path": wav_path}
