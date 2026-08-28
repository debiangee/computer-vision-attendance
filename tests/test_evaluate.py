"""Tests for the target-device evaluation harness using synthetic providers."""

import json
from pathlib import Path

from lobby_attendance.evaluate import _host_info, _camera_diagnostics, _run_evaluation


class _FakeNamespace:
    camera_index = 0
    model_path = None
    model_directory = None
    model_sha256 = None
    iterations = 3
    interaction_timeout = 1.0
    sampling_interval = 0.2
    output = "unused.json"
    quiet = True


def test_host_info_collects_safe_metadata():
    info = _host_info()
    assert "platform" in info
    assert "machine" in info
    assert "python" in info
    assert "cpu_count" in info
    # Must never contain secrets, tokens, or biometric data
    text = json.dumps(info)
    assert "token" not in text.lower()
    assert "secret" not in text.lower()


def test_camera_diagnostics_handles_missing_opencv(monkeypatch):
    # Force ImportError for cv2
    import sys
    monkeypatch.setitem(sys.modules, "cv2", None)
    diag = _camera_diagnostics(0)
    assert diag["available"] is False
    assert "error" in diag


def test_evaluation_produces_structured_report_without_camera():
    args = _FakeNamespace()
    report = _run_evaluation(args)

    assert report["evaluation_type"] == "target-device-evaluation"
    assert report["started_at"] is not None
    assert report["completed_at"] is not None
    assert report["host"]["python"] is not None
    assert report["verdict"] in (
        "camera-unavailable",
        "camera-and-provider-operational",
        "partial-with-errors",
        "provider-failed",
        "incomplete",
    )
    assert isinstance(report["notes"], list)
    assert len(report["notes"]) >= 1

    # Report must not contain actual frames, embeddings, or identities as data fields
    # (the notes[] explanatory text is allowed to reference those concepts)
    data_only = {k: v for k, v in report.items() if k != "notes"}
    text = json.dumps(data_only)
    assert "embedding" not in text.lower()
    assert "identity" not in text.lower()


def test_evaluation_report_json_roundtrips(tmp_path):
    args = _FakeNamespace()
    report = _run_evaluation(args)
    path = tmp_path / "test-report.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["evaluation_type"] == "target-device-evaluation"
    assert loaded["verdict"] == report["verdict"]
