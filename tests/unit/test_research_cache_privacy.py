import logging

from app.research.cache import ResearchCache


def test_corrupt_document_cache_does_not_log_url_or_parser_diagnostic(tmp_path, caplog):
    private_url = "https://papers.example/paper.pdf?access_token=private-token"
    cache = ResearchCache(cache_dir=tmp_path)
    disk_file = tmp_path / f"doc_{cache._hash_key(private_url)}.json"
    disk_file.write_text("{invalid private-cache-payload", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="aura"):
        assert cache.get_document(private_url) is None

    assert "Could not read a cached research document" in caplog.text
    assert private_url not in caplog.text
    assert "private-token" not in caplog.text
    assert "private-cache-payload" not in caplog.text
