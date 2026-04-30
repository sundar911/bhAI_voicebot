# Prompt: bhAI WhatsApp production setup (Meta Cloud API + optional Wati)

Copy-paste everything below into a fresh Claude chat. Use this chat for the ops/setup work only (Meta developer console, WhatsApp Business verification, webhook configuration, Railway env vars). Dev/coding work happens in a separate chat.

---

## Context for the new chat

I'm migrating a WhatsApp voice bot called **bhAI** from Twilio Sandbox to a production setup on my own WhatsApp number. I need help managing the setup end-to-end — the non-coding side (Meta console, WABA verification, access tokens, webhook configuration, Wati signup if needed). My other chat is doing the backend code changes in parallel.

### What bhAI is
A voice-note WhatsApp bot for artisans at Tiny Miracles (a Mumbai non-profit that employs women from vulnerable communities). Users send Hindi/Marathi voice notes, bhAI replies with warm, contextual voice notes using Vidhi's cloned voice. It's currently in a 5-user pilot.

### Current state
- **Backend**: FastAPI server hosted on Railway (`bhaivoicebot-production.up.railway.app`)
- **Messaging**: Twilio WhatsApp Sandbox (shared US number `+1 415 523 8886`, users must send "join <phrase>")
- **Pipeline**: Voice note → Sarvam STT → Claude Sonnet 4.6 → ElevenLabs TTS → voice note back
- **Prompt**: Lives at `src/bhai/llm/prompts/prompt_v1_pilot.md` in the repo
- **Pilot**: 7-8 women testing since Apr 13. Working but limited by sandbox (72-hour session expiry, US number, no proactive messaging, no display name)
- **Repo**: https://github.com/sundar911/bhAI_voicebot

### Goal
Move off Twilio Sandbox to a **production-grade WhatsApp setup** on bhAI's own Indian number so we can:
- Have a proper display name, profile picture, About section
- Send proactive messages / follow-ups (not just reply-only within 24hr window)
- Drop the "join" message flow — users just message directly
- No 72-hour session expiry
- Scale beyond 10 users

### Two possible paths — help me pick and execute

**Path A: Meta Cloud API directly** (no middleman, free)
- Already partially set up: Meta developer app called "bhAI" created
- App ID: 1594208654923318
- I've been going through Meta's "Connect on WhatsApp" use case setup
- Got stuck at: Configuration page asks for Callback URL + Verify token (I'll generate token: `bhai-pilot-2026`)
- Need to complete: WhatsApp Business Account verification, phone number registration, permanent access token generation, webhook verification
- Meta flagged my account once for "automated behavior" — need to be careful with rapid clicks in console

**Path B: Wati or Gupshup** (managed provider)
- They handle Meta verification for you
- Cost ~₹2500/month + per-conversation
- Faster to production (1-2 days) since they manage the business verification
- Less control, more expensive long-term

I'd prefer Path A since I've already started it. Switch to Path B only if Meta verification proves blocking.

### What I need from you in this chat

1. **Step-by-step guidance** through Meta's API Setup page:
   - How to connect my existing WhatsApp Business Account (if any) or create a new one
   - Which phone number to register (I need a fresh Indian SIM not currently on WhatsApp — does it need to be a specific type?)
   - How to generate a **permanent** access token (not the 24-hour temporary one)
   - Where to find Phone Number ID and WhatsApp Business Account ID

2. **Business verification process**:
   - What documents Meta will ask for
   - How long it takes
   - Can the bot work in "development mode" while verification is pending?
   - If verification fails or stalls, when should I switch to Path B (Wati)?

3. **Webhook setup** (I'll coordinate this with my dev chat):
   - What webhook events to subscribe to (messages, message_status, etc.)
   - How to test webhook verification before going live
   - Troubleshooting if verification fails

4. **Env vars I'll need to set on Railway**:
   - `META_VERIFY_TOKEN=bhai-pilot-2026`
   - `META_ACCESS_TOKEN=<permanent token>`
   - `META_PHONE_NUMBER_ID=<from API Setup>`
   - `META_APP_SECRET=<from App Settings>`
   - `META_WABA_ID=<WhatsApp Business Account ID>`

5. **Transition plan**: Once Meta is working, how to gracefully switch the 7-8 pilot users from Twilio sandbox to the new bhAI number without losing their conversation history. (DB is per-phone, so new number = new conversation context. Trade-offs?)

6. **If Meta takes too long**: Wati/Gupshup setup walkthrough — account creation, phone number provisioning, API key generation, webhook configuration. Same goal: production-grade Indian WhatsApp number with own branding.

### Constraints
- I'm on an M-series Mac, running Railway for production
- Budget: prefer free/cheap options; Meta Cloud API direct is free up to 1000 conversations/month
- Timeline: want this live within 2-3 days
- I'm not a full-time developer — explain things clearly, assume I'll copy-paste commands

### Start by asking me
1. Do I have an existing WhatsApp Business Account under my personal/business Meta account, or should I create a new one during this setup?
2. Do I have a spare Indian phone number that's **not currently registered on WhatsApp** (personal or business)? If not, what's the fastest way to get one?
3. Status of Meta Business verification for Tiny Miracles — has anyone on the team done this before?

Once I answer those, walk me through Meta's API Setup page screen by screen. If at any point we hit a wall, we'll pivot to Wati.

---

**Separately**, my dev chat is building the Meta Cloud API webhook handler on the `feature/meta-cloud-api-webhook` branch. So when the Meta console asks for a Callback URL, I'll coordinate with that chat to get the right dev Railway URL. Don't worry about the code — just the Meta/Wati setup side.
