# Knowledge Base

This directory contains all the domain knowledge that bhAI uses to answer employee questions.

## Structure

```
knowledge_base/
├── shared/                 # Used by ALL domains
│   ├── company_overview.md # Tiny Miracles mission, values, basics
│   ├── escalation_policy.md # When to escalate to human
│   └── style_guide.md      # How to respond (tone, length, structure)
│
├── hr_admin/               # HR-Admin domain (ACTIVE)
│   ├── policies.md         # Leave, attendance, conduct policies
│   ├── payroll.md          # Salary, deductions, bonuses
│   └── benefits.md         # Support programs, health, childcare
│
├── helpdesk/                       # Helpdesk domain (ACTIVE) — 27 files
│   ├── _index.md                   # Topic list, ALWAYS loaded by bhAI
│   ├── Helpdesk-Information.xlsx   # Source of truth (Tiny team edits this)
│   ├── aadhaar.md                  # Aadhaar card procedures
│   ├── pan_card.md                 # PAN card application
│   ├── voter_id.md                 # Voter ID procedures
│   ├── ration_card.md              # Ration card help
│   ├── esic.md                     # ESIC registration/claims
│   ├── marriage_certificate.md     # ... etc for personal documents
│   ├── domicile_certificate.md
│   ├── income_certificate.md
│   ├── residence_certificate.md
│   ├── gazette.md
│   ├── scheme_pmjay.md             # Ayushman Bharat / PM-JAY
│   ├── scheme_mjpjay.md            # Mahatma Jyotiba Phule scheme (state)
│   ├── scheme_ladki_bahin.md       # Ladki Bahin Yojana
│   ├── scheme_sukanya_samriddhi.md # Sukanya Samriddhi (girl-child savings)
│   ├── scheme_pmmvy.md             # PM Matru Vandana
│   ├── scheme_pmay_u.md            # PM Awas Yojana (Urban)
│   ├── scheme_pmjdy.md             # PM Jan Dhan
│   ├── scheme_pmmy.md              # PM Mudra Loan
│   ├── scheme_vishwakarma.md       # PM Vishwakarma
│   ├── scheme_eshram.md            # e-Shram for unorganized workers
│   ├── scheme_apy.md               # Atal Pension
│   ├── scheme_pensions_central.md  # Central old-age / widow / disability
│   ├── scheme_sanjay_gandhi.md     # Sanjay Gandhi Niradhar (state)
│   ├── scheme_nrlm.md              # NRLM self-help groups
│   ├── scheme_ujjwala.md           # PM Ujjwala LPG
│   └── scheme_other_misc.md        # Misc small schemes
│
├── production/                     # Production domain (FUTURE)
│                                   # Factory floor, machines, chai/breakfast
│
└── users/                  # Per-user profiles (200+ artisans)
    ├── _template.md        # Template for new profiles
    └── +91XXXXXXXXXX.md    # Auto-generated per-artisan profiles
```

## For Tiny Miracles Team

You contribute to the knowledge base using **Claude Code** (connected to this GitHub repo). No terminal or IDE needed.

### How to Make Changes

Tell Claude Code what you want to update. For example:

- *"Update the leave policy in knowledge_base/hr_admin/policies.md to add the new maternity leave policy"*
- *"Add information about the Aarey centre timings to knowledge_base/helpdesk/"*
- *"Fix the salary deduction rules in knowledge_base/hr_admin/payroll.md"*

Claude Code will edit the file, create a branch, and push the changes. Sundar will review and approve.

### Adding to the Knowledge Base

The folder layout above is **not optional** — bhAI's code finds answers by reading specific paths and the topic list in `helpdesk/_index.md`. Edit content freely, but **keep the structure** (don't rename or move folders), and follow the case that matches what you're doing:

**1. Fixing or updating an existing topic** — edit the matching file in `helpdesk/` (a changed fee, phone number, centre address in, say, `voter_id.md`). Keep the existing section headings (`## Keywords`, `## Common Questions & Answers`, `## Required Documents`, `## Centre Address`) — bhAI relies on them. Nothing else to touch.

**2. Adding a brand-new topic** (a new government document, scheme, or service) — two steps, **both required**:
1. Create the file `helpdesk/<short_name>.md` (lowercase, underscores — e.g. `birth_certificate.md`). Copy the layout of an existing file like `voter_id.md`: open with a `## Keywords` line (the words a user might actually say — bhAI matches on these), then the Q&A and documents.
2. Add one line to `helpdesk/_index.md` under the right heading (*Documents & IDs* or *Government Schemes*), e.g. `- Birth certificate — apply, corrections, where to go`. **If it isn't in `_index.md`, bhAI will never find it** — that index is the only list it reads to know what it can answer.

Keep entries short — every loaded file goes into bhAI's working memory, so bloat means slower, costlier replies.

**3. Adding a whole new *theme*** — any document/scheme/government service is just a new topic (use case 2 above). But a fundamentally different *kind* of help — health guidance, legal aid, a production-floor helpdesk — is more than a KB file: it needs a small **code** change (a new "use case" so bhAI knows when to pull it, plus routing). **Don't try to wire that up by reorganising folders — it won't work and can break routing.** Instead, put your draft content in a new file, open the PR, and **flag it to Sundar in the PR description** ("new theme — needs code wiring"). He adds the few lines of code so it plugs into the existing setup cleanly.

### Writing Guidelines

- **Use simple Hindi** - the same way you'd explain it to a colleague
- **Keep it short** - target 20-40 seconds when read aloud
- **Focus on what workers actually ask** - practical, not theoretical
- Use headings (`##`) to organize topics
- Use bullet points for steps

### Example Entry

```markdown
## Leave Request Kaise Kare?

1. Pehle team lead ko WhatsApp/call karo
2. Reason batao (sick/planned/emergency)
3. Jaldi message karo - late mat karo
4. Calendar me mark hoga automatically
```

### Editing bhAI's Personality

bhAI's personality and conversation rules live in `src/bhai/llm/prompts/` (not in this folder). You can edit those too — see [CONTRIBUTING.md](../CONTRIBUTING.md#editing-bhais-personality-system-prompt) for instructions.

### How bhAI uses these files

bhAI doesn't load every file every turn — that would blow the context window. Instead:

- **shared/** files (company overview, escalation policy, style guide) are reference docs — bhAI's live persona, voice, and escalation rules now live directly in the system prompt (`src/bhai/llm/prompts/prompt_v1_pilot.md`), so editing shared/ alone won't change behavior
- **helpdesk/_index.md** is always loaded (topic list, so bhAI knows what it *can* answer)
- **helpdesk/{topic}.md** files are loaded only when a user asks something matching that topic. Claude Sonnet 4.6 reads each user query and picks 1-3 relevant files. See [ARCHITECTURE.md §5](../ARCHITECTURE.md#5-kb-retrieval-llm-routed).
- **hr_admin/** files are loaded as part of the HR pipeline when applicable

This means **adding a new helpdesk file requires updating `_index.md`** so the router can discover it. The file body itself isn't seen by the router — only by the main LLM when that topic is matched.

### Updating the helpdesk source-of-truth

`helpdesk/Helpdesk-Information.xlsx` is the Tiny-team-editable source. The 27 markdown files are derived from it via a manual offline conversion (no runtime ingestion). When the Excel changes:

1. Re-export each topic sheet to its corresponding `.md` file
2. Update `_index.md` if topic names changed
3. Open a PR — Sundar reviews and merges

### Important Notes

- **shared/** files are used by ALL domains - edit carefully
- **Domain folders** (hr_admin, helpdesk, production) are specific to each use case
- **`_index.md` is special** — bhAI reads it every turn, so keep it short and current
- All changes go through a pull request — `main` branch is protected (1 approval required)
- Changes take effect on next bot restart
