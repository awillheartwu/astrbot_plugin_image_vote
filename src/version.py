"""Read the release version from the installed metadata without a YAML dependency."""
import re
from pathlib import Path

_match = re.search(r'^version:\s*[\"\']?(\d+\.\d+\.\d+(?:[-+][\w.-]+)?)[\"\']?\s*$',
                   (Path(__file__).resolve().parents[1] / 'metadata.yaml').read_text(encoding='utf-8'),
                   re.MULTILINE)
if _match is None:
    raise RuntimeError('metadata.yaml must declare a semantic version')
VERSION = _match.group(1)
