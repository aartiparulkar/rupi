import json
from pathlib import Path
import sys
sys.path.insert(0, 'c:/tax-agent/backend')
from services.document_parser import document_parser

pdf_path = Path('c:/tax-agent/Form_16_template.pdf')
content = pdf_path.read_bytes()

data, err, doc_type, _, identity = document_parser.extract_from_bytes(content, pdf_path.name)
print('document_type=', doc_type)
print('error=', err)
print('identity_keys=', sorted(identity.keys()))
print('tax_keys=', sorted(data.keys()))
print(json.dumps(data, indent=2, default=str))
