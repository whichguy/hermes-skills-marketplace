import sys
import os

sys.path.insert(0, "/opt/data/skills/resumable-script/scripts")
from workflow import _extract_json_object

test_case = 'Prose before {"a":"}"} and after'
result = _extract_json_object(test_case)
print(f"Result: {result}")
if result == {"a": "}"}:
    print("BUG NOT PRESENT")
else:
    print("BUG PRESENT")
