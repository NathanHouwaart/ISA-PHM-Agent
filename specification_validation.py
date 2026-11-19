"""Run shared draft checks on the exact JSON loaded in the Agent."""

import tempfile
from pathlib import Path

METADATA_CHECKS = ("isa_schema", "phm_protocols", "phm_metadata", "phm_experiment_type", "phm_sensors")


def validate_specification(parser, data_root=None):
    """Return the shared report and disclose whether file layout was checked."""
    content = getattr(parser, "_source_bytes", None)
    if content is None:
        return {"status": "unavailable", "checks": {}, "limitations": ["Original JSON bytes are unavailable."]}
    try:
        from validator import validate_dataset
    except ImportError:
        return {"status": "unavailable", "checks": {}, "limitations": ["The shared validator is not installed in the Agent environment."]}

    original = getattr(parser, "_original_path", None)
    root = Path(data_root).expanduser().resolve() if data_root else None
    try:
        same_source = bool(original and Path(original).is_file() and Path(original).read_bytes() == content)
    except OSError:
        same_source = False

    if same_source and root and root.is_dir():
        report = validate_dataset(original, dataset_root=root, checks=("layout", *METADATA_CHECKS)).to_dict()
        report["agent_scope"] = "The original JSON and selected dataset root were checked."
    else:
        with tempfile.TemporaryDirectory(prefix="isa-phm-agent-validation-") as directory:
            path = Path(directory) / "uploaded.isa-phm.json"
            path.write_bytes(content)
            report = validate_dataset(path, checks=METADATA_CHECKS).to_dict()
        report["agent_scope"] = (
            "Dataset layout and referenced paths were not checked. Load the dataset from its folder "
            "and connect its dataset root to check them."
        )
        if original and not same_source:
            report["agent_scope"] += " The original JSON has changed or is unavailable; metadata was checked against the loaded copy."
    return report
