# Community Research + Interactive Button Infrastructure

> Session: 2026-06-24. Community feedback on post-response suggestions + Hermes interactive button infrastructure audit.

## Community Research Findings

### ChatGPT Follow-Up Backlash (r/ChatGPT, OpenAI forums)

- **r/ChatGPT** thread: *"Is there REALLY no way to stop the 'Want me to...' suggestions after every response?"* — Users describe follow-ups as "disruptive," "clutter," "can't disable," "even when it promises not to do it it still does."
- Another thread: user did experiment answering "no" to every follow-up — found them "annoying at first" but "starting to appreciate" them **when contextually relevant**. Value depends entirely on relevance, not frequency.
- **Lesson for Hermes**: Default to silence. Only suggest when genuinely non-obvious. Suppressibility is mandatory.

### "Absolute Mode" Anti-Suggestion Movement (r/PromptEngineering)

- Viral prompt: *"Eliminate: emojis, filler, hype, soft asks, conversational transitions, call-to-action appendixes."*
- Users report "Terminator-like responses" with "a new level of clarity."
- Revised GPT-5 version adds: *"If it knows the next logical step, it should just do it and move me forward, unless there's a real risk."*
- One user: *"I particularly like forcing it to tell me how confident it is in its answer in the footnote."*
- Counter-movement: Medium article *"The Absolute Mode Prompt Trap: How Minimal AI Kills Cognitive Depth"* — argues stripping all guidance makes AI less useful for complex reasoning.
- **Lesson for Hermes**: The "Do, Don't Suggest" principle — if the next step is low-risk and reversible, Hermes should just DO it (existing persona already says this). Suggestion block is only for things needing user decision/verification. Consider optional confidence indicator.

### CHI 2025: Proactive Assistant Study (ACM CHI 2025, arxiv.org/abs/2410.04596)

- Controlled study, 61 participants, proactive programming assistant.
- **Five design considerations**: (1) support efficient evaluation, (2) support efficient utilization, (3) show contextually relevant suggestions, (4) time suggestions based on context, (5) incorporate user feedback.
- **Key finding**: All proactive variants significantly outperformed reactive baseline (12-18% more test cases passed). BUT the "Persistent Suggest" condition (5 suggestions, frequent) performed **worse** than standard "Suggest" (3, less frequent).
- **Lesson**: More suggestions = worse performance. Validated the "max 2-3 items" rule. Phase 2 should track user feedback (accept/reject) to adapt frequency.

### CMSWire: 10 UX Design Patterns for AI Trust

Relevant patterns:
- **Confidence Scores**: could add confidence indicator to suggestions (optional 4th component)
- **Progressive Disclosure**: suggestion block = first layer; user can ask for more detail
- **Source Attribution**: "Learn" could cite which tool/skill was used
- **User Control**: Phase 1 `/suggestions off` gives user control
- **Personalization**: already in design via memory-based adaptive depth
- **Feedback Collection**: Phase 2 should track whether users follow suggestions and adapt

### MindStudio: Proactive AI Design Principles

Five design principles for proactive AI:
1. **Clear Scope** — well-defined domain, not "monitor everything"
2. **Low False-Positive Tolerance** — "surface only meaningful signals to avoid being ignored" — **critical**: irrelevant suggestions train users to ignore all future suggestions
3. **Appropriate Action Levels** — match action to confidence/stakes (inform vs draft vs act)
4. **Observability** — maintain logs of what the agent did and why
5. **Easy Override** — humans must always be able to pause/modify/override

### r/UXDesign: "What I've Learned from 18 Months of AI Conversational UI Design"

- AI interfaces evolving from GUIs to natural language experiences
- **In-chat product recommendations based on real data** are an emerging pattern — anchored in actual user context, not generic
- **Progressive disclosure** — show summary, let user dig deeper

## Hermes Interactive Button Infrastructure (Existing)

Hermes already has interactive button infrastructure used for approval prompts. This is directly reusable for suggestion buttons in Phase 1.

### Telegram (`gateway/platforms/telegram.py`)

- **Imports**: `InlineKeyboardButton`, `InlineKeyboardMarkup` (line 24)
- **Callback handler**: `CallbackQueryHandler(self._handle_callback_query)` (line 1618) — routes callback data prefixes
- **Existing patterns**:
  - `ea:` (exec approval) — `ea:once:{id}`, `ea:session:{id}`, `ea:always:{id}`, `ea:deny:{id}`
  - `mp:` (model picker)
  - `gt:` (Gmail triage)
  - `update_prompt:y` / `update_prompt:n`
- **`send_exec_approval`** (line 2621): sends inline keyboard with Allow Once/Session/Always/Deny buttons
- **`send_update_prompt`** (line 2578): sends Yes/No inline keyboard
- **Callback resolution**: `self._approval_state` dict maps IDs to session keys; `_handle_callback_query` (line 3204) routes by prefix

### Slack (`gateway/platforms/slack.py`)

- **Block Kit support**: sends `blocks` JSON with `chat_postMessage` (line 2719)
- **Action handlers**: registered via `self._app.action(action_id)(handler)` (line 935)
- **Existing action_ids**: `hermes_approve_once`, `hermes_approve_session`, `hermes_approve_always`, `hermes_deny`, `hermes_confirm_once`, `hermes_confirm_always`, `hermes_confirm_cancel`
- **`send_exec_approval`** (line 2646): sends Block Kit with `section` + `actions` blocks containing styled buttons (primary/danger)
- **`_handle_approval_action`**: resolves approval via `resolve_gateway_approval()`
- **Button update**: `chat_update` removes buttons after resolution (lines 2847, 2958)

### WhatsApp (`gateway/platforms/whatsapp.py`)

- **No interactive button support** — no `send_exec_approval` method, no `send_update_prompt` method
- Only has: `send`, `send_image`, `send_image_file`, `send_video`, `send_voice`, `send_document`, `send_typing`
- Text-based `/approve` is the fallback for approval prompts
- Baileys supports interactive messages (reply buttons, list messages) but Hermes doesn't implement them
- WhatsApp Business Cloud API supports up to 3 quick-reply buttons (different adapter path)

### Other Platforms

- **Matrix** (`matrix.py`): has `send_exec_approval` (line 1265)
- **Discord**: buttons + select menus available
- **Feishu** (`feishu.py`): interactive card support (line 1865, 1968)

### Phase 1 Implementation Pattern

To add interactive suggestion buttons, follow the existing approval pattern:

1. Add `send_suggestion(chat_id, suggestion_text, actions, metadata)` method to platform adapters
2. Telegram: `InlineKeyboardMarkup` with `sg:explain`, `sg:do`, `sg:dismiss` callback data
3. Slack: Block Kit `divider` + `section` + `actions` with `hermes_suggest_explain`, `hermes_suggest_do`, `hermes_suggest_dismiss` action_ids
4. WhatsApp: text-only fallback (no buttons)
5. Register new action handlers in Slack init, new callback prefix in Telegram `_handle_callback_query`
6. "Do it" injects synthetic message to agent; "Explain" injects follow-up query; "Dismiss" edits message to remove buttons

## Key Design Principles Synthesized from All Research

1. **Default to silence** — better to stay silent than suggest something irrelevant (MindStudio #2, ChatGPT backlash, CHI 2025)
2. **Do, don't suggest** — if low-risk and reversible, just do it (Absolute Mode movement, Hermes existing persona)
3. **Fewer is better** — more suggestions = worse performance (CHI 2025 Persistent Suggest condition)
4. **Anchor in context** — every suggestion must reference what just happened (ShapeofAI)
5. **Show why** — each suggestion needs a reason (ShapeofAI)
6. **Visually separate** — use interactive buttons where available, not text appended to response (ShapeofAI, community feedback)
7. **Suppressible** — user must be able to disable (ChatGPT backlash)
8. **Adaptive** — reduce frequency as user familiarity grows (ShapeofAI, Hermes memory)
9. **Track feedback** — adapt based on whether users follow suggestions (CHI 2025, MindStudio)
10. **Easy override** — "Dismiss" button or text command always available (MindStudio #5)