# DrawToSTEP — корпус реальных чертежей / Real-corpus benchmark

> Документация по задаче «Real corpus at scale». Метрики генерируются автоматически
> в [docs/CORPUS_BENCHMARK.md](docs/CORPUS_BENCHMARK.md); английские разделы — там же.

## Зачем

Демо-пример в репозитории — синтетический PDF. Пока не прогнано на тысячах **реальных**
чертежей, любые цифры точности — это утверждения про генератор, а не про алгоритм.
Этот модуль скачивает открытые корпуса, прогоняет весь конвейер на каждом файле и
честно отчитывается о распределениях и ошибках.

## Источники (проверено 2026-11-26, доверять не слепо)

| ID | Источник | Лицензия | Доступ | Роль |
|---|---|---|---|---|
| A | Zenodo `24167336` "Open Mechanical 3D Models Dataset" — 2D PDF + STEP | CC BY 4.0 | открытый | Tier A ground truth (PDF ↔ STEP) |
| B | Hugging Face `jcrzd/engineering-drawings` (~1000 JPG) | см. `data/sources.yaml` | открытый | стресс-корпус (размеров почти нет) |
| C | Hugging Face `ecado/rfq-engineering-drawings` (600 parquet) | см. `data/sources.yaml` | открытый | OCR-точность, только если в ответах есть размеры |
| D | Hugging Face `XUXU666/MechAtlas` (~49 662 пары PDF+STEP) | CC BY 4.0 | **GATED (HTTP 401)** | НЕ скачивается автоматически; нужен ручной запрос доступа |

Полная таблица (размер, количество, атрибуция, точные команды curl, статус проверки) —
в [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) и [data/sources.yaml](data/sources.yaml).
Ни один источник не доверен «по-умолчанию»: всё сверяется с метаданными при загрузке.

## Как запустить

```bash
# 1) скачать (нужен интернет; в build-песочнице хосты корпуса недоступны —
#    используйте машину владельца или .github/workflows/corpus-nightly.yml)
python -m core.dataset_fetch --source zenodo_open_mech --limit 100 --out data/corpus/zenodo_open_mech
#    добавить: --source hf_jcrzd --limit 1000   /   --source hf_ecado --inspect

# 2) скрининг (только измеримые признаки: осевая линия, симметрия, Ø, кластеры видов)
python -m core.corpus_screen --corpus data/corpus --out data/corpus/screening.csv

# 3) прогон конвейера (каждый файл — отдельный подпроцесс, таймаут 120 c, resume)
python -m core.corpus_run --corpus data/corpus --out data/corpus/results.jsonl

# 4) отчёт (CORPUS_BENCHMARK.md + BUG_HARVEST.md + reports/*.png)
python -m core.corpus_report --golden-check
```

**Атрибуция (CC BY 4.0):** Open Mechanical 3D Models Dataset (zenodo.org/records/24167336),
licensed under CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/
(MechAtlas — CC BY 4.0 после одобрения доступа; jcrzd/ecado — unresolved, только
внутренняя сводная статистика, ни в релизах, ни в git, ни в цитировании.)

## Политика данных

- **Сырые файлы корпуса в git НЕ коммитятся.** `data/corpus/` в `.gitignore`;
  коммитятся только `manifest.jsonl` (sha256 каждого файла), `screening.csv`,
  `results.jsonl` и 20–40 маленьких образцов при необходимости.
- Источник D (MechAtlas, gated) не обходится и не подменяется — только ручной запрос,
  статус и инструкция в `docs/DATA_SOURCES.md`.
- Любая метрика в доках вычислена из закоммиченных `results.jsonl`/`screening.csv`.
  Не измерено — пишется NOT MEASURED, никогда не выдумывается.

## Ночные прогоны

`.github/workflows/corpus-nightly.yml` (cron 03:17 UTC + ручной запуск):
кэширует `data/corpus/` между прогонами, грузит Zenodo с `--limit 200`,
скринит, прогоняет, регенерирует отчёт, печатает воронку в job summary и
выкладывает артефакты (manifest/results/docs/png). Падает только на
инфраструктурных ошибках; пер-файловые сбои — это данные, а не падение CI.

## Что НЕ доказывают эти цифры

См. раздел «WHAT THESE NUMBERS DO NOT PROVE» в `docs/CORPUS_BENCHMARK.md`.
Коротко: покрытие = только то, что скачано и раскриптовано; призмы/резьбы/сечения/
сборки — вне области v1; Tier A сравнивает форму, а не чтение размеров;
синтетические «golden» фикстуры — это проверка конвейера в CI, а не точность на
реальных чертежах.
