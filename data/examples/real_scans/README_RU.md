# Реальные сканы / Real scans

Сюда кладите файл скана реального чертежа (любое тело вращения, ГОСТ/ЕСКД).
Nothing is hardcoded to a specific file — the harness works on **any** scan dropped here.

## Как правильно отсканировать (важно для точности)

1. **Планшетный сканер**, не фото на телефон/камеру (перспектива + неравномерное освещение ломают размеры).
2. **300–600 DPI**, 8-битные оттенки серого (grayscale), без цвета — цвет только мешает бинеризации.
3. Лист ровный, **без перекоса более ~5°** (выравнивание делается автоматически, но большие углы съедают края).
4. Контраст высокий, без пятен/теней; фон белый. Скан должен покрывать **весь лист целиком**, без обрезанных линий.
5. Форматы: PNG (лучше), TIFF, JPEG (только качество 90+%).

## Куда положить и как назвать

- Положите файл сюда: `data/examples/real_scans/my_scan.png`
- Имя: `<деталь>_<dpi>dpi.png` — например `flange_450_300dpi.png`, `val_stanok_600dpi.png`
- Файл никуда не отправляется — всё обрабатывается локально.

## Что дальше

```bash
# отчёт по скану (ничего не меняя в чертеже):
python -m core.benchmark_real --scan data/examples/real_scans/my_scan.png
# с эталоном (если есть ground truth JSON с expected_volume_mm3):
python -m core.benchmark_real --scan ... --gt my_ground_truth.json
```

Отчёт: **`docs/real_scan_report.md`** (перезаписывается каждый прогон):
DPI, размеры, качество скана (резкость/шум/обрезка), сколько размеров найдено/привязано/
требуют подтверждения, погрешность длины, объём (с GT), предупреждения и вердикт.

> `docs/real_scan_report.md` в репозитории — это шаблон; ваш реальный отчёт перезапишет его
> локально и попадёт в git только если вы сами сделаете commit.

## В интерфейсе

Если качество низкое (DPI < 300 или большая погрешность длины), при открытии скана
показывается баннер «Низкое качество скана — пересканируйте в 300 DPI, точность ~3 мм» —
3D собирать с такого скана не рекомендуется.

---

**English:** Drop any scan of a GOST/ESKD body-of-revolution drawing here (flatbed, 300–600 DPI,
grayscale, sheet flat and fully in frame, no phone photos). Then run
`python -m core.benchmark_real --scan <file>`. Output: `docs/real_scan_report.md` with DPI,
quality metrics, dimension linking stats and volume error (if `--gt` is passed). Low quality
shows a warning banner before any 3D is built.
