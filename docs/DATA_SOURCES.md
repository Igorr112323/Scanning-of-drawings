# DATA_SOURCES.md — корпус реальных чертежей: реестр источников

**Дата верификации:** 2026-11-26 (curator pre-check; повторный тест из build-песочницы — см. ниже).

## ВАЖНО: статус доступа из среды сборки

В песочнице, где выполнялась эта работа, сетевой доступ ограничен набором
`github.com`, `codeload.github.com`, `api.github.com`, `pypi.org`,
`files.pythonhosted.org`, `registry.npmjs.org`. Все внешние хосты корпуса
(`zenodo.org`, `huggingface.co`) **недоступны**. Проверка curl 2026-11-26:

```
$ curl -s -o /dev/null -w "%{http_code}" -m 20 -I "https://zenodo.org/api/records/24167336/files/1-%20100%202D%20orthographic%20drawings.pdf/content"
000   (curl exit 35, SSL connect error — хост не открывается)
$ curl -s -m 20 "https://zenodo.org/api/records/24167336"            → 000
$ curl -s -m 20 "https://huggingface.co/api/datasets/jcrzd/engineering-drawings/tree/main" → 000
$ curl -s -m 20 "https://huggingface.co/datasets/ecado/rfq-engineering-drawings/resolve/main/data/train-00000-of-00002.parquet" → 000
```

Это НЕ проблема лицензии или гейтинга (для A/B/C данные открыты — см. ниже),
это ограничение сети среды сборки. Загрузчик `core/dataset_fetch.py` готов и
будет работать на любой машине с доступом к этим хостам — в том числе в
nightly CI на GitHub-hosted раннере (см. `.github/workflows/corpus-nightly.yml`).
Данные не выдуманы: скачивание нигде не «эмулировалось».

## Что требуется от владельца (manual actions)

1. **Скачать корпус** на машине с полным доступом в интернет:
   ```bash
   python -m core.dataset_fetch --source zenodo_open_mech --limit 100 --out data/corpus/zenodo
   python -m core.dataset_fetch --source hf_jcrzd --limit 1000 --out data/corpus/jcrzd
   python -m core.dataset_fetch --source hf_ecado --limit 600 --out data/corpus/ecado
   python -m core.dataset_fetch --source hf_ecado --inspect
   ```
   либо дождаться первого запуска nightly (`corpus-nightly` — manual dispatch).
2. **XUXU666/MechAtlas** — запросить доступ вручную на
   https://huggingface.co/datasets/XUXU666/MechAtlas с указанием аффилиации и
   исследовательской цели (см. источник D). После одобрения — добавить токен
   в секреты репозитория и убрать гейт в коде.

---

## A) Zenodo record 24167336 — Open Mechanical 3D Models Dataset: 100 Components in STEP/IGES

- **Name:** Open Mechanical 3D Models Dataset: 100 Components in STEP/IGES
- **Record:** https://zenodo.org/records/24167336
- **License:** CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
- **Attribution (required):** Open Mechanical 3D Models Dataset (zenodo.org/records/24167336), CC BY 4.0
- **Access status:** OPEN (curator verified: direct download HTTP 200; partial range requests 206). From agent build sandbox: **blocked by network** (see above).
- **Files:**
  1. `1- 100 2D orthographic drawings.pdf` — ~35 MB, 100 pages, A3/A4, vector with text layer on most pages; some pages raster
     ```
     curl -L -o "1- 100 2D orthographic drawings.pdf" \
       "https://zenodo.org/api/records/24167336/files/1-%20100%202D%20orthographic%20drawings.pdf/content"
     ```
  2. `3D STEP Files collection.zip` — ~28 MB, ~100 STEP files
     ```
     curl -L -o "3D STEP Files collection.zip" \
       "https://zenodo.org/api/records/24167336/files/3D%20STEP%20Files%20collection.zip/content"
     ```
- **File count:** 2 archives → 100 drawings (pages) + ~100 STEP files
- **Usable for:** Tier A external validation (volume/bbox/faces vs real STEP), end-to-end regression at 100 scale, screening with real vector PDFs.
- **NOT usable for:** OCR accuracy on scans (mostly clean vector), degraded-raster stress.
- **Date of verification:** 2026-11-26 (curator pre-check; blocked in build sandbox — pending human/CI download).
- **Notes:** page→STEP matching is best-effort by numeric stem; unmatched pages get `gt_3d=null` explicitly in manifest. Need actual run to know the real match rate — do not assume.

## B) Hugging Face — `jcrzd/engineering-drawings`

- **Name:** jcrzd/engineering-drawings
- **URL:** https://huggingface.co/datasets/jcrzd/engineering-drawings
- **License:** **unresolved — no license metadata on the dataset card (verified). Internal evaluation only.**
  Not redistributable, not citable as a dataset, no release artifacts may contain its files.
  Only aggregate, derived metrics may be reported, and they must be labelled as coming from an
  unlicensed internal evaluation corpus.
- **Access status:** OPEN (anon read, HF resolve + tree API). From agent build sandbox: **blocked by network**; from GitHub-hosted CI: reachable (HTTP 200, curator-verified 2026-11-26).
- **Files:** ~1000 JPG sheets, ~3509×2481 px, UNSW-style academic sheets with title block.
  List files:
  ```
  curl -s "https://huggingface.co/api/datasets/jcrzd/engineering-drawings/tree/main"
  curl -L -o sheet.jpg "https://huggingface.co/datasets/jcrzd/engineering-drawings/resolve/main/<filename>"
  ```
- **File count:** ~1000
- **Usable for:** degraded-raster stress corpus (contour/axis/text separation, robustness, pipeline coverage).
- **NOT usable for:** dimension-accuracy metrics — the majority of sheets are **drawing-reading exercises and carry NO dimension values**. Never report OCR/accuracy numbers on this set.
- **Date of verification:** 2026-11-26 (curator pre-check; blocked in build sandbox).
- **Notes:** metric value is a *coverage/limit* statement ("N of 1000 real sheets survive the pipeline"), not an accuracy claim. Any number reported from this corpus must carry the label "unlicensed internal evaluation corpus (jcrzd/engineering-drawings), aggregate metrics only".

## C) Hugging Face — `ecado/rfq-engineering-drawings`

- **Name:** ecado/rfq-engineering-drawings
- **URL:** https://huggingface.co/datasets/ecado/rfq-engineering-drawings
- **License:** **unresolved — no license metadata on the dataset card (team-verified 2026-11-26). Internal evaluation only.**
  Not redistributable, not citable, no release artifacts may contain its files.
  Only aggregate, derived metrics may be reported, labelled as coming from an unlicensed
  internal evaluation corpus.
- **Access status:** OPEN. From agent build sandbox: **blocked by network**; from GitHub-hosted CI: reachable (HTTP 200, curator-verified 2026-11-26).
- **Files:** 600 samples, parquet, `data/train-*`, `validation-*`, `test-*`; question/answer fields.
  ```
  curl -L -o rfq.parquet "https://huggingface.co/datasets/ecado/rfq-engineering-drawings/resolve/main/data/train-00000-of-00002.parquet"
  python -m core.dataset_fetch --source hf_ecado --inspect
  ```
- **File count:** ~600 (3 splits)
- **Usable for:** dimension-text OCR reading accuracy — **only if the answer fields actually contain dimension values**.
- **NOT usable for:** geometry/volume validation (no 3D); blindly assuming answers carry dimensions.
- **Date of verification:** 2026-11-26 (curator pre-check; blocked in build sandbox; schema NOT inspected yet).
- **Decision rule:** after `--inspect`, if dimension values are absent/absent-as-text → document here as "unusable for OCR accuracy" and skip. Do NOT synthesize metrics from it.

## D) Hugging Face — `XUXU666/MechAtlas`  (GATED — do not bypass)

- **Name:** XUXU666/MechAtlas
- **URL:** https://huggingface.co/datasets/XUXU666/MechAtlas
- **License:** CC BY 4.0
- **Attribution:** XUXU666/MechAtlas (huggingface.co/datasets/XUXU666/MechAtlas), CC BY 4.0
- **Access status:** **GATED — file downloads return HTTP 401** without approved access. Curator verified gating (2026-11-26). Citable under CC BY 4.0 once access is granted.
- **Files:** ~49 662 PDF+STEP pairs.
- **Usable for:** the primary long-term Tier A target at 10–100× Zenodo scale — only after access is granted.
- **NOT usable for:** anything right now.
- **Action for the human owner:** request access on the dataset page with affiliation and research purpose, then add HF token to repo secrets and re-run `python -m core.dataset_fetch --source mechatlas`. **Do not attempt to bypass the gate.**
- **Date of verification:** 2026-11-26 (401 confirmed by curator; blocked in build sandbox).

---

## Legal / licensing summary

| Source | License | Citable? | Redistribution of binaries | In git? | May ship in release artifacts? |
|---|---|---|---|---|---|
| Zenodo 24167336 | **CC BY 4.0** | **yes** (with attribution, see below) | allowed with attribution (we still do NOT commit binaries) | never | no raw files; derived STEP outputs of *our own* pipeline on their drawings are fine to distribute with attribution |
| MechAtlas | **CC BY 4.0 (gated, HTTP 401)** | yes — after manual approval | after approval with attribution | never | same as Zenodo |
| jcrzd | **unresolved — no license metadata** | **NO — internal evaluation only** | not granted | never | **NO** |
| ecado | **unresolved — no license metadata** | **NO — internal evaluation only** | not granted | never | **NO** |

Required attribution (Zenodo, CC BY 4.0):

> Open Mechanical 3D Models Dataset (zenodo.org/records/24167336), licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).

Required attribution (MechAtlas, once approved, CC BY 4.0):

> XUXU666/MechAtlas (huggingface.co/datasets/XUXU666/MechAtlas), licensed under CC BY 4.0.

Rules for the unlicensed corpora (jcrzd, ecado):

1. Their files are never committed, never attached to releases, never shown in screenshots or docs.
2. Metrics derived from them are reported only in aggregate (e.g., "73 of 1000 sheets screened to BODY_OF_REVOLUTION")
   and always labelled: **"unlicensed internal evaluation corpus (jcrzd/engineering-drawings)"**.
3. They are never cited as a redistributable dataset, in documentation or in any publication.
4. Attribution strings for them may identify the source but grant nothing: `jcrzd/engineering-drawings (huggingface.co/datasets/jcrzd/engineering-drawings), license unresolved — internal evaluation only`.

Only manifests (`manifest.jsonl` — ids+checksums, no binaries), aggregate reports
(`results.jsonl`, `screening.csv`, `docs/*.md`, `reports/*.png`), the committed golden
fixtures (`data/corpus/golden/`, 30 small synthetic PDFs) and — once real drawings may be
legally redistributed — a small sample of real files are committed to git.
Raw corpora are git-ignored (see `.gitignore`); no downloaded binary belongs in this repository.
