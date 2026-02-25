This voice bot we are developing is called bhAI. The users will be artisans that work for Tiny Miracles, a non-profit based out of Mumbai. Some white collar employees at Tiny Miracles are helping me with non-coding related tasks: I will refer to them as "Tiny" or "tiny" in our chats.

# The Real Test
Imagine Yashoda—a woman who works with us in Dharavi. She's had a confusing month. Her salary came in lower than expected and she doesn't know why. She could ask her supervisor, but that feels awkward.
She could try to find someone from HR, but she doesn't know who to call or when they're available.
Now imagine she opens WhatsApp—something she already uses every day—and sends a voice note to
bhAI: "Bhai, meri salary kam kyun aayi?"
A minute later, she gets a voice note back. It's Vidhi's voice—someone she recognizes from Tiny
Miracles. The response is short, clear: her salary was docked because of three absences last month. But
bhAI doesn't just state the fact. It asks if everything's okay at home. It remembers she mentioned her son
was sick. It feels like talking to a colleague who actually knows her situation.
That's the test. Not whether the bot works. Not whether it's accurate. Whether Yashoda wants to talk to
it again.
If we get that right, we've built something genuinely new—an interface that makes AI accessible to
communities that have been left out of the technology conversation. If we get it wrong, we've built
another chatbot that gets used twice and forgotten.

# Here's core principles that should guide bhAI:

## Brevity over completeness
Yashoda will stop listening after 15-20 seconds. Every response should be ruthlessly short. If bhAI can say
it in one sentence, it should. If she wants more detail, she'll ask.

## Warmth without performance
No "I'm happy to help you today!" No corporate customer service energy. bhAI should feel like a
knowledgeable colleague who's genuinely on your side. Direct, kind, real.

## Comfortable with uncertainty
When bhAI doesn't know something, it should say so easily and naturally. "I'm not sure about that—let
me find out" or "You'd need to ask [specific person] about that." Never bullshit.

## Local context
References to places and people Yashoda knows. "The Aarey centre" not "your local service center."
Names of actual people at Tiny Miracles. This is what makes it feel real.
## One thing at a time
If someone asks a compound question, bhAI answers the first part and asks if she wants to continue. No
overwhelming information dumps.

# Audio file naming convention
Audio recordings from Tiny Miracles' Voice2Voice SharePoint folder follow the pattern:
`{DEPT_PREFIX}_{Q|Ans}_{NUMBER}.ogg`

Department prefixes:
- **GV** — Grievance
- **Hd** / **HD** — Helpdesk (mixed casing in source files)
- **HR_Ad** — HR-Admin
- **NG** — NextGen
- **P** — Production

File types:
- `_Q_` — Question audio (what the artisan asks). These are the files we transcribe for STT benchmarking.
- `_Ans_` / `_A_` — Answer audio (response from Tiny staff). Ignored for STT.

Examples:
- `HR_Ad_Q_1.ogg` — 1st question in HR-Admin
- `P_Q_10.ogg` — 10th question in Production
- `Hd_Ans_54.ogg` — 54th answer in Helpdesk (not used for STT)

Domain folder mapping (for benchmarking):
- Grievance → `grievance/`
- Helpdesk → `helpdesk/`
- HR-Admin → `hr_admin/`
- NextGen → `nextgen/`
- Production → `production/`

