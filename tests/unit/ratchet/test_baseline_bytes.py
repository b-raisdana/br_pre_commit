import hashlib
from unittest.mock import patch

import pytest

import src.helper.paths as paths_module
from src.ratchet import common

pytestmark = pytest.mark.unit


def test_baseline_bytes_match_content_hash(tmp_path):
    baseline = {"loc": 215}
    with (
        patch.object(paths_module, "get_ratchet_baseline_dir", return_value=tmp_path),
        patch.object(common, "get_user_repo_path_from_env", return_value=tmp_path),
        patch.object(common.subprocess, "run"),
    ):
        common.write_baseline_file(baseline)

    content = (tmp_path / common.baseline_filename(baseline)).read_bytes()
    assert b"\r" not in content
    assert hashlib.sha256(content).hexdigest()[:8] == common.baseline_content_hash(baseline)
