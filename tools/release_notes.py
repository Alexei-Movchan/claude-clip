"""Print the newest section of CHANGELOG.md (used as GitHub release notes)."""
from pathlib import Path

text = (Path(__file__).resolve().parents[1] / 'CHANGELOG.md').read_text(encoding='utf-8')
sections = text.split('\n## ')
newest = sections[1] if len(sections) > 1 else text
lines = newest.split('\n')
print('**' + lines[0].strip() + '**\n')
print('\n'.join(lines[1:]).strip())
