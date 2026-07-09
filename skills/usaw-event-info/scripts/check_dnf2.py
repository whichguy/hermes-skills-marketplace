#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from usaw_results_parser import parse_full_results
import fitz

pdf_path = 'tests/fixtures/pdfs/2026-ncw-results.pdf'
doc = fitz.open(pdf_path)
result = parse_full_results(doc)
doc.close()

dnf_athletes = [a for a in result.get('athletes', []) if a.get('total') == 'DNF']
print(f'Total athletes: {len(result["athletes"])}')
print(f'DNF total entries: {len(dnf_athletes)}')
