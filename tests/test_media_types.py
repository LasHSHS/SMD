from smd.media_types import extension_matches_magic, format_bytes


def test_extension_matches_magic_jpg():
    assert extension_matches_magic(".jpg", "jpg") is True
    assert extension_matches_magic(".jpeg", "jpg") is True
    assert extension_matches_magic(".mp4", "jpg") is False


def test_extension_matches_magic_mp4():
    assert extension_matches_magic(".mp4", "mp4") is True
    assert extension_matches_magic(".m4v", "mp4") is True


def test_format_bytes():
    assert format_bytes(512) == "512.0 B"
    assert format_bytes(2048) == "2.0 KB"
