"""
WhatsApp webhook server for bhAI voice bot.
Receives audio messages, processes them, and sends back voice responses.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bhai.audio_utils import ensure_dir
from src.bhai.config import load_config, INFERENCE_OUTPUTS_DIR
from src.bhai.pipelines.hr_admin_pipeline import HRAdminPipeline
from src.bhai.tts.sarvam_tts import SarvamTTS
from src.bhai.integrations.whatsapp_client import WhatsAppClient


app = FastAPI(title="bhAI WhatsApp Webhook")

# Intro message for first-time users
INTRO_TEXT = (
    "नमस्कार! मैं आपकी सहायता साथी हूँ। "
    "आप मुझे यहाँ पर अपनी आवाज़ में सवाल पूछ सकते हैं, जैसे वेतन, छुट्टी, या काम से जुड़ी बात। "
    "मैं आपकी बात सुनकर आसान हिंदी में जवाब दूँगी।"
)

# Track seen senders
SEEN_FILE = INFERENCE_OUTPUTS_DIR / "wa_seen.json"


def _load_seen() -> Dict[str, bool]:
    """Load set of previously seen senders."""
    if not SEEN_FILE.exists():
        return {}
    try:
        return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_seen(seen: Dict[str, bool]) -> None:
    """Save set of seen senders."""
    ensure_dir(SEEN_FILE.parent)
    SEEN_FILE.write_text(json.dumps(seen, indent=2), encoding="utf-8")


def _get_message(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract message from webhook entry."""
    try:
        changes = entry.get("changes", [])
        if not changes:
            return None
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        return messages[0] if messages else None
    except Exception:
        return None


@app.get("/webhook")
async def verify_webhook(request: Request):
    """Webhook verification endpoint for Meta."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    config = load_config()
    if mode == "subscribe" and token == config.meta_verify_token:
        return PlainTextResponse(challenge or "")

    return Response(status_code=403)


@app.post("/webhook")
async def webhook(request: Request):
    """Process incoming WhatsApp messages."""
    payload = await request.json()
    entry_list = payload.get("entry", [])

    if not entry_list:
        return {"status": "no_entry"}

    config = load_config()
    wa = WhatsAppClient(
        token=config.meta_wa_token,
        phone_number_id=config.meta_phone_number_id,
        api_version=config.meta_api_version,
    )

    for entry in entry_list:
        message = _get_message(entry)
        if not message:
            continue

        sender = message.get("from")
        msg_type = message.get("type")

        # Only process audio messages
        if msg_type != "audio":
            continue

        audio = message.get("audio", {})
        media_id = audio.get("id")
        if not media_id or not sender:
            continue

        # Create run directory
        run_dir = INFERENCE_OUTPUTS_DIR / f"wa_{int(time.time())}"
        ensure_dir(run_dir)

        # Download audio
        media_info = wa.get_media_url(media_id)
        media_url = media_info.get("url")
        mime_type = media_info.get("mime_type", "audio/ogg")
        extension = ".ogg" if "ogg" in mime_type else ".wav"
        inbound_path = run_dir / f"inbound{extension}"
        wa.download_media(media_url, inbound_path)

        # Send intro to first-time users
        seen = _load_seen()
        if not seen.get(sender):
            tts = SarvamTTS(config)
            intro_path = run_dir / "intro.wav"
            tts.synthesize(INTRO_TEXT, intro_path)
            intro_media_id = wa.upload_media(intro_path, mime_type="audio/wav")
            wa.send_audio(sender, intro_media_id)
            seen[sender] = True
            _save_seen(seen)

        # Process through pipeline
        pipeline = HRAdminPipeline(config=config, enable_tts=True)
        result = pipeline.run(audio_path=inbound_path, out_dir=run_dir)

        # Send response audio
        response_audio_path = run_dir / "response.wav"
        if response_audio_path.exists():
            response_media_id = wa.upload_media(response_audio_path, mime_type="audio/wav")
            wa.send_audio(sender, response_media_id)

    return {"status": "ok"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "bhai-whatsapp-webhook"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
