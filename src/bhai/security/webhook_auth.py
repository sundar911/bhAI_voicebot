"""
Twilio webhook request signature verification.
Prevents forged requests from reaching the bot.
"""

import logging
from typing import Dict

from twilio.request_validator import RequestValidator

logger = logging.getLogger("bhai.security")


def verify_twilio_signature(
    auth_token: str,
    url: str,
    params: Dict[str, str],
    signature: str,
) -> bool:
    """
    Verify that a webhook request genuinely came from Twilio.

    Args:
        auth_token: Twilio auth token
        url: The full URL of the webhook endpoint
        params: Form parameters from the request
        signature: Value of the X-Twilio-Signature header

    Returns:
        True if the signature is valid, False otherwise.
    """
    if not signature:
        logger.warning("Missing X-Twilio-Signature header — rejecting request")
        return False

    validator = RequestValidator(auth_token)
    is_valid = validator.validate(url, params, signature)

    if not is_valid:
        logger.warning("Invalid Twilio signature — rejecting forged request")

    return is_valid
