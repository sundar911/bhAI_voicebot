"""
Background retry worker for queued pipeline requests.

Polls the request queue at a configurable interval and processes
requests from their saved stage, sending results via Twilio.
"""

import asyncio
import logging
import time
from pathlib import Path

from ..audio_utils import convert_to_ogg_opus, ensure_dir
from ..config import INFERENCE_OUTPUTS_DIR, ROOT_DIR, Config
from ..integrations.twilio_client import TwilioWhatsAppClient
from ..llm import create_llm
from ..memory.store import ConversationStore
from ..stt.sarvam_stt import SarvamSTT
from .queue import RequestQueue

logger = logging.getLogger("bhai.resilience.worker")

APOLOGY_TEXT = (
    "Maaf karo, abhi kuch problem ho rahi hai. "
    "Thodi der mein phir se try karo ya apne supervisor ko call karo."
)


class RetryWorker:
    """
    Background worker that retries failed pipeline requests.

    Runs as an asyncio task, polling the queue every `interval` seconds.
    Processes each request from its saved stage onward (STT → LLM → TTS).
    """

    def __init__(
        self,
        queue: RequestQueue,
        config: Config,
        store: ConversationStore,
        interval: int = 30,
    ):
        self.queue = queue
        self.config = config
        self.store = store
        self.interval = interval

    async def run_forever(self):
        """Poll the queue and process ready requests until cancelled."""
        logger.info("Retry worker started (interval=%ds)", self.interval)
        while True:
            try:
                request = self.queue.dequeue_ready()
                if request:
                    await asyncio.to_thread(self._process_request, request)
                else:
                    # Also clean up old entries periodically
                    self.queue.cleanup_completed(older_than_hours=48)
            except Exception as e:
                logger.error("Worker loop error: %s", e, exc_info=True)

            await asyncio.sleep(self.interval)

    def _process_request(self, request: dict):
        """Process a single queued request through remaining pipeline stages."""
        request_id = request["id"]
        phone = request["phone"]
        sender = request["sender"]
        stage = request["stage"]
        domain = request.get("domain", "hr_admin")

        logger.info(
            "Processing queued request id=%d stage=%s",
            request_id,
            stage,
        )

        twilio_client = TwilioWhatsAppClient(
            account_sid=self.config.twilio_account_sid,
            auth_token=self.config.twilio_auth_token,
            whatsapp_number=self.config.twilio_whatsapp_number,
        )

        try:
            transcript: str = request.get("transcript") or ""
            llm_response: str = request.get("llm_response") or ""

            # ── STT stage ──────────────────────────────────────────
            if stage == "stt":
                audio_path = Path(request["audio_path"])
                if not audio_path.exists():
                    raise FileNotFoundError(f"Queued audio missing: {audio_path}")

                work_dir = ROOT_DIR / ".bhai_temp"
                stt = SarvamSTT(self.config, work_dir=work_dir)
                stt_result = stt.transcribe(audio_path)
                transcript = stt_result["text"]

                # Save progress so next retry skips STT
                self.queue.update_stage(request_id, "llm", transcript=transcript)
                stage = "llm"

            # ── LLM stage ──────────────────────────────────────────
            if stage == "llm":
                llm = create_llm(self.config)
                user_profile = llm.load_user_profile(phone)
                memory = self.store.get_memory(phone)

                memory_summary = ""
                extracted_facts = ""
                if memory:
                    memory_summary = memory["summary"]
                    facts_list = memory["facts"]
                    if facts_list:
                        extracted_facts = "\n".join(f"- {f}" for f in facts_list)

                recent = self.store.get_recent_messages(phone, limit=8)

                llm_result = llm.generate_with_emotions(
                    transcript,
                    domain=domain,
                    user_profile=user_profile,
                    memory_summary=memory_summary,
                    extracted_facts=extracted_facts,
                    conversation_history=recent,
                )
                llm_response = llm_result["text"]

                # Save progress
                self.queue.update_stage(request_id, "tts", llm_response=llm_response)
                stage = "tts"

            # ── TTS stage ──────────────────────────────────────────
            if stage == "tts":
                audio_serve_dir = INFERENCE_OUTPUTS_DIR / "twilio_audio"
                ensure_dir(audio_serve_dir)
                run_id = f"retry_{request_id}_{int(time.time())}"
                response_filename = f"{run_id}_response.ogg"
                response_serve_path = audio_serve_dir / response_filename

                try:
                    if self.config.tts_backend == "elevenlabs":
                        from ..tts.elevenlabs_tts import ElevenLabsTTS

                        tts_el = ElevenLabsTTS(self.config)
                        tts_el.synthesize(llm_response, response_serve_path)
                    else:
                        from ..tts.sarvam_tts import SarvamTTS

                        tts_sr = SarvamTTS(self.config)
                        run_dir = INFERENCE_OUTPUTS_DIR / run_id
                        ensure_dir(run_dir)
                        tts_raw_path = run_dir / "tts_raw_output.wav"
                        tts_sr.synthesize(llm_response, tts_raw_path)
                        convert_to_ogg_opus(tts_raw_path, response_serve_path)

                    # Send audio response
                    base_url = self.config.base_url.rstrip("/")
                    audio_url = f"{base_url}/audio/{response_filename}"
                    twilio_client.send_audio_message(
                        to_number=sender, media_url=audio_url
                    )
                except Exception:
                    # TTS failed — fall back to text
                    logger.warning(
                        "TTS failed for queued request id=%d, sending text",
                        request_id,
                    )
                    twilio_client.send_text_message(to_number=sender, body=llm_response)

            self.queue.mark_completed(request_id)
            logger.info("Queued request id=%d processed successfully", request_id)

        except Exception as e:
            logger.error(
                "Queued request id=%d failed: %s", request_id, e, exc_info=True
            )
            is_dead = self.queue.mark_failed(request_id, str(e))
            if is_dead:
                try:
                    twilio_client.send_text_message(to_number=sender, body=APOLOGY_TEXT)
                except Exception:
                    logger.error(
                        "Failed to send apology for dead request id=%d",
                        request_id,
                    )
