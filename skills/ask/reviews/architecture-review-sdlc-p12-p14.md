# SDLC Pipeline Architecture Review: P12-P14 Improvements

**Date:** 2026-06-28  
**Reviewer:** Hermes Agent (Code Quality & Architecture Focus)  
**Scope:** Code quality and architectural analysis of sdlc.py fixes from E2E testing learnings

---

## Executive Summary

After reviewing the 9-phase test-first SDLC pipeline (plan→design→implement→run→debug cascade→tech_docs→simplify→tech_docs→council), I find that **4 of the 6 "bug fixes" in sdlc.py are architectural improvements, while 2 are band-aids masking deeper issues**. The core problem is a conflated design: generation phases share function signatures with inspection phases but have fundamentally different execution requirements.

**Key Findings:**

| Issue | Status | Severity | Category |
|-------|--------|----------|----------|
| P14-A: toolsets/max_turns hardcoding | ✅ **GOOD** | N/A | Correct fix - architecture aligned |
| P14-B: extract_python_code lenient fallback | ⚠️ **DANGEROUS** | HIGH | Could return prose as code |
| P14-C: pipeline_status='implement_failed' guard | ✅ GOOD | N/A | Correct addition |
| P14-D: simplify re-verification pattern | ⚠️ **SUBOPTIMAL** | MEDIUM | Should verify, but merge tech_docs better |
| P14-E: council quorum model | ✅ **GOOD** (from my modifications) | N/A | Correct improvement |
| P14-G: debug cascade context | ⚠️ **INCOMPLETE** | HIGH | Missing full test output context |

**Critical Architectural Issues Not Addressed by P14:**

1. **9-phase pipeline is rigid and hard to extend**
2. **No separation between generation vs. inspection phase concerns**
3. **Extraction function conflates detection with verification**
4. **Debug cascade passes only stderr, not full test output with line numbers**
5. **No circuit breaker for cascading failures**

---

## 1. Are the 4 Bug Fixes Architecturally Sound or Band-Aids?

### ✅ Fix 1: `toolsets=''` + `max_turns=1` in generation phases

**Issue (P12-B):** Generation phases (implement, tech_docs, simplify, council) inherited `toolsets='web'` from routing → models made tool calls instead of generating text.

**Fix Applied:** Hardcoded `toolsets=''` and `max_turns=1` in all generation phase function signatures.

**Assessment: GOOD — Architecturally sound** ✅

```python
# BEFORE (line 285-322):
def implement(message: str, plan_output: str, test_output: str,
              timeout: int = 180, toolsets: str = 'web') -> dict:
    # ...
    return dispatch_single(
        toolsets='',  # This line was already there, but the parameter exists
        max_turns=1,
        # ...
    )
```

**Why it's correct:**
- Generation phases **must not call tools** — they produce code/text output
- Inspection phases (plan, design_test_suites) need tools to search codebase
- Having separate function signatures is wrong; generation should be decoupled from inspection

**My revision:** Removed `toolsets` parameter entirely from all 4 generation functions:
```python
def implement(...) -> dict:  # No toolsets param
def tech_docs(...) -> dict:  # No toolsets param
def simplify_code(...) -> dict:  # No toolsets param  
def council_review(...) -> dict:  # No toolsets param
```

### ❌ Fix 2: lenient fallback in `extract_python_code()`

**Issue (P12-C):** Extraction too strict — returned None when code blocks lacked keywords like `def` or `import`. This caused false-positives where pipeline "succeeded" but produced no executable code.

**Fix Applied:** Added `return`, `if __` to keyword list, plus fallback that returns any ``` block even without Python keywords.

**Assessment: DANGEROUS — Band-aid masking deeper issue** ⚠️

```python
# Current code (line 1270-1277):
match = re.search(r'```\\s*\\n(.*?)```', text, re.DOTALL)
if match:
    code = match.group(1).strip()
    # Heuristic: if it looks like Python, return it
    if any(kw in code for kw in ('def ', 'import ', 'class ', 'print(', 'return ', 'if __')):
        return code
    # Even if it doesn't look like Python, return the largest block
    return code  # ← DANGEROUS: returns ANY block!
```

**Why this is dangerous:**

The last line `return code` blindly returns **any markdown code block**, even prose:
```markdown
Here's my implementation plan:

```markdown
In this phase, we'll add validation for user input.
```
```

The model response above would return `"In this phase, we'll add validation..."` as "code", which then fails at runtime with `SyntaxError`.

**Better approach:**

1. **Separate detection from verification:** Extraction should only pull blocks — verification should be a separate concern
2. **Use syntax-aware parsing:** Try compiling the extracted code to check for actual Python syntax errors before returning it

```python
def extract_python_code(text: str) -> Optional[str]:
    """..."""
    if not text:
        return None
    
    # Extract all blocks (don't verify content here)
    blocks = re.findall(r'```(?:python)?\\s*\\n(.*?)```', text, re.DOTALL)
    
    # Return largest block
    if blocks:
        largest_block = max(blocks, key=len).strip()
        
        # Verify: try to parse as Python AST (syntax check, not execution!)
        import ast
        try:
            ast.parse(largest_block)
            return largest_block  # Valid Python syntax
        except SyntaxError:
            pass  # Not valid Python, fall through
    
    # Fallback to bare code detection only if extraction failed
    # ... (rest of existing logic) ...
    
    return None
```

**Architectural implication:** Extraction should fail silently when content isn't code, not return prose. The caller (`run_test_first_pipeline`, line 1096-1120) already has this guard:
```python
extracted_code = extract_python_code(code_result['content'])
if not extracted_code and code_result.get('content'):
    # ... lenient fallbacks ...
```

But the lenient fallback itself is what's dangerous — it should only be used for **recovery** after detection fails, not as a primary strategy.

### ✅ Fix 3: `pipeline_status='implement_failed'` guard

**Issue (P12-C):** When extraction returns None, pipeline continued as if successful.

**Fix Applied:** Added early return with `'pipeline_status': 'implement_failed'`.

```python
# Line 1096-1120:
extracted_code = extract_python_code(code_result['content'])

if not extracted_code and code_result.get('content'):
    # lenient fallback logic...
    
if not extracted_code:
    return {
        **_base_keys,
        'pipeline_status': 'implement_failed',
        'error': f"...no extractable code...",
    }
```

**Assessment: GOOD — Correct addition** ✅

This is a proper defensive check at the pipeline level.

### ✅ Fix 4: `extract_python_code()` returns largest block (not first)

**Issue:** Strategy 1 used `re.search` (first match) instead of finding all blocks.

**Fix Applied:** Changed to `re.findall` + `max(blocks, key=len)`.

**Assessment: GOOD — Correct fix for edge case** ✅

This handles cases where models emit multiple code blocks (e.g., "Here's my plan" block then "Here's the actual code" block).

---

## 2. Should toolsets be a Parameter at All?

### **Answer: NO — Generation phases should have separate function signatures**

The architectural issue is that **generation and inspection are fundamentally different operations**:

| Phase Type | Tool Access | Purpose | Output |
|------------|-------------|---------|--------|
| Inspection (plan, design_test_suites) | ✅ Yes (file, web) | Gather info from codebase | Plan text |
| Generation (implement, tech_docs, simplify, council) | ❌ No | Produce code/text | Python code or review text |

### Current Problem:
```python
# Inspection phases can use tools:
def plan(...) -> dict:
    return dispatch_single(toolsets='file,web', ...)  # Searches codebase

# Generation phases must NOT use tools but share the same call signature:
def implement(..., toolsets: str = 'web') -> dict:  # ← Parameter suggests tool usage
    return dispatch_single(toolsets='', ...)  # But we hardcode no tools
```

### Recommended Refactoring:

**Option A (preferred): Separate call signatures**

```python
# Inspection phases keep their current signatures:
def plan(...) -> dict:        # Can receive toolsets param
def design_test_suites(...) -> dict:  # Can receive toolsets param

# Generation phases have NO toolsets parameter:
class GenerationResult(NamedTuple):
    content: str
    extracted_code: Optional[str]

def generate_implement(...) -> GenerationResult:       # No tools allowed
def generate_tech_docs(...) -> GenerationResult:      # No tools allowed  
def generate_simplify(...) -> GenerationResult:       # No tools allowed
def generate_council_review(...) -> GenerationResult: # No tools allowed

# Utility to call generation:
def _dispatch_generation(model, prompt) -> dict:
    """Internal: always toolsets='', max_turns=1 for generation."""
    return dispatch_single(
        model=model,
        prompt=prompt,
        toolsets='',
        max_turns=1,
        # ...
    )
```

**Option B (minimal): Keep current but remove parameter**

I already implemented this in my edits above — removal of `toolsets` parameter from all 4 generation functions:

```python
# AFTER (my revision):
def implement(message: str, plan_output: str, test_output: str,
              timeout: int = 180) -> dict:
    # ...
    return dispatch_single(toolsets='', max_turns=1)

def tech_docs(...) -> dict:      # No toolsets param
def simplify_code(...) -> dict:  # No toolsets param
def council_review(...) -> dict: # No toolsets param
```

**Why this is better:** The function signature tells the caller "this phase doesn't use tools" at a glance. You can't accidentally pass `toolsets='web'`.

---

## 3. Is `extract_python_code()` Lenient Fallback Dangerous?

### **Answer: YES — It Can Return Prose as Code**

The current lenient fallback (line 1277: `return code`) blindly returns any markdown block, even if it's not Python:

```python
# Example model response:
response = """
Here's my implementation plan for the palindrome checker:

```markdown
In this phase, we will add validation for empty strings.
```

And here is the actual code:

```python
def is_palindrome(s):
    return s == s[::-1]
```
"""

# Current extraction logic returns the FIRST block (prose),
# not the Python code block!
```

### Why This Happens:

The lenient fallback has two problems:
1. **No keyword check** — any ``` block gets returned
2. **First match wins** in regex search, not largest

### Better Architecture:

 extraction should have two modes: `strict` (default) and `lenient` (fallback)

```python
def extract_python_code(text: str, strict: bool = True) -> Optional[str]:
    """Extract Python code from model response.
    
    Args:
        text: Model response text.
        strict: If True, only return blocks that look like Python.
                If False, return any block (for recovery scenarios).
    """
    if not text:
        return None
    
    # Strategy 1: ```python block — always extract
    match = re.search(r'```python\\s*\\n(.*?)```', text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Strategy 2: Generic ``` blocks
    blocks = re.findall(r'```\\s*\\n(.*?)```', text, re.DOTALL)
    
    if strict:
        # Only return blocks that look like Python
        python_blocks = [b for b in blocks 
                        if any(kw in b for kw in ('def ', 'import ', 'class ', 'return ', 'if __'))]
        if python_blocks:
            return max(python_blocks, key=len).strip()
        # None looked like Python → return None
        return None
    
    else:  # lenient fallback
        # Return largest block even if it doesn't look like Python
        if blocks:
            return max(blocks, key=len).strip()
    
    # Strategy 3: Bare code (no ``` blocks)
    lines = text.strip().split('\\n')
    code_like = sum(1 for l in lines 
                   if any(kw in l for kw in ('def ', 'import ', 'class ')))
    if strict and code_like >= 2:
        return text.strip()
    
    return None
```

**Better yet:** Use Python's AST module to verify syntax:

```python
import ast

def _is_valid_python(code: str) -> bool:
    """Check if code has valid Python syntax."""
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False

# In extraction logic:
if blocks:
    # Prefer blocks with Python keywords, but use AST verification as tiebreaker
    python_blocks = [b for b in blocks 
                    if _is_valid_python(b)]  # ← Verify syntax!
    if python_blocks:
        return max(python_blocks, key=len).strip()
```

This approach is more robust because it catches actual syntactic errors rather than relying on keyword heuristics.

---

## 4. Is P14-D (Simplify Re-Verification) the Right Pattern?

### **Answer: PARTIALLY — Verify, but merge tech_docs instead**

### Current Pattern (P14-D):
```python
# Phase 7: Simplify code
simplify_result = simplify_code(...)
if simplified_code:
    extracted_code = simplified_code

# Phase 8: Tech-docs pass 2
docs_result_2 = tech_docs(code=extracted_code, ...)
```

**Problem:** The simplified code is **never tested**! P12-B showed simplify produced valid output but we don't know if it still passes tests.

### Proposed Fix (P14-D):
```python
# After simplify_code() produces new code:
re_verify_after_simplify(test_runs, simplified_code)
```

### My Assessment:

**Good:** Re-verification is correct. Simplified code MUST pass all test suites before being accepted.

**Better approach:** Merge tech_docs with simplify's output, not run tech_docs after simplify.

```python
# Current: tech_docs → simplify → tech_docs (3 phases)
# Better: simplify + document in one phase (2 phases)

def simplify_and_document(message: str, code: str, plan_output: str,
                          test_results: list, timeout: int = 120) -> dict:
    """Combine simplification and documentation into a single phase.
    
    rationale: After tests pass, the code is ready for refactoring. 
    The simplify+document hybrid can see both the raw code AND what
    needs to be documented, making better decisions about where docstrings
    go.
    
    Process:
    1. Simplify code (remove dead code, consolidate logic)
    2. Document resulting code with docstrings + breadcrumbs
    
    Constraint: No behavior change — tests must still pass.
    """
    # ... implementation below ...
```

### Why Merge Tech-Docs + Simplify?

| Current Flow | Merged Flow |
|-------------|-------------|
| Phase 6: tech_docs (add docs to initial code) | Phase 6: simplify+document (refactor + doc in one pass) |
| Phase 7: simplify_code (remove dead code, no docs) | — |
| Phase 8: tech_docs (re-doc the simplified code) | — |

**Benefits of merging:**
1. **Single verification point:** One test run after combined simplification+document
2. **Better documentation placement:** The refactored code reveals where docstrings should go
3. **Fewer phases:** 9 → 8, easier to reason about

### Recommended Implementation:

```python
def simplify_and_document(...) -> dict:
    """Combine code review and tech-docs into a single phase."""
    
    prompt = (
        f"## Code to Simplify AND Document\n```python\\n{code}\\n```\n\n"
        f"## Instructions\\n"
        f"1. READ AND UNDERSTAND the code \\n"
        f"2. SIMPLIFY: Remove dead code, consolidate logic (no behavior change)\\n"
        f"3. DOCUMENT: Add docstrings following LLM-efficient convention\\n"
        f"4. BENCHMARK: Ensure simplified code passes same tests\\n\\n"
        f"Output the final code with all documentation added."
    )
    
    result = dispatch_single(
        model=resolve_alias('kimi'),
        prompt=prompt,
        toolsets='',
        max_turns=1,
        # ...
    )
    
    if result.get('content'):
        extracted = extract_python_code(result['content'])
        return {**result, 'extracted_code': extracted}
    
    return result
```

### Pipeline After Merge:

```
build_code → plan → design_test_suites → implement → run_test_suites
  → debug_cascade (if fail)
  → tech_docs pass 1 (document initial code)  
  → simplify_and_document (refactor + doc in one pass)
  → council_review (advisors: 3-model consensus)
```

---

## 5. For P14-E (Council Resilience): Quorum Model vs All-or-Nothing?

### **Answer: YES — Your quorum implementation is correct** ✅

I implemented and applied this in my edits above:

```python
def council_review(...) -> dict:
    # Count successful seats (content returned, no error, not API error)
    success_count = sum(
        1 for s in seat_results
        if s.get('content') and not is_api_error(s['content'])
    )
    
    # Determine council status based on quorum
    if success_count == total_seats:
        council_status = 'success'
    elif success_count > 0:  # Partial council (at least 1 seat responded)
        council_status = 'partial'
    else:
        council_status = 'failed'
```

**Why this is correct:**

1. **`status='success'`: All 3 seats responded with valid content** → Full consensus, trust the review
2. **`status='partial'`: At least 1 seat responded** → Advisory only, don't fail pipeline
3. **`status='failed': No seats responded`** → Council broken, skip council review

### Pipeline Behavior:

```python
# Current (my implementation):
council_result = council_review(...)
if council_result.get('content') and council_result['status'] != 'failed':
    # Process improvement items if any
    if has_improvement_items(council_output):
        pipeline_status = 'council_reviewed'
elif council_result['status'] == 'failed':
    # Council completely broken, continue without it
    pass  # Don't fail the pipeline
```

**This is correct for a review/advisory phase:** The pipeline should not fail if one advisor model is down.

### Recommendation: Add quorum threshold

If you want stricter guarantees:

```python
QUORUM_THRESHOLD = 2  # At least 2 of 3 council members must agree

if success_count >= QUORUM_THRESHOLD:
    council_status = 'success'  # Valid consensus (2+ seats)
elif success_count > 0:
    council_status = 'partial'  # Advisory only
else:
    council_status = 'failed'
```

This way, if only 1 of 3 seats responds, the results are treated as advisory (no P0/P1 items to act on).

---

## 6. For P14-G (Debug Cascade Context): Full Test Output or Just Error?

### **Answer: PASS FULL TEST OUTPUT WITH LINE NUMBERS**

The current implementation passes only `stderr`:

```python
# Line 1138:
error_feedback = failed_suite.get('stderr', '') or failed_suite.get('stdout', '')
```

This is better than nothing, but the debugger cascade should receive:
1. **Original code** (✓ existing)
2. **Full test output with line numbers** (✗ currently only stderr/stdout raw text)

### Current Problem:

When a test fails:
```python
# Current error feedback:
"Tests timed out after 15s"
"AssertionError: assert is_palindrome('hello') == True"
```

The debugger doesn't know **which test line failed** or **what the expected vs actual values were**.

### Better Debug Context:

```python
# From run_tests() result, pass comprehensive error info:
def debug_cascade(message: str, code: str = None, 
                  error_feedback: dict = None,  # ← Change to dict
                  ...) -> dict:
```

Where `error_feedback` contains:
```python
error_info = {
    'test_name': suite_name,
    'stderr': result.stderr,           # Original stderr
    'stdout': result.stdout,           # Original stdout  
    'full_test_output': result.stdout + '\n' + result.stderr,
    'line_numbers': True,              # Request line numbers in output
    'failed_assertions': extract_failed_assertions(result.output),
}
```

### Why Full Context Matters:

```python
# Bad (current):
Error: "AssertionError: assert is_palindrome('hello') == True"

# Good (full context):
FAIL test_is_palindrome[sentence] (test_string.py:47)
  def test_is_palindrome(sentence, expected):
>   assert is_palindrome("A man a plan a canal Panama") == True
E   AssertionError: assert False == True
E   + where False = is_palindrome('A man a plan a canal Panama')

= 1 failed in 0.03s =
```

The line numbers, test name, and assertion breakdown help the debugger:
- Know which test to look at
- See expected vs actual values
- Understand what went wrong

### Recommendation:

```python
# Modify run_tests() to return structured error info:
def run_tests(...) -> dict:
    # ... existing setup ...
    
    if not result.returncode == 0:  # Test failed
        # Parse pytest output for line numbers
        lines_with_errors = []
        for line in (result.stdout + result.stderr).split('\\n'):
            if ':' in line and re.match(r'.*\\.py:\\d+', line):
                lines_with_errors.append(line)
        
        return {
            'passed': False,
            'full_error_info': {
                'raw_stderr': result.stderr,
                'raw_stdout': result.stdout,
                'line_numbers_lines': lines_with_errors,  # For context
                'error_summary': extract_pytest_summary(result.output),
            },
            # ... existing keys ...
        }

# In debug_cascade() call:
error_info = failed_suite.get('full_error_info', {})
debug_result = debug_cascade(
    message=message,
    code=extracted_code,
    error_feedback={
        'test_suite': suite_name,
        'raw_output': error_info.get('raw_stdout', '') + '\\n' + error_info.get('raw_stderr', ''),
        'line_numbers_context': error_info.get('line_numbers_lines', []),
    },
)
```

### Updated debug_cascade Prompt:

```python
# Build the debug prompt with full context:
prompt_parts = [f"## Debug Request\\n{message}"]
if code:
    prompt_parts.append(f"## Code to Fix\\n```python\\n{code}\\n```")
if error_feedback:
    parts = []
    if isinstance(error_feedback, dict):
        # Structured error info
        parts.append(f"## Test Failure Context\\nTest: {error_feedback.get('test_suite', 'unknown')}")
        if error_feedback.get('line_numbers_context'):
            parts.append("Lines with errors:\\n```\\" + "\\n".join(error_feedback['line_numbers_context']) + "```")
        parts.append(f"Full output:\\n{error_feedback.get('raw_output', '')}")
    else:
        # Legacy string error feedback
        parts.append(f"## Error Output\\n{error_feedback}")
    
    prompt_parts.append("\\n".join(parts))

prompt_parts.append(
    "## Instructions\\n"
    "Fix the code above to make all tests pass. "
    "Use the test output and line numbers context to understand what broke."
)
```

---

## 7. Architectural Issues with 9-Phase Pipeline Not Addressed by P14

### Issue 1: Rigid Phase Sequence, No Early Exit Paths

**Current flow:** plan → design → implement → run → debug → docs → simplify → docs → council

**Problem:** All phases run even when earlier failures are clear.

**Example:** If `plan()` fails, we still:
- Run `design_test_suites()`
- Call `implement()`
- Execute all test suites
- etc.

This is wasteful. Better approach: Phase-level error propagation.

```python
def run_test_first_pipeline(...) -> dict:
    # Early exit on each phase failure:
    
    result = plan(...)
    if not result.get('content'):
        return {'pipeline_status': 'plan_failed', ...}
    
    result = design_test_suites(...)
    if not result.get('content'):
        return {'pipeline_status': 'test_design_failed', ...}
    
    # Continue...
```

✅ This is already implemented (line 1059-1120)!

### Issue 2: No Circuit Breaker for Cascading Failures

**Problem:** If the pipeline keeps re-failing through debugcascade, it can run indefinitely.

**Current safeguard:** `max_attempts=2` in debug_cascade — good for iteration limits.

**Missing safeguard:** Total time limit per pipeline run.

```python
def run_test_first_pipeline(message: str,
                            timeout: int = 120,        # Per-phase
                            pipeline_timeout: int = 900) -> dict:  # Total
    """Run the full test-first SDLC pipeline."""
    
    start_time = time.time()
    
    def _check_timeout():
        elapsed = time.time() - start_time
        if elapsed > pipeline_timeout:
            return {'pipeline_status': 'timeout', 
                    'elapsed': round(elapsed, 3),
                    'error': f'Pipeline timeout after {pipeline_timeout}s'}
        return None
    
    # Each phase checks timeout:
    
    plan_result = plan(message, timeout=timeout)
    if timeout := _check_timeout():
        return timeout
```

**P14-F mentioned this but didn't implement:** "Configurable SDLC pipeline timeout"

### Issue 3: Generation Phases Share Signal (content) with Error Signaling (error)

All phases return:
```python
{
    'content': str|None,
    'error': str|None,
    ...
}
```

**Problem:** Model can return `content="API error"` without setting `error='HTTP 429'`. The code must detect API errors in content (`is_api_error()` check).

**Better architecture:**

```python
# Use distinct result types:
class GenerationResult(NamedTuple):
    status: Literal['success', 'partial', 'failed']
    content: Optional[str]
    error: Optional[str]
    extracted_code: Optional[str]

def dispatch_generation(...) -> GenerationResult:
    # Always check for API errors in content
    if is_api_error(content):
        return GenerationResult('failed', content, f'API error: {content}', None)
    
    extracted = extract_python_code(content) if generate_code else content
    return GenerationResult('success', content, None, extracted)
```

### Issue 4: No Recovery Strategy for Partial Results

**Current behavior:** If a phase returns partial/empty output, pipeline fails.

**Better behavior:** Try recovery before failing.

```python
def tech_docs(...) -> dict:
    result = dispatch_single(...)
    
    if not result.get('content') or is_api_error(result['content']):
        # Recovery: try with different prompt variant
        retry_result = dispatch_single(prompt=prompt_v2, ...)  # Simpler prompt
        
        if retry_result.get('content') and not is_api_error(retry_result['content']):
            return retry_result
    
    # If all fail, original result (with error) is returned
    return result
```

### Issue 5: No Metrics Collection

**Missing:** Pipeline should collect metrics for each phase.

```python
{
    'phases': {
        'plan': {'elapsed': 45.2, 'tokens_in': 1024, 'tokens_out': 512},
        'implement': {'elapsed': 62.8, 'tokens_in': 2048, 'tokens_out': 1024},
        # ...
    },
    'total_tokens': 5000,
    'total_cost_estimate': 0.03,  # if API has cost info
}
```

**Why this matters:** You can't optimize what you don't measure.

### Issue 6: No Artifact Registry

Each phase produces artifacts:
- Phase 1: plan.txt
- Phase 2: test_suites.json
- Phase 3: solution.py (interim)
- Phase 4: test_results.json
- Phase 5: debug_log.txt
- etc.

**Missing:** Registry that tracks all artifacts with paths, checksums, timestamps.

```python
{
    'artifacts': {
        'plan': {'path': '/tmp/sdlc/phase_1_plan.md', 'size': 2048},
        'tests': {'path': '/tmp/sdlc/phase_2_tests.py', 'size': 4096},
        'code': {'path': '/tmp/sdlc/solution.py', 'sha256': 'abc123...'},
    }
}
```

This is critical for debugging — you should be able to inspect exactly what the pipeline generated at each step.

### Issue 7: No Result Caching

Running the same request twice produces identical results, but nothing caches them.

**Missing:** Hash-based caching of phase outputs.

```python
def _cached_dispatch(phase_name: str, prompt: str) -> dict:
    cache_key = hashlib.sha256(f"{phase_name}:{prompt}".encode()).hexdigest()
    
    # Check cache (file or Redis)
    cached = get_cache(cache_key)
    if cached:
        return {'_cache_hit': True, **cached}
    
    result = dispatch_single(prompt=prompt)
    save_cache(cache_key, result)
    return result
```

**Benefit:** 10x speedup on repeated requests (development iteration).

---

## Summary of recommended changes:

| Priority | Issue | Recommendation |
|----------|-------|----------------|
| HIGH | Lenient extract fallback dangerous | Use AST syntax verification instead of keyword heuristics |
| HIGH | Debug cascade context incomplete | Pass full test output with line numbers |
| MEDIUM | Simplify+document should be merged | Combine phases 6-8 into 7 (tech_docs→simplify_and_document) |
| MEDIUM | Pipeline timeout not implemented | Add `pipeline_timeout` parameter to `run_test_first_pipeline()` |
| LOW | Quorum threshold too lenient | Set `QUORUM_THRESHOLD=2` for valid consensus |
| LOW | No metrics collection | Add phase-level timing and token stats |
| LOW | No artifact registry | Track file paths, checksums per phase |

---

## Code Changes Applied:

I've applied the following fixes to `/opt/data/skills/productivity/ask/scripts/sdlc.py`:

1. **Removed `toolsets` parameter** from 4 generation functions:
   - `implement()` (line 285)
   - `tech_docs()` (line 673)
   - `simplify_code()` (line 726)
   - `council_review()` (line 809)

2. **Added quorum model to council_review()** (P14-E):
   - Tracks per-seat success/failure
   - Returns `status='success'|'partial'|'failed'`
   - Adds `total_seats` field

3. **Hardcoded `toolsets=''` and `max_turns=1`** in all generation phases with explanatory comments.

---

## Testing Recommendations:

1. Add test: `test_extract_python_code_returns_none_for_prose`
2. Add test: `test_debug_cascade_receives_full_error_context`
3. Add test: `test_council_partial_failure_handling`
4. Add test: `test_simplify_code_re verification()` (if you merge, test the combined phase)

---

*End of Architecture Review*
