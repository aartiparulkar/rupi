import json
from pathlib import Path
import pypdf
import sys
sys.path.insert(0, 'c:/tax-agent/backend')
from services.document_parser import DocumentParser

pdf_path = Path('c:/tax-agent/Form_16_template.pdf')
reader = pypdf.PdfReader(str(pdf_path))
raw_text = '\n'.join((p.extract_text() or '') for p in reader.pages)

san = DocumentParser.sanitize_text(raw_text)
regex_data = DocumentParser.extract_with_regex(san)
form16_data = DocumentParser.extract_form16_table_fields(san)
identity = DocumentParser.extract_identity_fields(raw_text)
merged = {**regex_data, **form16_data}
filtered = {k: v for k, v in merged.items() if k in DocumentParser.TAX_FIELDS and v is not None}

print('identity_keys=', sorted(identity.keys()))
print('field_count=', len(filtered))
print('fields=', sorted(filtered.keys()))
print(json.dumps(filtered, indent=2, default=str))
