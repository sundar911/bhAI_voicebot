import json
import time
from pathlib import Path
from typing import Dict, Any

from .audio_utils import ensure_dir
from .config import OUTPUTS_DIR, Config, load_config, _debug_log
from .llm_openai import OpenAILLM
from .sarvam_stt import SarvamSTT
from .sarvam_tts import SarvamTTS


def run_pipeline(
    audio_path: Path,
    out_dir: Path | None = None,
    openai_model: str | None = None,
    enable_tts: bool = True,
) -> Dict[str, Any]:
    # #region agent log
    _debug_log(
        "pipeline.py:run_pipeline:entry",
        "Starting pipeline",
        {
            "audio_path": str(audio_path),
            "out_dir": str(out_dir) if out_dir else None,
            "enable_tts": enable_tts,
        },
        run_id="pre-fix",
        hypothesis_id="H2",
    )
    # #endregion
    if out_dir is None:
        out_dir = OUTPUTS_DIR / f"run_{int(time.time())}"
    out_dir = Path(out_dir)
    ensure_dir(out_dir)

    config: Config = load_config()
    if openai_model:
        config.openai_model = openai_model
    # #region agent log
    _debug_log(
        "pipeline.py:run_pipeline:config",
        "Config loaded",
        {"sarvam_key_present": bool(config.sarvam_api_key)},
        run_id="pre-fix",
        hypothesis_id="H2",
    )
    # #endregion

    if not config.sarvam_api_key:
        # #region agent log
        _debug_log(
            "pipeline.py:run_pipeline:missing_key",
            "SARVAM_API_KEY missing",
            {},
            run_id="pre-fix",
            hypothesis_id="H2",
        )
        # #endregion
        raise RuntimeError("SARVAM_API_KEY missing. Set it in .env to use Sarvam STT/TTS.")
    asr = SarvamSTT(config, work_dir=out_dir)
    tts = SarvamTTS(config) if enable_tts else None
    llm = OpenAILLM(config)

    timings: Dict[str, float] = {}

    t0 = time.perf_counter()
    asr_result = asr.transcribe(Path(audio_path))
    timings["asr_seconds"] = round(time.perf_counter() - t0, 3)

    transcript_text = asr_result["text"]
    (out_dir / "transcript.txt").write_text(transcript_text, encoding="utf-8")

    t1 = time.perf_counter()
    llm_result = llm.generate(transcript_text)
    timings["llm_seconds"] = round(time.perf_counter() - t1, 3)
    response_text = llm_result["text"]
    (out_dir / "response.txt").write_text(response_text, encoding="utf-8")

    tts_path = None
    if enable_tts and response_text:
        t2 = time.perf_counter()
        tts_result = tts.synthesize(response_text, out_dir / "response.wav")
        tts_path = tts_result.get("audio_path")
        timings["tts_seconds"] = round(time.perf_counter() - t2, 3)
    else:
        timings["tts_seconds"] = 0.0

    log = {
        "input_audio": str(Path(audio_path).resolve()),
        "wav_used": str(asr_result.get("wav_path")),
        "transcript_file": str((out_dir / "transcript.txt").resolve()),
        "response_file": str((out_dir / "response.txt").resolve()),
        "response_audio_file": str(tts_path.resolve()) if tts_path else None,
        "models": {
            "asr": config.sarvam_stt_model,
            "llm": config.openai_model,
            "tts": f"sarvam:{config.sarvam_tts_voice}",
        },
        "timings_seconds": timings,
        "escalate": llm_result.get("escalate", False),
    }
    (out_dir / "log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")

    return {
        "transcript": transcript_text,
        "response": response_text,
        "escalate": llm_result.get("escalate", False),
        "out_dir": out_dir,
        "log": log,
    }

