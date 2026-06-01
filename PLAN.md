# Astraea - Roadmap

## Current focus: Answer quality

### Q1 - Query rewrite (DONE)
Rewrite prompt now instructs the model to focus on the legal dispute and ignore
procedural sub-questions (wait times, hearing format, evidence deadlines). Fixes
the case where a long mixed question caused the rewriter to discard the substantive
dispute entirely.

### Q2 - System prompt: procedural vs substantive (DONE)
NZ tenancy system prompt now tells the model to answer procedural tribunal questions
from general knowledge without forcing [SN] citations onto them, then focus the
bulk of the answer on the substantive legal issue using retrieved decisions.

### Q3 - Concrete next steps + draft letter (DONE)
System prompt updated to always append after legal analysis:
- **What to do next** - numbered action plan (3-5 concrete steps)
- **Need a letter or email?** - offer line, and full draft when asked

If user asks for a draft, model produces complete letter/email:
date placeholder, correct addressee, legal position, required action +
deadline, professional closing. Firm but not aggressive.

Two new example buttons added to the NZ tenancy frontend:
- "Draft letter" - bond dispute letter to landlord
- "Draft email" - urgent repairs email to property manager

No new endpoints needed - works through the existing /ask/stream.

### Q4 - Answer tone (TODO)
The model still opens with hedging ("The process can be stressful...") instead of
directly addressing the user's situation and strength of their case.
Add system prompt guidance: open with a direct assessment of the user's legal
position, not a preamble.

---

## Deferred: User-local memory (no server storage)

Design agreed. Implement after quality work is stable.

**Approach:** Anonymous UUID stored in localStorage (no login, no server-side user data).

**localStorage keys:**
- `nzth_user_id` - UUID generated on first visit
- `nzth_memory` - JSON blob:
  ```json
  {
    "situation": "one-line summary of their tenancy issue",
    "key_facts": ["fact1", "fact2"],
    "history": [
      { "q": "question asked", "summary": "one-line answer summary" }
    ]
  }
  ```

**Flow:**
1. Frontend reads `nzth_memory` from localStorage on submit
2. Sends it in the request body alongside the question
3. Backend prepends it to LLM context as "User's tenancy situation so far:"
4. After the answer streams in, frontend updates localStorage with a summary of this Q&A

**Constraints:**
- Zero server-side user data - memory never persists on the server
- No auth, no login, no privacy policy changes required
- Memory lost if user clears localStorage - acceptable trade-off
- Cross-device sync not supported - acceptable for a free tool

**Work required:**
- Frontend: localStorage read/write, send memory in request body, update after answer
- Backend: accept optional `memory` field in AskRequest, inject into LLM prompt before context
- No database changes

---

## Deferred: api/server.py migration

nz-legal-rag.localrun.ai still runs the old stack (~15 specialised endpoints:
SQL search, notable cases, sentencing, contrasting cases). Complex - deferred
until quality and memory work is complete.
