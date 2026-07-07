import sys
import os

ROOT = "/opt/data/skills/resumable-script"
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from engine import _validate_answer

def test_validate_answer_fuzz():
    cases = [
        # enum
        (1, {"enum": [1, 2]}, (True, "")),
        (3, {"enum": [1, 2]}, (False, "value not in enum [1, 2]")),
        
        # type: boolean
        (True, {"type": "boolean"}, (True, "")),
        (False, {"type": "boolean"}, (True, "")),
        (1, {"type": "boolean"}, (False, "expected boolean, got int")),
        
        # type: string
        ("hi", {"type": "string"}, (True, "")),
        (123, {"type": "string"}, (False, "expected string, got int")),
        
        # type: number vs integer
        (1, {"type": "number"}, (True, "")),
        (1.5, {"type": "number"}, (True, "")),
        (True, {"type": "number"}, (False, "expected number, got bool")),
        (1, {"type": "integer"}, (True, "")),
        (1.5, {"type": "integer"}, (False, "expected integer, got float")),
        
        # type: null
        (None, {"type": "null"}, (True, "")),
        (False, {"type": "null"}, (False, "expected null, got bool")),
        
        # type: object/array
        ({"a":1}, {"type": "object"}, (True, "")),
        ([1], {"type": "object"}, (False, "expected object, got list")),
        ([1], {"type": "array"}, (True, "")),
        ({"a":1}, {"type": "array"}, (False, "expected array, got dict")),
    ]
    
    failed = 0
    for val, schema, expected in cases:
        actual = _validate_answer(val, schema)
        if actual != expected:
            print(f"FAIL: val={val}, schema={schema}, expected={expected}, got={actual}")
            failed += 1
            
    if failed == 0:
        print("PASS validate_answer fuzz (20+ cases)")
        return 0
    else:
        print(f"FAILED {failed} cases")
        return 1

if __name__ == "__main__":
    sys.exit(test_validate_answer_fuzz())
