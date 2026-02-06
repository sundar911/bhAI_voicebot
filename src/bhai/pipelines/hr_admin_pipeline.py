"""
HR-Admin domain pipeline.
Specialized pipeline for HR, salary, leave, and benefits queries.
"""

from pathlib import Path
from typing import Optional

from ..config import Config, load_config
from ..stt.sarvam_stt import SarvamSTT
from ..tts.sarvam_tts import SarvamTTS
from ..llm.openai_llm import OpenAILLM
from .base_pipeline import BasePipeline


class HRAdminPipeline(BasePipeline):
    """
    HR-Admin domain voice bot pipeline.

    Handles queries related to:
    - Salary and payroll
    - Leave requests and policies
    - Benefits and support programs
    - Workplace conduct and safety
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        work_dir: Optional[Path] = None,
        enable_tts: bool = True
    ):
        """
        Initialize HR-Admin pipeline with default components.

        Args:
            config: Application configuration (loads from env if None)
            work_dir: Working directory for temp files
            enable_tts: Whether to enable TTS
        """
        if config is None:
            config = load_config()

        if work_dir is None:
            work_dir = Path.cwd() / ".bhai_temp"

        # Initialize components
        stt = SarvamSTT(config, work_dir=work_dir)
        llm = OpenAILLM(config)
        tts = SarvamTTS(config) if enable_tts else None

        super().__init__(
            config=config,
            stt=stt,
            llm=llm,
            tts=tts,
            domain="hr_admin"
        )

    @property
    def name(self) -> str:
        return "hr_admin_pipeline"


def run_pipeline(
    audio_path: Path,
    out_dir: Optional[Path] = None,
    openai_model: Optional[str] = None,
    enable_tts: bool = True
):
    """
    Convenience function to run HR-Admin pipeline.

    Maintains backward compatibility with existing scripts.
    """
    config = load_config()
    if openai_model:
        config.openai_model = openai_model

    pipeline = HRAdminPipeline(config=config, enable_tts=enable_tts)
    return pipeline.run(audio_path, out_dir=out_dir, enable_tts=enable_tts)
