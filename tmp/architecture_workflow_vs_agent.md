# bhAI Architecture — Workflow vs Multi-Agent Critique

**Date**: 2026-05-24
**Question on the table**: should bhAI move from its current "API-calls-in-a-pipeline" architecture to a multi-agent system — one dedicated agent per user, calling specialised sub-agents for (1) workplace grievances, (2) salary/PF/loan lookups, (3) govt scheme KB, (4) general "stuff you'd Google"?
**Inputs**:
- [ARCHITECTURE.md](../ARCHITECTURE.md) — current end-to-end pipeline
- [src/bhai/llm/haiku_router.py](../src/bhai/llm/haiku_router.py) — existing KB routing layer
- External research scan (Anthropic engineering blog, Cognition, Letta/MemGPT, Karpathy/Willison, Hamel Husain) — sources at bottom

---

## TL;DR

The framing of the question is slightly off, and that matters. **bhAI is not "just API calls."** It is already a four-LLM-call routing-plus-chaining *workflow* in Anthropic's taxonomy: Haiku KB router → Sonnet main → summariser (every 5 turns) → nudge LLM (twice a day). That is on the *workflow* side of Anthropic's workflow-vs-agent spectrum, not pre-workflow.

The proposed "dedicated agent per user + 4 specialist sub-agents" is **not the cheapest way to absorb the expanding use-case surface**, and three independent primary sources predict it will fail or massively overspend at this scale:

1. **Anthropic's own data**: multi-agent systems use ~15× more tokens than chat and only pay off on high-value, parallelisable tasks. A single-user voice turn is neither.
2. **Cognition's "Don't Build Multi-Agents"**: the exact failure mode this proposal would hit is sub-agents seeing slices of the user's state and returning inconsistent guidance that a parent agent has to reconcile in Hindi voice on a 2-second budget.
3. **Karpathy / Willison**: the bhAI problem is a *context engineering* problem (route + retrieve + compose), not an orchestration problem.

The right move is to **stay on the workflow side and extend it**:

- **Now** (1 day): extend the Haiku router to also emit a *use-case tag* (`grievance | finance | scheme_kb | general`) and inject a task-specific instruction block into the Sonnet system prompt.
- **Soon** (½–1 week): upgrade memory from "regenerated every 5 turns" to a self-edited core block (Letta-style `core_memory_append`, or Anthropic's first-party memory tool if you also want context-editing's 84% token reduction).
- **Later** (when there is a real system of record): add salary/PF/loan as a *tool* the same Sonnet turn can call, not as an agent.
- **Only if** a use case genuinely needs multi-step planning ("file the grievance → draft email → wait → follow up"): build a *single* tool-using agent — never sub-agents. This is the one place Anthropic's "open-ended, can't hardcode a fixed path" criterion is met, and even there Cognition's rule (one thread, shared context, no fan-out) applies.

Memory architecture matters more than agent architecture for what you're trying to do.

---

## Re-framing the question — what bhAI actually is today

The user message describes the current state as "API calls for STT, inference, and TTS." That undersells what's already there. The actual per-turn topology (from [ARCHITECTURE.md](../ARCHITECTURE.md) §1–§10) is:

```
Telegram webhook (auth + rate-limit)
   → Sarvam STT
   → Session/onboarding detection
   → Haiku 4.5 KB router  ← LLM call #1 (returns 1-3 KB file stems)
   → Load matched KB files into system prompt
   → Sonnet main generation  ← LLM call #2
   → _strip_markdown / _strip_reasoning_leak
   → Sarvam (or ElevenLabs) TTS
   → sendVoice
   [async] every 5 user msgs: Summariser  ← LLM call #3
   [async] 2x/day: Nudge generation  ← LLM call #4
```

That is, by name, three of Anthropic's five workflow patterns in one pipeline: **prompt chaining** (KB router → main), **routing** (Haiku picks KB scope), and a form of **orchestrator-workers** at the async layer (summariser + nudger as background workers writing back into the per-user state the next turn reads).

Memory is already compressed in the way Cognition specifically recommends: rolling 3-4 line Hindi summary + extracted facts + last 8 turns (ARCHITECTURE.md §9). Per-user state is Fernet-encrypted in SQLite on a Railway volume.

This matters because **the question is not "single call vs. agents."** It is "extend the workflow vs. switch paradigm to agents." And the literature is very clear on that specific question.

---

## What the primary sources say

### 1. Anthropic — *Building Effective Agents* (Schluntz & Zhang, Dec 2024)

This is the canonical taxonomy. The terminology I'm using above (workflow / routing / chaining / orchestrator-workers) is theirs. Their explicit guidance on when to escalate to agents:

> "Agents can be used for open-ended problems where it's difficult or impossible to predict the required number of steps, and where you can't hardcode a fixed path."

And the headline rule:

> "We recommend finding the simplest solution possible, and only increasing complexity when needed. This might mean not building agentic systems at all… Success in the LLM space isn't about building the most sophisticated system. It's about building the *right* system for your needs."

bhAI's reply loop is the opposite of their criterion: every turn produces exactly one voice note within ~5–10 seconds. The number of steps *is* predictable. There is no plan-and-act loop the LLM needs to control.

### 2. Anthropic — *How we built our multi-agent research system* (June 2025)

Anthropic's own multi-agent post is both a how-to and a cautionary tale. The cost reality:

> "In our data, agents typically use about 4× more tokens than chat interactions, and multi-agent systems use about 15× more tokens than chats."

The economic threshold:

> "Multi-agent systems require tasks where the value of the task is high enough to pay for the increased performance… multi-agent systems excel at valuable tasks that involve heavy parallelization, information that exceeds single context windows, and interfacing with numerous complex tools."

And the explicit anti-pattern:

> "Some domains that require all agents to share the same context or involve many dependencies between agents are not a good fit for multi-agent systems today… LLM agents are not yet great at coordinating and delegating to other agents in real time."

For bhAI: each user turn is low-value (one Hindi reply), highly sequential (one user is speaking), depends on shared context (the artisan's profile, last 8 turns, KB). Four-for-four against multi-agent fit. A 15× token blow-up on a 5-user pilot does not move the needle on Sundar's mission; it does move the needle on the monthly Railway + Anthropic bill.

### 3. Cognition AI — *Don't Build Multi-Agents* (Walden Yan, June 2025)

The famous counter-view. The bit that directly hits the proposal:

> "The key failure point is [when] subagents misunderstand their subtasks and produce inconsistent work that a final agent must reconcile… Actions carry implicit decisions, and conflicting decisions carry bad results."

His two principles:

> "Principle 1: Share context, and share full agent traces, not just individual messages."
> "Principle 2: Actions carry implicit decisions, and conflicting decisions carry bad results."

His recommended alternative is a **single-threaded linear agent** because "the context is continuous" throughout execution. Where context grows too big, he recommends compression — *exactly* what bhAI's summariser already does.

The proposed architecture (grievance sub-agent + finance sub-agent + KB sub-agent + general sub-agent under a per-user orchestrator) is the architecture he's specifically arguing against. The failure mode he predicts is concrete for bhAI: an artisan mentions PF deduction *and* asks about Aadhaar *and* hints at a workplace issue in the same voice note (this is the modal real transcript shape, see `tmp/manimala_loan_audit.md`). The grievance sub-agent sees one slice, the finance sub-agent sees another, neither sees the joint state, and the parent agent has to reconcile two different opinions about what the user actually needs in 20-40 seconds of Hindi.

### 4. Memory — Anthropic's first-party memory tool (Oct 2025)

Anthropic shipped a memory primitive that's directly relevant to the "agents are always on / how do we manage growing memory" worry in the user's message:

> "The memory tool enables Claude to store and consult information outside the context window through a file-based system. Claude can create, read, update, and delete files in a dedicated memory directory stored in your infrastructure that persists across conversations."

Companion feature, *context editing*:

> "Context editing automatically clears stale tool calls and results from within the context window when approaching token limits."

Their benchmark numbers (100-turn web-search eval):

> "Combining the memory tool with context editing improved performance by 39% over baseline."
> "Context editing alone delivered a 29% improvement… while reducing token consumption by 84%."

For bhAI: the memory tool is Anthropic's blessed version of what bhAI is already doing manually (rolling summary + extracted facts), but with **file-grain edits the model itself performs via tool calls** instead of a periodic summariser. The 84% token reduction is the headline number Sundar should care about on a Railway-budget pilot. The cost is non-trivial: per Anthropic's docs, the implementer must enforce path-traversal protection, track file sizes, and — for bhAI specifically — encrypt at rest with `BHAI_ENCRYPTION_KEY` before write, because the religion/caste/disability/loan rule applies to a memory directory the same as it applies to an outbound API call.

### 5. Letta / MemGPT (Charles Packer et al., 2023 paper → 2024+ company)

The most-cited research architecture for long-running conversational memory. Three tiers:

- **Core memory** — in-context, pinned, model-edited via `core_memory_append` / `core_memory_replace`. This is what's "always there" for the agent.
- **Recall memory** — full conversation history, queried via `conversation_search`.
- **Archival memory** — externally indexed knowledge, queried via `archival_memory_search` / `archival_memory_insert`.

The architectural idea worth stealing for bhAI *without* adopting the whole framework is the **core-memory block**: a small, pinned, per-user paragraph the model itself maintains. Replacing "every-5-turns regenerated summary" with "Sonnet emits a `<memory_patch>` block on every turn, code applies it" is a half-day change. That gets you Letta's self-editing memory in bhAI's existing schema without a new dependency.

### 6. Karpathy + Willison — *context engineering* (June 2025)

> "+1 for 'context engineering' over 'prompt engineering'… context engineering is the delicate art and science of filling the context window with just the right information for the next step." — Karpathy

This is the frame Sundar should adopt. **The bhAI problem isn't "do we need agents?" It's "what's the right context to put into the Sonnet call when the user mentions PF *and* a grievance *and* asks a Google-style question in the same voice note?"** That's a routing-and-retrieval problem — exactly the layer where bhAI's Haiku router already lives. Extending it is cheap; replacing it with sub-agents is expensive and, per the Cognition argument, worse.

### 7. Hamel Husain — *evals first*

Triangulation, but the most useful operational point: before any architectural change, cluster the failure modes in real transcripts. bhAI already has them (`tmp/lying_audit_transcripts.md`, `tmp/manimala_loan_audit.md`, `tmp/user_n_analysis.md`). Half a day labelling each failure as a routing miss vs. a generation miss vs. a context-compression miss tells you which architectural lever to pull. Without that, the workflow-vs-agent choice is guesswork.

---

## Direct critique of the multi-agent proposal

Taking the proposal at face value — one dedicated agent per user, calling 4 specialist sub-agents (grievance, finance, KB, general) — and stress-testing it against the sources above:

**(a) "Always on" agents don't fit voice.** The user's worry — "are agents always on by design? coz maybe that isn't needed" — answers itself the moment you look at the pipeline. bhAI's turn is reactive: voice note in → 5–10s of work → voice note out. There is no background reasoning loop that benefits from an always-on agent. "Always on" makes sense for long-horizon tasks (background research, monitoring inboxes, batch processing). For a synchronous voice turn it's pure overhead.

**(b) Sub-agents do not solve the use-case-surface problem.** The actual problem is *what content + what tone-instruction* the Sonnet call gets when the user's intent is ambiguous (the modal real case). Sub-agents don't help with this — they make it harder, because now four agents independently decide what they think the user needs, and the parent has to reconcile. The Haiku router already solves the easier version of this (which KB files to inject); extending it to also tag the use-case is the same lever, scaled up.

**(c) The 4 use cases are heterogeneous in a way that bites multi-agent.** Grievances need **memory and outreach gating** (the `ESCALATE: true` mechanism + the outreach-honesty rule in [prompt_v1_pilot.md](../src/bhai/llm/prompts/prompt_v1_pilot.md):102–123). Finance lookups need **a real backend** (system of record for salary/PF/loan — bhAI doesn't have one yet). KB needs **retrieval over your existing helpdesk corpus**. General-purpose needs **the model itself, no augmentation**. These don't share an interface. A grievance "agent" is mostly prompt + escalation; a finance "agent" is mostly a database query; a KB "agent" is mostly retrieval. Calling all four "agents" hides the fact that three are tools and one is a prompt mode.

**(d) Latency and cost are not free.** Anthropic's 15× number is for their research agent (long-form, deeply parallel). bhAI wouldn't hit 15× on every turn, but a per-turn orchestrator dispatching to even 1–2 sub-agents serially adds 2–4 seconds and 3–5× token cost. On a synchronous voice loop this is felt by the user. Bhai's whole appeal is that it sounds like a friend who replies fast; making her think twice as long for the same answer would be a regression.

**(e) The trust-repair architecture (ARCHITECTURE.md §16) gets worse, not better, with sub-agents.** When bhAI confabulates, Sundar issues a literal text via `POST /admin/send-message` that bypasses the LLM and writes the correction directly into history. This works because there is *one* history thread the next LLM call reads. In a multi-agent setup, corrections have to be propagated to every sub-agent that might next handle the user — or you accept that the grievance agent doesn't know what the finance agent just got corrected on. Cognition's "share full context" principle directly indicts this.

**(f) The pilot scale is 5 users.** Architectural moves that pay off at thousands of users (sub-agent specialisation, parallel research) don't pay off at five. The cheapest learning loop right now is "look at the transcripts → change the prompt or the router → look again" — exactly the Hamel loop. Sub-agent infrastructure adds rungs to that ladder for no learning gain.

None of this means the multi-agent proposal is *wrong forever*. It means **it's wrong now**, and the conditions under which it would become right (a use case that genuinely needs multi-step planning, a real system of record for finance, scale where parallelism would pay) aren't met yet.

---

## What to build instead — concrete plan in cost order

### Step 0 — failure-mode triage (½ day, no code)

Cluster every confabulation / wrong answer / off-topic reply in the existing transcripts against the four use-case buckets (grievance / finance / KB / general). For each cluster, label: *routing miss* (wrong KB file picked), *generation miss* (right KB, wrong Hindi), *memory miss* (forgot a key fact from a prior turn), or *prompt miss* (the rule isn't there). The architecture choice falls out of the breakdown. If 80% are generation misses, no amount of routing or memory work helps — go back to the prompt.

### Step 1 — use-case routing tag (1 day)

Extend [haiku_router.py](../src/bhai/llm/haiku_router.py) so the same Haiku call that picks KB files also emits a use-case tag:

```json
{ "kb_stems": ["aadhaar", "pf_basics"], "use_case": "finance" }
```

In [base.py](../src/bhai/llm/base.py) `_build_system_prompt()`, inject a small task-block keyed off the tag (e.g., `=== Finance Mode ===` adds "ask which company / which month / always cite a source, never invent a number"). This is **still one Sonnet call**, with the prompt slightly differentiated by intent. It's Anthropic's routing pattern, scaled up by one dimension. No new dependencies.

### Step 2 — memory upgrade (½–1 week)

Pick one of:

- **(2a)** Keep the SQLite schema but switch the summariser from "regenerate every 5 turns" to "Sonnet emits `<memory_patch>` blocks each turn, code parses + applies them" (Letta-style self-editing core memory). Lighter touch, no new vendor. ~½ day.
- **(2b)** Adopt Anthropic's first-party memory tool with a Fernet-encrypted file backend constrained to `/app/data/memories/<phone_hash>/`. Buys you context-editing's 84% token reduction on long conversations. More work — file-system tool plumbing, path-traversal protection, the encryption layer. ~1 week.

(2a) is the right first move. Revisit (2b) once you see actual token cost growing past your budget — likely only after the pilot scales past 5 users.

### Step 3 — finance as a *tool*, not an agent (when a backend exists)

If/when there's a real system of record for salary / PF / loan-repayment status (Tiny Miracles backend or otherwise), expose it as a single tool call from the same Sonnet turn:

```python
@tool
def get_finance_status(user_id: str, category: Literal["salary", "pf", "loan"]) -> dict: ...
```

Sonnet decides whether to call it given the user's question. This is "advanced tool use," not multi-agent. The workflow still terminates in one voice reply.

### Step 4 — a single tool-using agent for *outreach only* (if/when needed)

The one place agents genuinely fit is the outreach + follow-up loop that the current `ESCALATE: true` + trust-repair mechanism gestures at: file the grievance → draft the email/WhatsApp to Vijay/Priti → wait for response → follow up with the user. This is open-ended in Anthropic's exact sense. Even here, build it as **one** agent with tools (`draft_message`, `send_message`, `wait_for_reply`, `update_user`), not as a constellation of sub-agents. Cognition's principle 1 — share full context, one thread — applies.

This is a much later move and should not gate steps 1–3.

---

## What this means for the user's specific worries

> "as memory of the chats grow, we need to use complex memory management techniques to rely on API calls, right? like scrunch down the user chat to a summary to feed in with the prompt for the API call."

Yes, and you're already doing the right thing (rolling summary + extracted facts). The cheap upgrade is letting the model edit the summary itself instead of regenerating it every 5 turns (Step 2a). The expensive upgrade is Anthropic's memory tool (Step 2b) — defer until the bill or the failure modes force it.

> "Are Claude's managed sub-agents a good replacement to this?"

Not for this use case. Anthropic's own multi-agent post is upfront that the orchestrator-workers pattern is for "valuable tasks that involve heavy parallelization, information that exceeds single context windows, and interfacing with numerous complex tools." A voice turn for one artisan is none of those. The first-party *memory tool* is a good fit; the multi-agent pattern is not.

> "are agents 'always on' by design? coz maybe that isn't needed."

Right instinct. Agents are not always-on by default — they run when triggered. But the *cost model* of an agent assumes a longer-running, multi-step task where the model controls its own loop. For bhAI's reactive voice turn there's no loop for it to control, so the agent abstraction is pure overhead.

---

## At what scale of users does it start making sense to consider agents?

Short answer: **user scale is not the primary trigger.** Per-turn task shape is. But scale does change which agent patterns become economically viable, and the two interact. Here's the honest decomposition.

### Why "scale of users" is partly a misframe

Anthropic's 15× token multiplier is *per turn*, not per user. A multi-agent reply costs ~15× whether you have 5 users or 5 million. Scaling users doesn't make the per-turn economics work — it just spreads the fixed cost of building the agent infrastructure. What actually unlocks agents is:

1. **A use case that genuinely needs multi-step planning the model controls.** Anthropic's criterion: "open-ended problems where it's difficult or impossible to predict the required number of steps, and where you can't hardcode a fixed path." For bhAI, the reactive voice turn never meets this. The outreach/follow-up loop does.
2. **Parallelism that pays for the orchestration overhead.** Anthropic's Research agent fans out across many sources simultaneously — that's where the multi-agent pattern earns its 15×. A single artisan asking a single question has nothing to parallelise.
3. **A tool surface too complex for one prompt to use well** (Anthropic: "interfacing with numerous complex tools").
4. **Task value high enough to absorb the cost.** Anthropic's own line: "Multi-agent systems require tasks where the value of the task is high enough to pay for the increased performance."

None of those are unlocked by adding users. They're unlocked by adding *the right kind of task*.

### Where scale actually does matter

User scale changes the **secondary economics**, not the primary fit:

- **Below ~50 users (bhAI today)**: the cheapest learning loop is "look at transcripts → tweak prompt or router → look again" — exactly Hamel's eval-first loop. Agent infrastructure adds rungs to that ladder for no learning gain. Stay on workflow.
- **~50–500 users**: manual transcript triage breaks. Investment in a real eval harness, automated failure clustering, and better routing pays off. *Still workflow*, but with more discipline around the routing layer. Memory upgrade (Step 2 in the plan above) becomes more valuable because user-fact density grows. This is also where a **single tool-using agent for outreach** (Step 4) starts paying for itself, because manual `POST /admin/send-message` corrections don't scale.
- **~500–5,000 users**: token cost is now a real line item. Anthropic's first-party memory tool (Step 2b) becomes attractive on its own merits — 84% token reduction × 5,000 users adds up. Fine-tuned routing models or smaller-model variants for specific subtasks become ROI-positive. You might have *one* sub-agent for a specific bounded high-value flow (e.g., a grievance-filing agent that handles draft → escalate → follow-up across multiple turns) — but the main chat path is still workflow.
- **~5,000+ users**: dedicated backend integrations (real PF/loan system of record exposed as tools) pay for themselves. Multi-agent might make sense for one or two specific high-value flows that genuinely fan out (e.g., a daily digest agent that pulls scheme updates from multiple government sources for each user — that's parallel and information-rich). The reactive voice path is *still* a workflow, because the per-turn task shape hasn't changed.

There is no scale at which the *main reply path* should become multi-agent for a voice-companion product. The shape of "one user speaks → one bot replies" is fundamentally a single-thread workflow at any scale. What scale unlocks is **adjacent capabilities** (proactive digests, long-running outreach, batch processing) that can be agent-shaped without touching the main loop.

### Cross-checking against Anthropic's own product

Anthropic's multi-agent post is about their *Research* feature on Claude.ai — a product serving millions of users where each Research query is high-value (often replaces hours of analyst work) and parallelisable across sources. That's the canonical fit. bhAI's main loop has neither property. Even if bhAI grew to a million users, the per-turn task shape — a single artisan asking a single question — would still be wrong for multi-agent. The right pattern at million-user scale for a voice bot like bhAI is still a workflow, just with much better routing, memory, and tooling.

### Concrete trigger conditions, not user counts

Better than thresholds: revisit the workflow-vs-agent question when *any* of these become true, regardless of user count:

- A use case appears that needs the model to plan over **3+ internal steps** before the user sees a reply (and you've already tried prompt chaining and routing).
- Token spend on a specific flow exceeds **~30% of total bill** and Step 2b's context-editing isn't enough.
- You have a tool surface **>10 tools** that one prompt can't reliably navigate.
- A flow needs to **run for minutes/hours** in the background (outreach follow-up, batch enrichment) — agent loop is natural here.

None of these are bhAI's current state. If you grow to 500 users and still none of them are true, you still don't need agents.

---

## Sources

- [Building Effective Agents — Anthropic Engineering, Dec 2024](https://www.anthropic.com/engineering/building-effective-agents)
- [How we built our multi-agent research system — Anthropic Engineering, June 2025](https://www.anthropic.com/engineering/built-multi-agent-research-system)
- [Don't Build Multi-Agents — Walden Yan, Cognition, June 2025](https://cognition.ai/blog/dont-build-multi-agents)
- [Context management on the Claude Developer Platform — Anthropic, Oct 2025](https://claude.com/blog/context-management)
- [Memory tool — Claude API docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
- [Agent Memory — Letta blog](https://www.letta.com/blog/agent-memory)
- [Andrej Karpathy on "context engineering" — X, June 2025](https://x.com/karpathy/status/1937902205765607626)
- [Context Engineering — Simon Willison, June 2025](https://simonwillison.net/2025/jun/27/context-engineering/)
- [LLM Evals FAQ — Hamel Husain](https://hamel.dev/blog/posts/evals-faq/)
