import json
from pathlib import Path
from types import SimpleNamespace

from isa_parser import load_from_bytes, load_from_file
from specification_validation import validate_specification
from tools import execute_tool


FIXTURE = Path(__file__).parent / 'fixtures' / 'diagnostic-signal-mini' / 'i_investigation.json'


def test_upload_checks_original_metadata_without_claiming_file_checks(tmp_path):
    content = json.dumps({'studies': []}).encode()
    parser = SimpleNamespace(_source_bytes=content, _original_path=None)
    report = validate_specification(parser, tmp_path)
    assert 'layout' in report['not_selected']
    assert 'paths were not checked' in report['agent_scope']
    assert report['conformant'] is None


def test_folder_source_checks_layout_and_detects_changed_json(tmp_path):
    path = tmp_path / 'example.isa-phm.json'
    content = json.dumps({'studies': []}).encode()
    path.write_bytes(content)
    parser = SimpleNamespace(_source_bytes=content, _original_path=path)
    report = validate_specification(parser, tmp_path)
    assert 'layout' in report['checks']
    path.write_text('{}', encoding='utf-8')
    changed = validate_specification(parser, tmp_path)
    assert 'layout' not in changed['checks']
    assert 'changed or is unavailable' in changed['agent_scope']


def test_chat_tool_reports_upload_scope():
    content = FIXTURE.read_bytes()
    parser = load_from_bytes(content, source_hint=FIXTURE.name)
    result = json.loads(execute_tool('validate_specification', {'dataset_name': 'mini'}, {'mini': parser}))
    assert 'layout' in result['not_selected']
    assert 'paths were not checked' in result['agent_scope']


def test_file_loader_preserves_original_path():
    parser = load_from_file(str(FIXTURE))
    assert parser._original_path == FIXTURE.resolve()
