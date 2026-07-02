# E2E Test Suite Recommendations

## Executive Summary

After reviewing the ask skill E2E test suite (`tests/test_pipeline_e2e.py`), I recommend **adding more complex test cases** to better validate the SDLC pipeline's capabilities. The current 4 test cases (palindrome, fizzbuzz, fibonacci, factorial) are all simple single-function programs that don't exercise multi-phase SDLC complexities like iteration, debugging, or data structure handling.

---

## Current State Analysis

### Existing Test Cases
1. **palindrome_checker** - Single `is_palindrome(s)` function, prints True/False
2. **fizzbuzz** - Simple loop printing Fizz/Buzz/FizzBuzz 1-15
3. **fibonacci** - `fibonacci(n)` returning nth Fibonacci number (calls `fibonacci(10) = 55`)
4. **factorial** - `factorial(n)` returning n! (calls `factorial(5) = 120`)

### Test Validation Assessment

The validation logic in the tests is **moderately robust** but has issues:

1. **Current validation functions** (lines 177, 192, 207, 222):
   ```python
   validate = lambda r: r["returncode"] == 0 and "120" in r["stdout"]
   ```
   - ✅ Verifies code executes (`returncode == 0`)
   - ✅ Checks stdout for expected values
   - ❌ Does NOT test edge cases (e.g., `factorial(0) = 1`, negative inputs)
   - ❌ Does NOT verify output format precisely (e.g., fizzbuzz should be newline-separated)
   - ❌ No validation of function behavior beyond single outputs

### SDLC Pipeline Coverage Assessment

**Current E2E test coverage:**

| Test Class | Phases Covered | Notes |
|------------|---------------|-------|
| `TestPipelineEndToEnd` | Single dispatch only | Tests triage → routing → dispatch → execute |
| `TestPipelineSDLCE2E::test_sdlc_build_minimal` | plan→tests→implement→run_tests | No docs/simplify/council |
| `TestPipelineSDLCE2E::test_sdlc_build_with_docs` | + tech_docs, simplify | No council |
| `TestPipelineSDLCE2E::test_sdlc_build_full_pipeline` | All 9 phases | Most comprehensive |

**Missing coverage:**
- ❌ Multi-function code with interdependencies
- ❌ Classes and object-oriented patterns
- ❌ I/O handling (file read/write, stdin/stdout)
- ❌ Data structure manipulation (lists, dicts, sets)
- ❌ Error handling and exception cases
- ❌ Iteration cycles beyond simple debug
- ❌ Lean/simplify phases with behavior verification

---

## Recommendations

### 1. Add More Complex Test Cases

The current test suite mostly validates that the pipeline can generate single-function code. For a production SDLC pipeline, we need tests that exercise:

**Category A: Multi-function programs**
- Program with multiple cooperating functions
- Programs with helper functions called from main logic
- **Expected:** Tests should verify correct behavior across function boundaries

**Category B: Classes and OOP**
- Simple class definitions with methods
- Constructor initialization and method calls
- **Expected:** Tests should validate object state and behavior

**Category C: I/O handling**
- Reading from stdin or files
- Writing to files
- **Expected:** Tests should verify file contents or stdin processing

**Category D: Data structures**
- List manipulation (sorting, filtering, transformations)
- Dictionary operations (key-value pairs, lookups)
- Set operations (unions, intersections, differences)
- **Expected:** Tests should validate complex data transformations

**Category E: Edge cases and error handling**
- Input validation and error messages
- Boundary conditions (empty inputs, zeros, negatives)
- Exception handling in generated code
- **Expected:** Tests should verify graceful error handling

### 2. Improve Test Validation Logic

The current validation is text-based (`"120" in stdout`), which is fragile. Proposed improvements:

**Current:**
```python
validate = lambda r: r["returncode"] == 0 and "55" in r["stdout"]
```

**Improved approach:**
```python
def validate_fibonacci(result):
    # Parse output, check exact value for fibonacci(10)
    import re
    match = re.search(r'\b\d+\b', result["stdout"])
    return (
        result["returncode"] == 0 
        and match is not None 
        and int(match.group()) == 55
    )
```

**Or even better:**
```python
# Use pytest-style assertions with actual execution results
expected_output = "55"
actual_stdout = execute_code(code)["stdout"]
assert expected_output.strip() == actual_stdout.strip(), \
    f"Expected '{expected_output}', got '{actual_stdout}'"
```

### 3. Specific New E2E Test Cases

Here are 6 concrete new test cases with specific expected outputs:

#### Test Case 1: `reverse_words`
**Idea:** Write a Python script that defines `reverse_words(text)` returning text with words reversed (not characters). Example: `"hello world"` → `"dlrow olleh"`. Main block should print `reverse_words("the quick brown fox")` = `"xof nworb kciuq eht"`.

**Expected output:** `xof nworb kciuq eht`

#### Test Case 2: `word_frequency`
**Idea:** Write a Python script that defines `word_frequency(text)` returning a dict of word counts. Example: `"hello world hello"` → `{"hello": 2, "world": 1}`. Main block should print sorted items as "word: count" lines.

**Expected output (sorted):**
```
apple: 3
banana: 2
orange: 1
```

#### Test Case 3: `simple_calculator`
**Idea:** Write a Python script with a Calculator class that has `add(a, b)`, `subtract(a, b)`, `multiply(a, b)`, `divide(a, b)`. Main block computes `Calculator().divide(10, 2) + Calculator().multiply(3, 4)` = `17`.

**Expected output:** `17`

#### Test Case 4: `file_read_write`
**Idea:** Write a Python script that reads `/dev/stdin`, converts to uppercase, writes to `/tmp/test_output.txt`. Main block writes "hello world" to stdin (simulate with direct write to file), then prints contents of the output file.

**Expected output:** `HELLO WORLD`

#### Test Case 5: `list_operations`
**Idea:** Write a Python script that defines `unique_squares(nums)` returning sorted unique squares. Example: `[1, -2, 2, -1, 3]` → `[1, 4, 9]`. Main block prints `unique_squares([3, -2, 2, -3, 1])` = `[1, 4, 9]`.

**Expected output:** `[1, 4, 9]`

#### Test Case 6: `fibonacci_with_cache`
**Idea:** Write a Python script with `fibonacci(n)` using memoization (cache). Should handle `fibonacci(35)` correctly and quickly. Main block prints `fibonacci(10)`, `fibonacci(20)`, `fibonacci(35)`.

**Expected output:**
```
55
6765
9227465
```

### 4. Test Runner Alias Recommendation

**Recommendation:** Use `qwen3.6` for the test runner alias (fast/local).

**Rationale:**

From `model_utils.py` lines 163-178:
```python
"qwen":         "qwen3.6:35b-a3b",       # Line 163
"qwen-local":   "qwen3.6:35b-a3b",       # Line 165
# Local standard — Qwen 3.6 35B MoE (114 tok/s, 4.4s wall)
"fast":         "qwen3.6:35b-a3b",       # Line 177
"local":        "qwen3.6:35b-a3b",       # Line 178
```

The current SDLC pipeline uses different models for different phases:
| Phase | Model | Alias |
|-------|-------|-------|
| Planner | GLM | `glm-5.2:cloud` |
| Coder/Debugger | Qwen-coder | `qwen3-coder-next:q4_K_M` |
| Debugger-fallback | Kimi | `kimi-k2.7-code:cloud` |
| Tech-docs | Qwen-coder | `qwen3-coder-next:q4_K_M` |
| Simplify/Council | Kimi | `kimi-k2.7-code:cloud` |

**For E2E test validation (code execution), use `qwen-local`/`fast`:**

The test runner (`execute_code()` in `test_pipeline_e2e.py`) executes Python code, not runs models. However, if we're talking about the **pipeline alias used for dispatch during tests**, there are two considerations:

1. For **single-dispatch E2E tests** (TestPipelineEndToEnd): Should use a fast local model for quick iteration
   - Recommendation: `fast` → `qwen3.6:35b-a3b`
   
2. For **SDLC multi-phase E2E tests** (TestPipelineSDLCE2E): Phase-specific models are correct as-is
   - Planner needs reasoning → GLM is fine
   - Coder needs code skills → qwen-coder or kimi is good
   - The `qwen3.6` alias is better suited for simple dispatch tests

**Final recommendation:** For the E2E test runner (when calling through pipeline), use:
- `fast` or `local` alias (both resolve to `qwen3.6:35b-a3b`)
- This provides quick feedback during testing

See PR #14 for reference.

---

## Priority Implementation Order

### Phase 1 (Immediate - Low Risk)
1. **Improve validation logic** - Make tests more robust with precise output checking
2. **Add `reverse_words` test case** - Simple multi-function, good iteration test

### Phase 2 (Short-term - Medium Risk)
3. **Add `word_frequency` test case** - Data structures (dicts)
4. **Add list/sorting test case** - List manipulation

### Phase 3 (Medium-term - Higher Risk)
5. **Add class-based test case** - OOP patterns
6. **Add I/O test case** - File operations, stdin/stdout

---

## Summary of Key Issues and Recommendations

| Issue | Current State | Recommendation |
|-------|--------------|----------------|
| Test complexity | 4 simple single-function tests | Add 6+ complex multi-function/test cases |
| Validation logic | Text substring matching | Use precise parsing and assertions |
| SDLC coverage | Minimal iteration/debug testing | Add test cases that require multiple iterations |
| I/O handling | Not tested | Add file read/write test |
| Data structures | Only simple lists (print output) | Add dict, set operations |
| Edge cases | None tested | Test boundary conditions, empty inputs |
| Test runner alias | Current aliases are phase-specific | Use `fast`/`local` for quick validation tests |
