"""Corpus downloader for the real-drawing benchmark (Part 2).

Fetches the registered sources into ``data/corpus/<source>/``, verifies
checksums where the source publishes them, splits the multi-page Zenodo
PDF into one file per drawing page, and appends one JSON line per artifact
to ``data/corpus/manifest.jsonl``.

Never commits anything — ``data/corpus/`` is gitignored (see .gitignore).
No network access happens at import time; every network call goes through
:func:`_http_get` which is mocked in tests.

Usage:
    python -m core.dataset_fetch --source zenodo_open_mech --limit 100 --out data/corpus/zenodo
    python -m core.dataset_fetch --source hf_jcrzd --limit 1000 --out data/corpus/jcrzd
    python -m core.dataset_fetch --source hf_ecado --limit 600 --out data/corpus/ecado
    python -m core.dataset_fetch --source hf_ecado --inspect
    python -m core.dataset_fetch --source zenodo_open_mech --dry-run
    python -m core.dataset_fetch --validate-manifest data/corpus/manifest.jsonl

Exit codes: 0 = work done (per-file failures are logged and reported but do
not fail the run — nightly CI must survive one bad file); 2 = refused
(gated source or bad usage); 3 = infrastructure failure (cannot reach the
source at all, directory unusable, registry broken).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "data" / "sources.yaml"
DEFAULT_MANIFEST = ROOT / "data" / "corpus" / "manifest.jsonl"

USER_AGENT = "drawtostep-corpus-fetch/1.0 (+https://github.com/Igorr112323/Scanning-of-drawings)"


# --------------------------------------------------------------------------- #
# registry                                                                     #
# --------------------------------------------------------------------------- #
def load_registry(path: Path | None = None) -> dict:
    import yaml  # PyYAML — already a dev/test dependency

    path = Path(path) if path else DEFAULT_REGISTRY
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if not isinstance(doc, dict) or "sources" not in doc:
        raise ValueError(f"registry {path} has no 'sources' key")
    return doc["sources"]


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------- #
# manifest                                                                     #
# --------------------------------------------------------------------------- #
REQUIRED_MANIFEST_FIELDS = (
    "id", "source", "url", "sha256", "bytes", "path",
    "fetched_at", "license", "attribution",
)


def validate_manifest_record(rec: dict) -> list[str]:
    """Return a list of schema violations ([] = valid)."""
    problems = [f"missing field: {f}" for f in REQUIRED_MANIFEST_FIELDS if f not in rec]
    if problems:
        return problems
    if not re.fullmatch(r"[0-9a-f]{64}", str(rec["sha256"])):
        problems.append("sha256 must be 64 lowercase hex")
    if not isinstance(rec["bytes"], int) or rec["bytes"] < 0:
        problems.append("bytes must be a non-negative int")
    if not rec["id"] or not re.fullmatch(r"[A-Za-z0-9._-]+", str(rec["id"])):
        problems.append("id must be a non-empty [A-Za-z0-9._-] string")
    if not rec["path"] or str(rec["path"]).startswith("/"):
        problems.append("path must be a relative path inside data/corpus")
    return problems


def read_manifest(manifest_path: Path) -> list[dict]:
    if not manifest_path.exists():
        return []
    records = []
    for i, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"manifest {manifest_path} line {i + 1} is not valid JSON: {exc}") from exc
    return records


class _ManifestWriter:
    def __init__(self, manifest_path: Path):
        self._path = manifest_path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, rec: dict) -> None:
        problems = validate_manifest_record(rec)
        if problems:
            raise ValueError(f"refusing to write invalid manifest record: {problems}")
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- #
# http                                                                         #
# --------------------------------------------------------------------------- #
def _http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — URLs come from the committed registry
        return resp.read()


def _http_get_with_headers(url: str, timeout: float) -> tuple[bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — URLs come from the committed registry
        return resp.read(), dict(resp.headers)


def _http_get_json(url: str, timeout: float):
    return json.loads(_http_get(url, timeout).decode("utf-8"))


def _with_retries(fn, retries: int, base_delay: float, url: str):
    delay = base_delay
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn(url)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_exc = exc
            if attempt == retries:
                break
            time.sleep(delay)
            delay = min(delay * 2.0, 60.0)
    raise RuntimeError(f"fetch failed after {retries} attempts: {url}: {last_exc}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_urls(records: list[dict]) -> set[str]:
    return {rec.get("url") for rec in records if rec.get("url")}


# --------------------------------------------------------------------------- #
# zenodo                                                                       #
# --------------------------------------------------------------------------- #
def split_pdf_pages(pdf_path: Path, out_dir: Path, limit: int) -> list[Path]:
    """Split a multi-page PDF into one single-page PDF per drawing page."""
    import fitz  # pymupdf

    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    produced: list[Path] = []
    try:
        for index in range(min(doc.page_count, limit)):
            page_path = pages_dir / f"page_{index + 1:03d}.pdf"
            single = fitz.open()
            single.insert_pdf(doc, from_page=index, to_page=index)
            single.save(page_path)
            single.close()
            produced.append(page_path)
    finally:
        doc.close()
    return produced


def numeric_tokens(stem: str) -> list[str]:
    return re.findall(r"\d+", stem)


def match_step_file(page_path: Path, step_files: list[Path]) -> Path | None:
    """Best-effort page→STEP match by shared numeric stem token."""
    page_tokens = set(numeric_tokens(page_path.stem))
    if not page_tokens:
        return None
    hits = [s for s in step_files if set(numeric_tokens(s.stem)) & page_tokens]
    return hits[0] if len(hits) == 1 else None


def _fetch_zenodo(args, out_dir: Path, writer: _ManifestWriter, manifest_path: Path, registry: dict) -> int:
    src = registry["zenodo_open_mech"]
    timeout = args.timeout

    record = None
    if not args.dry_run:
        # dry-run must be fully offline: no metadata call at all
        try:
            record = _with_retries(lambda u: _http_get_json(u, timeout), args.retries, 1.0, src["api_base"])
        except RuntimeError as exc:
            print(f"WARN: Zenodo record metadata unavailable ({exc}); checksums will NOT be pre-verified", file=sys.stderr)

    api_checksums: dict[str, str] = {}
    if isinstance(record, dict):
        for f in record.get("files", []):
            checksum = str(f.get("checksum", ""))
            # zenodo publishes "md5:<hex>" or "sha256:<hex>"
            api_checksums[f.get("key", "")] = checksum
        print(f"Zenodo record: {record.get('title', '?')} — {len(api_checksums)} file(s) listed")

    plan: list[dict] = []
    for entry in src["files"]:
        expected = api_checksums.get(entry["name"], "")
        plan.append({**entry, "expected_checksum": expected})

    if args.dry_run:
        for item in plan:
            print(f"DRY-RUN fetch {item['name']} <- {item['url']}")
        print(f"DRY-RUN split up to {min(args.limit, 100)} pages into {out_dir / 'pages'}")
        print(f"DRY-RUN extract STEP archive into {out_dir / 'step'}")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    records = read_manifest(manifest_path)
    have_urls = _existing_urls(records)
    fetched_any = False
    for item in plan:
        if args.resume and item["url"] in have_urls:
            print(f"SKIP (manifest) {item['name']}")
            continue
        dest = out_dir / item["name"]
        print(f"FETCH {item['name']} <- {item['url']}")
        payload = _with_retries(lambda u: _http_get(u, timeout * 4), args.retries, 2.0, item["url"])
        dest.write_bytes(payload)
        sha = _sha256(dest)
        expected = item["expected_checksum"]
        if expected.startswith("sha256:") and expected.split(":", 1)[1] != sha:
            dest.unlink()
            print(f"ERROR: checksum mismatch for {item['name']} (zenodo sha256 ≠ downloaded) — file deleted", file=sys.stderr)
            continue
        rec = {
            "id": f"zenodo-{sha[:16]}",
            "source": "zenodo_open_mech",
            "url": item["url"],
            "sha256": sha,
            "bytes": len(payload),
            "path": dest.relative_to(ROOT).as_posix() if dest.is_relative_to(ROOT) else dest.name,
            "fetched_at": _utc_now(),
            "license": src["license"],
            "attribution": src["attribution"],
            "name": item["name"],
            "role": "archive",
        }
        writer.append(rec)
        fetched_any = True
        print(f"OK {item['name']} sha256={sha[:16]}… {len(payload) / 1e6:.1f} MB")

    pdf_path = _find_downloaded_pdf(out_dir, plan)
    step_zip = next((out_dir / item["name"] for item in plan if item["name"].lower().endswith(".zip")), None)
    step_files: list[Path] = []
    if step_zip and step_zip.exists():
        step_dir = out_dir / "step"
        step_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(step_zip) as zf:
            for member in zf.infolist():
                target = (step_dir / member.filename).resolve()
                if not str(target).startswith(str(step_dir.resolve())):
                    print(f"WARN: skipping suspicious zip member {member.filename!r}", file=sys.stderr)
                    continue
                zf.extract(member, step_dir)
        step_files = sorted(step_dir.rglob("*.step")) + sorted(step_dir.rglob("*.stp"))
        print(f"STEP archive extracted: {len(step_files)} file(s) in {step_dir}")
    if pdf_path:
        pages = split_pdf_pages(pdf_path, out_dir, min(args.limit, 100))
        for page_path in pages:
            sha = _sha256(page_path)
            step = match_step_file(page_path, step_files)
            rec = {
                "id": f"zenodo-page-{page_path.stem}",
                "source": "zenodo_open_mech",
                "url": f"zenodo-page:{page_path.name}",
                "sha256": sha,
                "bytes": page_path.stat().st_size,
                "path": page_path.relative_to(ROOT).as_posix() if page_path.is_relative_to(ROOT) else page_path.name,
                "fetched_at": _utc_now(),
                "license": src["license"],
                "attribution": src["attribution"],
                "page": int(numeric_tokens(page_path.stem)[0]),
                "role": "drawing_page",
                "gt_3d": step.name if step else None,
            }
            if not any(r.get("id") == rec["id"] for r in read_manifest(manifest_path)):
                writer.append(rec)
        print(f"Split {len(pages)} page(s) from {pdf_path.name}")
    return 0 if fetched_any or plan else 3


def _find_downloaded_pdf(out_dir: Path, plan: list[dict]) -> Path | None:
    for item in plan:
        if item["name"].lower().endswith(".pdf"):
            candidate = out_dir / item["name"]
            if candidate.exists():
                return candidate
    return None


# --------------------------------------------------------------------------- #
# hugging face                                                                 #
# --------------------------------------------------------------------------- #
_LINK_NEXT_RE = re.compile(r'<([^>]+)>\s*;\s*rel="next"')


def hf_list_files(api_tree_url: str, http_get_json=None) -> list[dict]:
    """List all files in an HF dataset repo.

    Pagination follows the RFC 5988 ``Link: rel="next"`` header the HF tree
    API emits (verified live: ``hasMore: true`` in the JSON body, page size
    ~50 rows/request regardless of ``limit``). The flat repo layout is used
    as-is; directories (if any) are walked one level deep.
    """
    files: list[dict] = []
    base = api_tree_url.rstrip("/")

    def _fetch(url: str) -> tuple[list, dict[str, str]]:
        if http_get_json is not None:  # test hook — JSON only, single page
            page = http_get_json(url, 60)
            if not isinstance(page, list):
                raise RuntimeError(f"unexpected HF tree response from {url}")
            return page, {}

        def _get(u: str):
            body, headers = _http_get_with_headers(u, 60)
            return json.loads(body.decode("utf-8")), headers

        page, headers = _with_retries(_get, 3, 1.0, url)
        if not isinstance(page, list):
            raise RuntimeError(f"unexpected HF tree response from {url}")
        return page, headers

    def _walk(url: str) -> None:
        seen_next: set[str] = set()
        current: str | None = url
        while current:
            page, headers = _fetch(current)
            for item in page:
                if item.get("type") == "file":
                    files.append(item)
                elif item.get("type") == "directory" and item.get("path"):
                    _walk(f"{base}/{item['path']}?expand=false")
            nxt = None
            m = _LINK_NEXT_RE.search(headers.get("Link") or headers.get("link") or "")
            if m:
                nxt = m.group(1)
            if nxt and nxt not in seen_next:
                seen_next.add(nxt)
                current = nxt
            else:
                current = None

    _walk(f"{base}?expand=false")
    return files


def _suffix_wanted(name: str, wanted: tuple[str, ...]) -> bool:
    return name.lower().endswith(tuple(wanted))


def _fetch_hf(args, out_dir: Path, writer: _ManifestWriter, manifest_path: Path, registry: dict, source_key: str, wanted: tuple[str, ...]) -> int:
    src = registry[source_key]
    if "401" in str(src.get("access_status", "")):
        print(f"REFUSED: {source_key} is gated ({src['access_status']}). Request access manually — see docs/DATA_SOURCES.md.", file=sys.stderr)
        return 2

    timeout = args.timeout
    if args.dry_run:
        try:
            files = hf_list_files(src["hf_api_tree"])
        except Exception as exc:
            print(f"DRY-RUN: cannot list remote files ({exc}); the plan would be: list '{src['hf_api_tree']}', download every *{'/'.join(wanted)} up to --limit {args.limit}")
            return 0
        wanted_files = [f for f in files if _suffix_wanted(f.get("path", ""), wanted)]
        for f in wanted_files[: args.limit]:
            print(f"DRY-RUN fetch {f.get('path')} <- {src['hf_resolve_base']}/{f.get('path')}")
        print(f"DRY-RUN total: {min(len(wanted_files), args.limit)} of {len(wanted_files)} matching file(s)")
        return 0

    try:
        files = hf_list_files(src["hf_api_tree"])
    except Exception as exc:
        print(f"ERROR: cannot list {source_key}: {exc}", file=sys.stderr)
        return 3

    wanted_files = [f for f in files if _suffix_wanted(f.get("path", ""), wanted)][: args.limit]
    if not wanted_files:
        print(f"ERROR: no matching files in {source_key}", file=sys.stderr)
        return 3

    records = read_manifest(manifest_path)
    have_urls = _existing_urls(records)

    def _one(f):
        rel = f["path"]
        url = f"{src['hf_resolve_base']}/{rel}"
        dest = out_dir / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if args.resume and dest.exists() and url in have_urls:
                return ("skip", url, dest, None)
            payload = _with_retries(lambda u: _http_get(u, timeout), args.retries, 1.0, url)
            dest.write_bytes(payload)
            return ("ok", url, dest, len(payload))
        except Exception as exc:  # one bad file must never abort the batch
            return ("fail", url, dest, str(exc))

    failures = 0
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for status, url, dest, nbytes in pool.map(_one, wanted_files):
            if status == "fail":
                failures += 1
                print(f"ERROR {url}: {nbytes}", file=sys.stderr)
                continue
            if status == "skip":
                print(f"SKIP {dest.name}")
                done += 1
                continue
            time.sleep(args.delay)  # politeness between completed downloads
            try:
                sha = _sha256(dest)
                rec = {
                    "id": f"{source_key}-{re.sub(r'[^A-Za-z0-9._-]', '_', dest.stem)}-{sha[:8]}",
                    "source": source_key,
                    "url": url,
                    "sha256": sha,
                    "bytes": nbytes,
                    "path": dest.relative_to(ROOT).as_posix() if dest.is_relative_to(ROOT) else dest.as_posix(),
                    "fetched_at": _utc_now(),
                    "license": src["license"],
                    "attribution": src["attribution"],
                    "name": dest.name,
                }
                if not any(r.get("id") == rec["id"] for r in read_manifest(manifest_path)):
                    writer.append(rec)
                print(f"OK {dest.name} sha256={sha[:16]}… {nbytes / 1e6:.1f} MB")
                done += 1
            except Exception as exc:
                failures += 1
                print(f"ERROR {url}: {exc}", file=sys.stderr)
    print(f"{source_key}: {done} ok/skipped, {failures} failed of {len(wanted_files)} planned")
    return 0 if failures < len(wanted_files) else 3


def _inspect_ecado(registry: dict) -> int:
    src = registry["hf_ecado"]
    print("ecado/rfq-engineering-drawings — schema inspection")
    print(f"tree url: {src['hf_api_tree']}")
    try:
        files = hf_list_files(src["hf_api_tree"])
    except Exception as exc:
        print(f"ERROR: cannot list dataset: {exc}", file=sys.stderr)
        return 3
    data_files = [f for f in files if f.get("path", "").startswith("data/") and f["path"].endswith(".parquet")]
    for f in data_files:
        print(f"  {f['path']}  ({f.get('size', '?')} bytes)")
    try:
        import pandas as pd  # optional — only for --inspect
    except ImportError:
        print("pandas not installed here; run on a machine with: pip install pandas pyarrow")
        return 0
    import io
    sample = next((f for f in data_files if "train" in f["path"]), None)
    if sample:
        raw = _http_get(f"{src['hf_resolve_base']}/{sample['path']}", 240)
        df = pd.read_parquet(io.BytesIO(raw))
        print(f"columns: {list(df.columns)}")
        print(f"rows: {len(df)}")
        print("first row (truncated):")
        print(str(df.iloc[0].to_dict())[:2000])
        print("If no dimension values appear in the answers, this source is unusable for OCR accuracy — document and skip (docs/DATA_SOURCES.md).")
    return 0


# --------------------------------------------------------------------------- #
# cli                                                                          #
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Download the real drawing corpus (see docs/DATA_SOURCES.md).")
    ap.add_argument("--source", choices=["zenodo_open_mech", "hf_jcrzd", "hf_ecado", "mechatlas"])
    ap.add_argument("--out", default=None, help="output dir (default: data/corpus/<source>)")
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.4, help="politeness delay between downloads, seconds")
    ap.add_argument("--timeout", type=float, default=120.0, help="per-request timeout, seconds")
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--dry-run", action="store_true", help="list what would be fetched; no writes")
    ap.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--inspect", action="store_true", help="hf_ecado only: print parquet schema and one row")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="shared manifest.jsonl path")
    ap.add_argument("--validate-manifest", default=None, metavar="PATH", help="validate a manifest.jsonl and exit")
    return ap


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.validate_manifest:
        path = Path(args.validate_manifest)
        bad = 0
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            problems = validate_manifest_record(json.loads(line))
            if problems:
                bad += 1
                print(f"line {i + 1}: {problems}")
        print(f"manifest: {bad} invalid record(s)")
        return 0 if bad == 0 else 3

    if not args.source:
        print("ERROR: --source is required", file=sys.stderr)
        return 2
    registry = load_registry(Path(args.registry))
    out_dir = Path(args.out) if args.out else ROOT / "data" / "corpus" / args.source
    if args.source == "mechatlas":
        print("REFUSED: XUXU666/MechAtlas is gated (HTTP 401). Request access manually — see docs/DATA_SOURCES.md.", file=sys.stderr)
        return 2
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    writer = _ManifestWriter(manifest_path)

    if args.source == "hf_ecado" and args.inspect:
        return _inspect_ecado(registry)
    if args.source == "zenodo_open_mech":
        return _fetch_zenodo(args, out_dir, writer, manifest_path, registry)
    if args.source == "hf_jcrzd":
        return _fetch_hf(args, out_dir, writer, manifest_path, registry, "hf_jcrzd", (".jpg", ".jpeg", ".png"))
    if args.source == "hf_ecado":
        return _fetch_hf(args, out_dir, writer, manifest_path, registry, "hf_ecado", (".parquet",))
    return 2


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
