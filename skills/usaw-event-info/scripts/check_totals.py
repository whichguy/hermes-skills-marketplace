#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from usaw_results_parser import parse_full_results
import fitz

pdf_path = 'tests/fixtures/pdfs/2026-ncw-results.pdf'
doc = fitz.open(pdf_path)
result = parse_full_results(doc)
doc.close()

# Look for athletes without snatch_attempts
no_snatch = [a for a in result.get('athletes', []) if not a.get('snatch_attempts')]
print(f'Athletes without snatch_attempts: {len(no_snatch)}')
for a in no_snatch[:3]:
    print(f'  {a.get("name")} - team: {a.get("team")}, total: {a.get("total")}')

# Count by structure
has_snatch = [a for a in result.get('athletes', []) if a.get('snatch_attempts')]
print(f'\nAthletes with snatch_attempts: {len(has_snatch)}')
