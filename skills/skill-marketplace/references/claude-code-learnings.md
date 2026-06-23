# Claude Code Skills Ecosystem — Key Learnings

## agentskills.io Open Standard

Adopted by Claude Code, OpenAI Codex, Cursor, GitHub Copilot, Gemini CLI, Hermes Agent.

### Required frontmatter
- `name`: max 64 chars, lowercase + hyphens, MUST match parent directory
- `description`: max 1024 chars, describe WHAT + WHEN

### Optional frontmatter
- `license`, `compatibility` (max 500 chars), `metadata`, `allowed-tools`

### Progressive disclosure (3 levels)
1. Metadata (~100 tokens): name + description at startup
2. Instructions (< 5000 tokens): full SKILL.md on activation
3. Resources (as needed): scripts/, references/, assets/

## Anthropic's skill-creator workflow
1. Capture intent → 2. Interview → 3. Write SKILL.md →
4. Test cases → 5. Run evals (with-skill + baseline) → 6. Grade → 7. Iterate

## What our marketplace does beyond the standard
1. Config-code separation enforced by CI
2. 5 automated validators
3. .well-known/skills/index.json discovery
4. Config schema with defaults + prompts
5. Secret/credential declarations
6. Platform + tool gating
7. Tiered governance (curated → community → external)