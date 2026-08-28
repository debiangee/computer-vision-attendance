import math

import pytest

from lobby_attendance.vision.local_matcher import LocalMatcher, normalize_grayscale_crop


def _gradient(size=8):
    return [[float((row * 3 + column) % 17) for column in range(size)] for row in range(size)]


def _checker(size=8):
    return [[float((row + column) % 2) for column in range(size)] for row in range(size)]


def test_normalized_match_ignores_uniform_brightness_and_returns_server_hash():
    matcher = LocalMatcher(crop_size=8, threshold=0.01, margin=0.01)
    crop = _gradient()
    metadata = matcher.register("user-1", [[[value + 25 for value in row] for row in crop]])
    result = matcher.match(crop)
    assert result.identity_id == "user-1"
    assert result.status == "recognized"
    assert metadata.matcher_version == "local-gray-crop-v1"
    assert len(metadata.protected_template_hash) == 64
    assert all(character in "0123456789abcdef" for character in metadata.protected_template_hash)


def test_malformed_nonfinite_constant_and_three_dimensional_inputs_reject():
    matcher = LocalMatcher(crop_size=8)
    with pytest.raises(ValueError):
        normalize_grayscale_crop([[1.0, math.nan], [2.0, 3.0]], 8)
    with pytest.raises(ValueError):
        normalize_grayscale_crop([[1.0] * 8] * 8, 8)
    with pytest.raises(ValueError):
        normalize_grayscale_crop([[[1.0]]], 8)
    with pytest.raises(ValueError):
        matcher.register("user-1", [])


def test_unknown_ambiguous_and_removal_are_safe():
    matcher = LocalMatcher(crop_size=8, threshold=0.01, margin=0.01)
    gradient = _gradient()
    matcher.register("user-1", [gradient])
    assert matcher.match(_checker()).status == "unknown"

    matcher.register("user-2", [gradient])
    assert matcher.match(gradient).status == "ambiguous"
    assert matcher.remove("user-1") is True
    assert matcher.match(gradient).identity_id == "user-2"
    assert matcher.invalidate("user-2") is True
    assert matcher.match(gradient).status == "unknown"
    assert matcher.remove_all() == 0


def test_frame_shape_and_bounds_are_validated():
    matcher = LocalMatcher(crop_size=8)
    with pytest.raises(ValueError):
        matcher.resolve([[1.0] * 8] * 8, (4, 4, 8, 8))
    with pytest.raises(ValueError):
        matcher.resolve([[1.0] * 8] * 8, (0, 0, 0, 8))
