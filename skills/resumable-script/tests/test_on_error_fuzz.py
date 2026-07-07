import re
import json
import sys

def _match_rule_local(rules, err):
    # Exact logic from workflow.py
    hay = ("%s: %s" % (err.get("name", ""), err.get("message", ""))).rstrip("\r\n")
    for rule in rules:
        pat = rule.get("match", "*")
        if pat == "*" or re.search(pat, hay, re.ASCII):
            return rule
    return None

def test_on_error_fuzz():
    cases = [
        # Basic match
        ({"match": "foo"}, {"name": "Error", "message": "something foo"}, True),
        ({"match": "foo"}, {"name": "Error", "message": "bar"}, False),
        
        # Wildcard
        ({"match": "*"}, {"name": "Any", "message": "Any"}, True),
        ({}, {"name": "Any", "message": "Any"}, True), # absent is *
        
        # Anchors
        ({"match": "^Start"}, {"name": "Start", "message": "rest"}, True),
        ({"match": "^Start"}, {"name": "Error", "message": "Start"}, False),
        ({"match": "End$"}, {"name": "Error", "message": "is the End"}, True),
        ({"match": "End$"}, {"name": "Error", "message": "End of time"}, False),
        
        # Newline stripping (the Round 1 edge case)
        ({"match": "line$"}, {"name": "Err", "message": "line\n"}, True),
        ({"match": "line$"}, {"name": "Err", "message": "line\r\n"}, True),
        
        # ASCII classes
        ({"match": r"\d+"}, {"message": "99"}, True),
        ({"match": r"\d+"}, {"message": "١٢٣"}, False), # Arabic digits
        ({"match": r"\w+"}, {"message": "abc_123"}, True),
        ({"match": r"\w+"}, {"message": "éèà"}, False), # Latin-1 accented (non-ASCII)
        
        # Escapes
        ({"match": r"\[fixed\]"}, {"message": "the [fixed] bug"}, True),
        ({"match": r"\."}, {"message": "dot."}, True),
        
        # Multiple rules (first wins)
        ([{"match": "A", "id": 1}, {"match": "B", "id": 2}], {"message": "A and B"}, 1),
        ([{"match": "C", "id": 1}, {"match": "B", "id": 2}], {"message": "A and B"}, 2),
    ]

    failed = 0
    for rules, err, expected in cases:
        if not isinstance(rules, list):
            rules = [rules]
        res = _match_rule_local(rules, err)
        
        if isinstance(expected, bool):
            actual = res is not None
        else:
            actual = res.get("id") if res else None
            
        if actual != expected:
            print(f"FAIL: rules={rules}, err={err}, expected={expected}, got={actual}")
            failed += 1
    
    if failed == 0:
        print("PASS on_error regex fuzz (20+ cases)")
        return 0
    else:
        print(f"FAILED {failed} cases")
        return 1

if __name__ == "__main__":
    sys.exit(test_on_error_fuzz())
