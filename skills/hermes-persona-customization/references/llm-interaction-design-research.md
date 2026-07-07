# LLM Interaction Design Research

Condensed research on post-response suggestion patterns, follow-up UX, and proactive agent design.
Sources evaluated Jun 2026 for the post-response suggestion block feature.

## ShapeofAI "Follow Up" Pattern

Source: shapeof.ai/patterns/follow-up (Emily Campbell, CC-BY-NC-SA)

Most rigorous UX treatment of post-response follow-ups.

### Definition
> "Follow ups are prompts, questions, or inline actions that help users refine or extend their initial interaction with the model so the model can better understand their intent."

### When to Use
- Open conversation / unstructured search: probe deeper into user interests
- Deep research / compute-heavy tasks: precede generation to ensure thorough understanding
- Action-oriented flows: use as nudges and inline actions

### Key Principles
1. **Anchor follow ups in what just happened.** Base suggestions on the system's last response. Avoid generic next steps. (Perplexity references specific facts from answers to guide exploration.)
2. **Show why you're suggesting something.** Make the connection to the previous exchange clear. Use phrasing cues like "You could also ask…" or "Related topics include…"
3. **Keep the list short and scannable.** Offer a small set of high-value follow ups.
4. **Balance depth and breadth.** Mix 1-2 "zoom in" suggestions with 1 "zoom out" option.
5. **Preserve the conversational rhythm.** Visually separate follow ups from the model's main output.
6. **Let users select.** Allow users to regenerate the list of options.

### Lifecycle Importance
Follow ups are **most critical early in the user journey**, when the AI has the least information. As the AI builds memory, follow ups become less important and more personalized.

### Variations
| Type | Description | Example |
|---|---|---|
| Conversation extenders | Suggest additional questions after completing previous action | — |
| Clarifying questions | Ask about missing info or ambiguous phrasing | "Do you want results for Europe only?" |
| Depth probes | Offer to drill into a persona, scenario, or detail | "Should I expand on budget trade-offs?" |
| Comparisons | Suggest pros/cons, alternatives, or benchmarks | "Would you like to see side-by-side comparisons?" |
| Action nudges | Turn a generative result into an actionable step | "Send an email draft?" |
| Share/Export options | Extend work into other formats | "Would you like me to generate a slide?" |

## Follow-Up Chips (AI UX Playground)

Source: aiuxplayground.com/pattern/follow-up-chips

Clickable suggestion buttons after AI responses. Reduces cognitive load by proactively suggesting next steps.

- 2-4 suggested queries as interactive chips
- Ideal for: AI search engines, educational tools, discovery tools
- Seen in: Bing Chat, Google Bard, Perplexity, ChatGPT

## ChatGPT Follow-Up Suggestions — User Sentiment

Source: community.openai.com discussion threads

**Strongly negative** user sentiment:
- "Disruptive," "clutter the interface," "interrupt flow"
- "Even when it promises not to do it it still does"
- Users report inability to fully suppress even with settings toggle

**Lessons**:
- Must be opt-in, suppressible, and genuinely useful
- Forced suggestions breed resentment
- Advanced users especially dislike them

## Claude Artifacts

Source: code.claude.com/docs/en/artifacts

**Not a post-response tutorial** — Artifacts are shareable interactive HTML pages published from Claude Code sessions.

### Relevant Patterns
- "Walk through this change" with annotated diffs
- "Compare alternatives" side-by-side layouts
- "Bring result back to session" with "Copy as prompt" button
- "Track work in progress" with checklists

### Key Insight
Claude applies a built-in design skill and looks for the user's design system first. Precedence: user design system > Claude's built-in choices > user prompt.

## Proactive Agent Research

Source: arXiv 2410.12361, ICLR 2025

"Shifting LLM Agents from Reactive Responses to Active Assistance"

- Proactive agents anticipate and initiate tasks without explicit instructions
- Based on user activity, environmental events, and state
- ProactiveBench: 6,790 training examples for proactiveness
- Fine-tuning with ProactiveBench significantly elicits proactiveness

### Key Concept
Agent gives predictions based on:
- User's activities (A_t)
- Environmental events (E_t)
- State (S_t)

## Cursor "Plan Before Code" Pattern

"End your agent prompts with 'Investigate the codebase and outline your implementation approach step-by-step. Don't code, just tell.'"

- Generates structured plan with checkpoints
- "Stop and recap where we are with respect to the plan when you are done"
- Shows value of structured next-step framing

## Design Synthesis for Hermes

On messaging platforms (Slack/Telegram/WhatsApp), there are no clickable chips. The block is text appended to the response.

### What Works
- Structured format with emoji headers (📚 ⚡ 💡)
- Horizontal rule separation
- 1-2 components, not all three
- Adaptive depth based on user familiarity
- Explicit trigger classification (tactical vs non-tactical)

### What Doesn't Work
- Forced suggestions on every response (ChatGPT backlash)
- Generic "you could also ask about X" suggestions
- Long suggestion blocks that double the response length
- Suggestions that repeat what was already discussed