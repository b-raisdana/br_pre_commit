import zlib

import pytest

from src.backup.common import content_hash as backup_content_hash
from src.br_pandera.content_hash import content_hash as pandera_content_hash
from src.helper.content_hash import crc32_hex

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("payload", [b"", b"hello", bytes(range(256))])
def test_domain_hashes_keep_their_legacy_slices(payload: bytes):
    full_hash = f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}"

    assert crc32_hex(payload) == full_hash
    assert backup_content_hash(payload) == full_hash[-7:]
    assert pandera_content_hash(payload) == full_hash[:7]
