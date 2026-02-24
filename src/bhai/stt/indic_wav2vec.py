"""AI4Bharat IndicWav2Vec Hindi STT backend."""

from pathlib import Path
from typing import Any, Dict

from .gpu_base import GPUModelSTT

_DEFAULT_MODEL_ID = "ai4bharat/indicwav2vec-hindi"


class IndicWav2VecSTT(GPUModelSTT):

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
        from transformers import AutoModelForCTC, AutoProcessor

        self._processor = AutoProcessor.from_pretrained(self.model_id)
        self._model = AutoModelForCTC.from_pretrained(self.model_id)
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
        )
        input_values = inputs.input_values.to(self.device)

        with torch.no_grad():
            logits = self._model(input_values).logits

        ids = torch.argmax(logits, dim=-1)[0]
        text = self._processor.decode(ids)

        return {"text": text.strip(), "raw": {}, "wav_path": wav_path}
