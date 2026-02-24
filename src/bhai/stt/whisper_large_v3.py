"""OpenAI Whisper Large V3 STT backend."""

from pathlib import Path
from typing import Any, Dict

from .gpu_base import GPUModelSTT

_DEFAULT_MODEL_ID = "openai/whisper-large-v3"


class WhisperLargeV3STT(GPUModelSTT):

    def __init__(
        self,
        work_dir: Path,
        device: str = "auto",
        model_id: str = _DEFAULT_MODEL_ID,
        **kwargs: Any,
    ):
        super().__init__(work_dir, device, model_id)

    @property
    def model_name(self) -> str:
        return self.model_id

    def _load_model(self) -> None:
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        self._processor = WhisperProcessor.from_pretrained(self.model_id)
        self._model = WhisperForConditionalGeneration.from_pretrained(
            self.model_id, torch_dtype=torch.float32
        )
        self._model.to(self.device)

    def transcribe(self, audio_path: Path) -> Dict[str, Any]:
        import torch

        if self._model is None:
            self._load_model()

        wav_path = self._ensure_wav(audio_path)
        waveform, sr = self._load_audio_tensor(wav_path)

        input_features = self._processor(
            waveform.squeeze().numpy(),
            sampling_rate=sr,
            return_tensors="pt",
        ).input_features.to(self.device)

        with torch.no_grad():
            predicted_ids = self._model.generate(
                input_features, language="hi", task="transcribe"
            )

        text = self._processor.batch_decode(
            predicted_ids, skip_special_tokens=True
        )[0]

        return {"text": text.strip(), "raw": {}, "wav_path": wav_path}
