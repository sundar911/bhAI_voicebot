"""
Twilio WhatsApp webhook server for bhAI voice bot.
Receives audio messages via Twilio, processes through STT + LLM,
and sends back a voice response (dummy TTS for now).
"""

import sys
import time
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.audio_utils import ensure_dir
from src.bhai.config import load_config, INFERENCE_OUTPUTS_DIR
from src.bhai.integrations.twilio_client import TwilioWhatsAppClient
from src.bhai.stt.sarvam_stt import SarvamSTT
from src.bhai.llm.openai_llm import OpenAILLM


app = FastAPI(title="bhAI Twilio WhatsApp Webhook")

# Directory where response audio files are served from
AUDIO_SERVE_DIR = INFERENCE_OUTPUTS_DIR / "twilio_audio"

# Dummy response audio (used until real TTS is wired up)
DUMMY_AUDIO_PATH = ROOT / "data" / "sample_audio" / "dummy_response.ogg"


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    """
    Serve audio files for Twilio to fetch.

    Twilio's send-message API requires a publicly accessible URL.
    This endpoint serves audio files from the twilio_audio directory.
    """
    file_path = AUDIO_SERVE_DIR / filename
    if not file_path.exists():
        return Response(status_code=404)
    return FileResponse(
        path=str(file_path),
        media_type="audio/ogg",
        filename=filename,
    )


@app.post("/webhook")
async def webhook(request: Request):
    """
    Handle incoming Twilio WhatsApp webhook.

    Twilio sends form-encoded POST data with fields:
    - From: sender number (e.g., "whatsapp:+919876543210")
    - To: our Twilio number
    - NumMedia: count of media attachments
    - MediaUrl0: URL of first media attachment
    - MediaContentType0: MIME type of first media attachment
    """
    config = load_config()

    # Parse form data (Twilio sends form-encoded, not JSON)
    form_data = await request.form()
    sender = form_data.get("From", "")
    num_media = int(form_data.get("NumMedia", 0))
    media_url = form_data.get("MediaUrl0", "")
    media_content_type = form_data.get("MediaContentType0", "")

    print(f"[Twilio] Message from {sender}, media={num_media}, "
          f"type={media_content_type}")

    # Only process audio messages
    if num_media == 0 or not media_url:
        print(f"[Twilio] Skipping non-media message from {sender}")
        return Response(status_code=200, content="<Response></Response>",
                        media_type="application/xml")

    if "audio" not in media_content_type and "ogg" not in media_content_type:
        print(f"[Twilio] Skipping non-audio media: {media_content_type}")
        return Response(status_code=200, content="<Response></Response>",
                        media_type="application/xml")

    # Initialize Twilio client
    twilio_client = TwilioWhatsAppClient(
        account_sid=config.twilio_account_sid,
        auth_token=config.twilio_auth_token,
        whatsapp_number=config.twilio_whatsapp_number,
    )

    # Create run directory
    run_id = f"twilio_{int(time.time())}"
    run_dir = INFERENCE_OUTPUTS_DIR / run_id
    ensure_dir(run_dir)

    # Download incoming audio
    extension = ".ogg" if "ogg" in media_content_type else ".wav"
    inbound_path = run_dir / f"inbound{extension}"
    twilio_client.download_media(media_url, inbound_path)
    print(f"[Twilio] Downloaded audio to {inbound_path}")

    # STT
    work_dir = ROOT / ".bhai_temp"
    stt = SarvamSTT(config, work_dir=work_dir)
    stt_result = stt.transcribe(inbound_path)
    transcript = stt_result["text"]
    (run_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
    print(f"[Twilio] Transcript: {transcript}")

    # LLM
    llm = OpenAILLM(config)
    llm_result = llm.generate(transcript, domain="hr_admin")
    response_text = llm_result["text"]
    (run_dir / "response.txt").write_text(response_text, encoding="utf-8")
    print(f"[Twilio] Response: {response_text}")

    # Dummy TTS: copy the dummy audio to the serve directory
    ensure_dir(AUDIO_SERVE_DIR)
    response_filename = f"{run_id}_response.ogg"
    response_serve_path = AUDIO_SERVE_DIR / response_filename

    if DUMMY_AUDIO_PATH.exists():
        response_serve_path.write_bytes(DUMMY_AUDIO_PATH.read_bytes())
    else:
        # Fallback: generate a short tone if dummy file is missing
        from pydub import AudioSegment
        from pydub.generators import Sine
        tone = Sine(440).to_audio_segment(duration=1000)
        tone.export(str(response_serve_path), format="ogg", codec="libopus")

    # Construct the public URL for the audio file
    base_url = config.base_url.rstrip("/")
    audio_public_url = f"{base_url}/audio/{response_filename}"

    # Send audio response via Twilio
    send_result = twilio_client.send_audio_message(
        to_number=sender,
        media_url=audio_public_url,
    )
    print(f"[Twilio] Sent response: SID={send_result['sid']}, "
          f"status={send_result['status']}")

    # Return empty TwiML (Twilio expects XML response)
    return Response(
        status_code=200,
        content="<Response></Response>",
        media_type="application/xml",
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "bhai-twilio-webhook"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
