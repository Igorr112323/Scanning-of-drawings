"""Offline tests for the corpus downloader (Part 2).

No network access — the HTTP layer is either never reached (dry-run) or
monkeypatched. These tests must pass on a machine with no connectivity.
"""

from __future__ import annotations

import json

import pytest

from core import dataset_fetch as df


# --------------------------------------------------------------------------- #
# registry                                                                     #
# --------------------------------------------------------------------------- #
def test_registry_loads_and_has_four_sources():
    registry = df.load_registry()
    for key in ("zenodo_open_mech", "hf_jcrzd", "hf_ecado", "mechatlas"):
        assert key in registry, key
        assert registry[key].get("license")
        assert registry[key].get("attribution")


def test_mechatlas_gate_recorded_not_bypassed():
    registry = df.load_registry()
    assert "401" in str(registry["mechatlas"].get("access_status", ""))


# --------------------------------------------------------------------------- #
# manifest schema                                                              #
# --------------------------------------------------------------------------- #
def _valid_record(**overrides):
    rec = {
        "id": "test-001",
        "source": "hf_jcrzd",
        "url": "https://example.com/x.jpg",
        "sha256": "a" * 64,
        "bytes": 123,
        "path": "data/corpus/x.jpg",
        "fetched_at": "2026-11-26T00:00:00Z",
        "license": "cc-by-4.0",
        "attribution": "test",
    }
    rec.update(overrides)
    return rec


def test_manifest_record_valid():
    assert df.validate_manifest_record(_valid_record()) == []


@pytest.mark.parametrize("field,bad", [
    ("sha256", "nothex"),
    ("sha256", "A" * 64),          # uppercase hex rejected — manifests must be canonical
    ("bytes", -1),
    ("bytes", "12"),
    ("id", ""),
    ("id", "a b"),
    ("path", "/absolute/path"),
])
def test_manifest_record_rejected(field, bad):
    assert df.validate_manifest_record(_valid_record(**{field: bad}))


def test_manifest_missing_fields():
    problems = df.validate_manifest_record({"id": "x"})
    assert any("missing field" in p for p in problems)


def test_manifest_writer_roundtrip_and_resume(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    writer = df._ManifestWriter(manifest)
    writer.append(_valid_record(id="rec-a"))
    writer.append(_valid_record(id="rec-b"))
    records = df.read_manifest(manifest)
    assert [r["id"] for r in records] == ["rec-a", "rec-b"]
    assert df._existing_urls(records) == {"https://example.com/x.jpg"}


def test_manifest_writer_refuses_invalid(tmp_path):
    writer = df._ManifestWriter(tmp_path / "manifest.jsonl")
    with pytest.raises(ValueError):
        writer.append(_valid_record(sha256="zz"))


def test_validate_manifest_cli(tmp_path, capsys):
    manifest = tmp_path / "m.jsonl"
    manifest.write_text(json.dumps(_valid_record()) + "\n" +
                        json.dumps(_valid_record(sha256="bad")) + "\n", encoding="utf-8")
    rc = df.run(["--validate-manifest", str(manifest)])
    out = capsys.readouterr().out
    assert rc == 3
    assert "1 invalid record" in out


# --------------------------------------------------------------------------- #
# dry-run (no network)                                                         #
# --------------------------------------------------------------------------- #
def test_zenodo_dry_run_makes_no_network_calls(tmp_path, monkeypatch, capsys):
    def boom(url, timeout):
        raise AssertionError(f"network touched in dry-run: {url}")

    monkeypatch.setattr(df, "_http_get", boom)
    rc = df.run(["--source", "zenodo_open_mech", "--dry-run", "--limit", "5",
                 "--out", str(tmp_path / "out"), "--manifest", str(tmp_path / "m.jsonl")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert not (tmp_path / "out").exists()  # dry-run creates nothing


def test_hf_dry_run_lists_plan(monkeypatch, tmp_path, capsys):
    fake_files = [{"type": "file", "path": f"page_{i:04d}.jpg", "size": 100} for i in range(3)] + \
                 [{"type": "file", "path": "README.md", "size": 10}]

    def fake_list(url, http_get_json=None):
        return fake_files

    monkeypatch.setattr(df, "hf_list_files", fake_list)
    rc = df.run(["--source", "hf_jcrzd", "--dry-run", "--limit", "2",
                 "--out", str(tmp_path / "out"), "--manifest", str(tmp_path / "m.jsonl")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "page_0000.jpg" in out and "page_0001.jpg" in out
    assert "README.md" not in out  # wrong suffix filtered out


def test_mechatlas_refused_without_network(tmp_path, capsys):
    rc = df.run(["--source", "mechatlas", "--limit", "1",
                 "--out", str(tmp_path / "out"), "--manifest", str(tmp_path / "m.jsonl")])
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def test_split_pdf_pages(tmp_path):
    import fitz

    src = tmp_path / "multi.pdf"
    doc = fitz.open()
    for i in range(7):
        page = doc.new_page(width=200, height=100)
        page.insert_text((20, 50), f"page {i + 1}")
    doc.save(src)
    doc.close()

    out_dir = tmp_path / "out"
    pages = df.split_pdf_pages(src, out_dir, limit=3)
    assert len(pages) == 3
    assert all(p.suffix == ".pdf" and p.exists() for p in pages)
    assert [p.name for p in pages] == ["page_001.pdf", "page_002.pdf", "page_003.pdf"]


def test_match_step_file_unique_numeric_stem(tmp_path):
    step_dir = tmp_path
    a = step_dir / "1002.step"
    b = step_dir / "1002x.stp"   # also shares token 1002
    c = step_dir / "77.step"
    for p in (a, b, c):
        p.write_bytes(b"x")
    page = tmp_path / "page_1002.pdf"
    page.write_bytes(b"x")
    # two candidates share the token → no match (ambiguous, stay honest)
    assert df.match_step_file(page, [a, b]) is None
    assert df.match_step_file(page, [a, c]) == a
    assert df.match_step_file(page, [c]) is None


def test_numeric_tokens():
    assert df.numeric_tokens("page_042") == ["042"]
    assert df.numeric_tokens("ABC") == []
