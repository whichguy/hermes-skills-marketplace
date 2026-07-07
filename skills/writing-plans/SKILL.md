---
name: writing-plans
description: 'Write implementation plans: bite-sized tasks, paths, code.'
version: 1.1.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
platforms:
- linux
- macos
- windows
metadata:
  hermes:
    tags:
    - planning
    - design
    - implementation
    - workflow
    - documentation
    related_skills:
    - subagent-driven-development
    - test-driven-development
    - requesting-code-review
    config:
    - key: writing-plans.enabled
      description: Enable writing-plans skill behavior
      default: true
      prompt: Enable writing-plans skill?
    category: software-development
---
---

# Writing Implementation Plans

## Overview

Write comprehensive implementation plans assuming the implementer has zero context for the codebase and questionable taste. Document everything they need: which files to touch, complete code, testing commands, docs to check, how to verify. Give them bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume the implementer is a skilled developer but knows almost nothing about the toolset or problem domain. Assume they don't know good test design very well.

**Core principle:** A good plan makes implementation obvious. If someone has to guess, the plan is incomplete.

## When to Use

**Always use before:**
- Implementing multi-step features
- Breaking down complex requirements
- Delegating to subagents via subagent-driven-development

**Don't skip when:**
- Feature seems simple (assumptions cause bugs)
- You plan to implement it yourself (future you needs guidance)
- Working alone (documentation matters)

## Bite-Sized Task Granularity

**Each task = 2-5 minutes of focused work.**

Every step is one action:
- "Write the failing test" — step
- "Run it to make sure it fails" — step
- "Implement the minimal code to make the test pass" — step
- "Run the tests and make sure they pass" — step
- "Commit" — step

**Too big:**
```markdown
### Task 1: Build authentication system
[50 lines of code across 5 files]
```

**Right size:**
```markdown
### Task 1: Create User model with email field
[10 lines, 1 file]

### Task 2: Add password hash field to User
[8 lines, 1 file]

### Task 3: Create password hashing utility
[15 lines, 1 file]
```

## Plan Document Structure

### Header (Required)

Every plan MUST start with:

```markdown
# [Feature Name] Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---
```

### Task Structure

Each task follows this format:

````markdown
### Task N: [Descriptive Name]

**Objective:** What this task accomplishes (one sentence)

**Files:**
- Create: `exact/path/to/new_file.py`
- Modify: `exact/path/to/existing.py:45-67` (line numbers if known)
- Test: `tests/path/to/test_file.py`

**Step 1: Write failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

**Step 2: Run test to verify failure**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: FAIL — "function not defined"

**Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

**Step 4: Run test to verify pass**

Run: `pytest tests/path/test.py::test_specific_behavior -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## Writing Process

### Step 1: Understand Requirements

Read and understand:
- Feature requirements
- Design documents or user description
- Acceptance criteria
- Constraints

### Step 2: Explore the Codebase

Use Hermes tools to understand the project:

```python
# Understand project structure
search_files("*.py", target="files", path="src/")

# Look at similar features
search_files("similar_pattern", path="src/", file_glob="*.py")

# Check existing tests
search_files("*.py", target="files", path="tests/")

# Read key files
read_file("src/app.py")
```

### Step 3: Design Approach

Decide:
- Architecture pattern
- File organization
- Dependencies needed
- Testing strategy

### Step 4: Write Tasks

Create tasks in order:
1. Setup/infrastructure
2. Core functionality (TDD for each)
3. Edge cases
4. Integration
5. Cleanup/documentation

### Step 5: Add Complete Details

For each task, include:
- **Exact file paths** (not "the config file" but `src/config/settings.py`)
- **Complete code examples** (not "add validation" but the actual code)
- **Exact commands** with expected output
- **Verification steps** that prove the task works

### Step 6: Review the Plan

Check:
- [ ] Tasks are sequential and logical
- [ ] Each task is bite-sized (2-5 min)
- [ ] File paths are exact
- [ ] Code examples are complete (copy-pasteable)
- [ ] Commands are exact with expected output
- [ ] No missing context
- [ ] DRY, YAGNI, TDD principles applied

For privacy-sensitive personal-context, memory, email/calendar/contact discovery, relationship-graph, or engagement-policy plans, also load and apply `references/privacy-first-personal-context-planning.md`. Senior-engineer review must explicitly cover discovery-vs-truth separation, metadata-only defaults, canonical enums, validators, per-field provenance, fail-closed runtime behavior, retention/deletion, auditability, implementation gates, and sensitive-topic tests.

**After saving the plan, run a structural validation script** to catch missing sections, ordering violations, and reference gaps before handing off to implementation. The script should check: header presence, goal/architecture/tech stack sections, test-cases-before-implementation ordering, task count, TDD pattern references, commit instruction count, file path specificity, API feature coverage, ADR/DESIGN.md references, and meta-evaluation checkpoint presence. See `references/plan-validation-pattern.md` for a reusable Python validation template.

### Step 6.5: Define Test Cases BEFORE the Implementation Plan

**User preference (non-negotiable):** When a plan involves writing code, clarify the use cases as tests FIRST — before writing the implementation plan. The tests drive the outcomes.

Structure tests across three layers:

1. **Unit tests** — Individual functions/components in isolation. Each test: name, what it verifies, given/when/then, expected result.
2. **Mock tests** — External dependencies mocked (API calls, file I/O, databases, third-party services). Verify the code-under-test handles the contract correctly without real external systems.
3. **System tests** — End-to-end behavior through the real system. Verify the full path works, not just isolated units.

For each test, also define:
- **Edge cases** — boundary values, empty inputs, malformed data, concurrent access
- **Regression checks** — what existing behavior must NOT break

Place the test cases section BEFORE the implementation tasks section in the plan document. The implementation tasks should reference the tests by name ("Write code to pass `test_X`") rather than describing behavior in prose.

### Step 6.6: Test Suite Meta-Evaluation Loop

**User preference:** After each test passes OR fails during implementation, evaluate whether the test suite itself should improve.

This is a meta-loop on test quality, not just code quality. After every RED→GREEN cycle (or a RED that stays RED), ask:

- **Coverage gaps:** Did this cycle reveal a behavior we didn't test? Add a test for it.
- **Wrong-layer tests:** Is a unit test actually testing integration? Move it to the right layer.
- **Brittle tests:** Did a test fail for the wrong reason (typo, environment, flaky mock)? Fix the test, not just the code.
- **Missing edge cases:** Did the test pass but we're not confident? Add boundary tests.
- **Over-mocking:** Are we testing the mock instead of the behavior? Reduce mocking, use real components where feasible.

Document meta-evaluation decisions as a brief note after each cycle in the plan: "After `test_X` passed: added `test_X_edge_case` because [reason]." This creates an audit trail of test suite evolution.

### Step 6.7: Plan Verification by DeepSeek (Code-Level)

**User preference:** After writing a plan that references actual source code, delegate to DeepSeek V4 Pro to verify the plan against the real codebase. This catches concrete issues the plan-author misses: wrong import paths, abstract methods that would crash, missing API fields, always-true formulas, nonexistent helper methods, and scope gaps.

```python
delegate_task(
    goal="Verify this implementation plan against the actual source code",
    model="deepseek-v4-pro:cloud",
    context=f"""Read the plan at {plan_path}, then read the actual source files it references.
For every code snippet in the plan, verify:
1. Import paths match the actual project structure (no relative imports in scripts/)
2. Methods/functions called actually exist in the referenced files
3. API calls use correct field names (Google Sheets GridRange, etc.)
4. Abstract methods won't break existing concrete classes
5. Formulas/logic aren't always-true or always-false
6. All P0/P1 items from the design review are addressed
7. Scope gaps are documented (what's deferred and why)

Output: PASS or a numbered list of concrete issues with file:line references.""",
    toolsets=['terminal', 'file']
)
```

**After verification:** fix every issue found, then re-run the structural validation script from Step 6. Do NOT proceed to execution until both structural validation AND DeepSeek verification pass.

### Step 6.8: Advisor Review for Complex Plans (Pattern 9)

**User preference:** For complex, multi-file implementation plans — especially those touching the Hermes gateway, devloop, SDLC, or other fragile systems — run the plan through the `advisors` skill's Pattern 9 workflow before implementation:

1. **Write the plan** (Steps 1-6.7 above)
2. **Advisor review** — dispatch 2-3 seats to review the plan against actual source code. The review prompt MUST include: "Before identifying issues, verify each claim against the actual source files. If a file path is mentioned, read it."
3. **Implement** — dispatch a fixer model to apply patches, then verify independently
4. **Quality review** — dispatch a 2-3 seat panel to review the committed implementation for bugs the controller missed

See the `advisors` skill, **Pattern 9: Plan → Review → Implement → Quality Review** for the full workflow, dispatch code, and pitfalls.

**When to use Pattern 9:**
- Multi-file changes with architectural risk
- Changes to fragile systems (gateway, devloop, SDLC, pipeline)
- Plan references 5+ source files
- User explicitly asks for advisor review

**When to skip:**
- Single-file edits with no design decisions
- Trivial fixes (typos, linting, one-line changes)
- User says "just fix it"

### Step 7: Save the Plan

```bash
mkdir -p docs/plans
# Save plan to docs/plans/YYYY-MM-DD-feature-name.md
git add docs/plans/
git commit -m "docs: add implementation plan for [feature]"
```

## Principles

### Privacy-first personal context / relationship graph plans

When planning systems that infer personal context from Gmail, calendar, contacts, files, chats, or other private records, use the privacy-first graph pattern in `references/privacy-first-personal-context-graphs.md`.

Required planning checkpoints for this class of task:
- Separate raw discovery, candidate graph, reviewed canonical context, durable memory, and runtime resolver layers.
- Default to metadata-only discovery; snippets/body/document reads require explicit bounded user approval.
- Model third-party relationship edges when useful, but enforce: **an edge is not a permission**.
- Keep third-party edges local/routing-only by default: no disclosure and no memory writes unless separately approved.
- Add schema enums, per-field provenance, retention metadata, audit records, and a fail-closed validator before runtime use.
- Never promote candidate inferences to durable memory without an exact approved memory diff.

### DRY (Don't Repeat Yourself)

**Bad:** Copy-paste validation in 3 places
**Good:** Extract validation function, use everywhere

### YAGNI (You Aren't Gonna Need It)

**Bad:** Add "flexibility" for future requirements
**Good:** Implement only what's needed now

```python
# Bad — YAGNI violation
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
        self.preferences = {}  # Not needed yet!
        self.metadata = {}     # Not needed yet!

# Good — YAGNI
class User:
    def __init__(self, name, email):
        self.name = name
        self.email = email
```

### TDD (Test-Driven Development)

Every task that produces code should include the full TDD cycle:
1. Write failing test
2. Run to verify failure
3. Write minimal code
4. Run to verify pass

See `test-driven-development` skill for details.

### Frequent Commits

Commit after every task:
```bash
git add [files]
git commit -m "type: description"
```

## Common Mistakes

### Vague Tasks

**Bad:** "Add authentication"
**Good:** "Create User model with email and password_hash fields"

### Incomplete Code

**Bad:** "Step 1: Add validation function"
**Good:** "Step 1: Add validation function" followed by the complete function code

### Missing Verification

**Bad:** "Step 3: Test it works"
**Good:** "Step 3: Run `pytest tests/test_auth.py -v`, expected: 3 passed"

### Missing File Paths

**Bad:** "Create the model file"
**Good:** "Create: `src/models/user.py`"

### Privacy-Sensitive Personal Context Plans

When planning systems that infer facts about people, inboxes, contacts, calendars, personal memory, or relationship graphs, include explicit governance tasks before implementation:

- Separate raw discovery, candidate graph, reviewed canonical context, runtime policy, and durable memory.
- Use metadata-only discovery by default; snippets/body/document text require explicit bounded approval.
- Define canonical enums/schemas and a validator before runtime use.
- Require per-field provenance for policy-bearing facts.
- Add retention/deletion rules for raw and candidate artifacts.
- Fail closed on ambiguous identity, uncertain sensitive topics, or invalid policy files.
- Treat third-party relationship edges as local routing/disambiguation context only: an edge is not sharing permission.
- Keep disclosure permission, routing permission, and durable-memory permission as separate fields.

See `references/privacy-sensitive-relationship-graph-plans.md` for the detailed checklist and edge examples.

## Execution Handoff

After saving the plan, offer the execution approach:

**"Plan complete and saved. Ready to execute using subagent-driven-development — I'll dispatch a fresh subagent per task with two-stage review (spec compliance then code quality). Shall I proceed?"**

When executing, use the `subagent-driven-development` skill:
- Fresh `delegate_task` per task with full context
- Spec compliance review after each task
- Code quality review after spec passes
- Proceed only when both reviews approve

## Remember

```
Bite-sized tasks (2-5 min each)
Exact file paths
Complete code (copy-pasteable)
Exact commands with expected output
Verification steps
DRY, YAGNI, TDD
Frequent commits
```

**A good plan makes implementation obvious.**
