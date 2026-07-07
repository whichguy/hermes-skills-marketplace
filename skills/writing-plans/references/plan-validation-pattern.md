# Plan Validation Pattern

After writing an implementation plan, run a structural validation script to catch
missing sections, ordering violations, and reference gaps before handing off to
implementation. This is a reusable Python pattern — adapt the checks to the plan's
domain.

## Template

```python
import re

plan_path = "path/to/plan.md"
with open(plan_path, 'r') as f:
    content = f.read()

checks = []

# 1. Header presence
checks.append(("Plan has header", content.startswith("# ")))

# 2. Required sections
checks.append(("Has Goal", "**Goal:**" in content))
checks.append(("Has Architecture", "**Architecture:**" in content))
checks.append(("Has Tech Stack", "**Tech Stack:**" in content))

# 3. Test-first ordering (critical for TDD plans)
test_section_idx = content.find("## Test Cases")
impl_section_idx = content.find("## Implementation Tasks")
checks.append(("Test cases section exists", test_section_idx > 0))
checks.append(("Test cases BEFORE implementation", test_section_idx < impl_section_idx))

# 4. Test case counts by layer
unit_tests = len(re.findall(r'\| U\d+ \|', content))
mock_tests = len(re.findall(r'\| M\d+ \|', content))
system_tests = len(re.findall(r'\| S\d+ \|', content))
edge_tests = len(re.findall(r'\| E\d+ \|', content))
total_tests = unit_tests + mock_tests + system_tests + edge_tests
checks.append((f"Test cases (U={unit_tests}, M={mock_tests}, S={system_tests}, E={edge_tests})", total_tests >= 20))

# 5. Task count
task_headers = re.findall(r'### Task \d+:', content)
checks.append((f"Has N tasks (found {len(task_headers)})", len(task_headers) > 0))

# 6. TDD pattern
tdd_patterns = len(re.findall(r'Write failing test', content, re.I))
checks.append((f"TDD pattern present ({tdd_patterns} references)", tdd_patterns >= 3))

# 7. Commit instructions
commits = len(re.findall(r'git commit -m', content))
checks.append((f"Commit instructions ({commits})", commits >= 5))

# 8. File path specificity
file_refs = len(re.findall(r'[a-z_]+/[a-z_]+\.(py|js|ts|go|rs)', content))
checks.append((f"References source files ({file_refs} refs)", file_refs >= 3))

# 9. Domain-specific references (adapt to your domain)
checks.append(("References DESIGN.md", "DESIGN.md" in content))
checks.append(("References ADRs", "ADR-" in content))

# 10. Meta-evaluation checkpoint
checks.append(("Has meta-evaluation checkpoint", "Meta-Evaluation" in content))

# 11. Summary table
checks.append(("Has summary table", "| Phase |" in content))

# Print results
all_pass = True
for name, passed in checks:
    status = "✅" if passed else "❌"
    if not passed:
        all_pass = False
    print(f"  {status} {name}")

print(f"\n{'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'}")
print(f"Total: {sum(1 for _,p in checks if p)}/{len(checks)} passed")
```

## Customization

Add domain-specific checks for your plan type:

- **API plans:** Check for endpoint paths, request/response schemas, error codes
- **Database plans:** Check for migration files, schema changes, rollback steps
- **Infrastructure plans:** Check for Terraform/CloudFormation references, IAM roles
- **Security plans:** Check for threat model, attack surface analysis, mitigation steps

## When to Run

Run immediately after saving the plan. Fix any failures before handing off to
implementation. A plan that fails structural validation will waste subagent time
on ambiguous or incomplete tasks.
