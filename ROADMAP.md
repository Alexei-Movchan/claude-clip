# Roadmap — Cloudy Clip Studio

## MVP 0.3 changes
- Removed cloud LLM/API-key configuration.
- Added Ollama local-only endpoint with loopback hostname validation.
- Default local model: qwen3:4b; optional qwen3:8b / qwen2.5:7b.
- Added setup_local_ai.bat for one-time local model download.
- Added offline heuristic fallback when Ollama is unavailable.
- Updated Windows/CUDA and privacy documentation.

## Next
1. Implement physical HOOK reordering with synchronized audio/subtitle remapping.
2. Add a preview player and editable in/out points.
3. Add face tracking and speaker-aware reframing.
4. Add a robust local semantic quality classifier and duplicate detection.
5. Add NVENC detection and fallback to libx264.
6. Add local subtitle correction UI and frame-level banner compliance validation.
7. Build and test the EXE on Windows 10/11.


## Следующий этап после 1.1.0-dev
- Активное слежение за говорящим: детекция лиц + оценка синхронизации движения губ с речью; требуется отдельная локальная CV-модель и тесты на нескольких людях в кадре.
- Более надёжное распознавание сериал-опенингов и коротких перебивок, включая случаи с музыкой или речью поверх заставки.

## Версия 1.2.0-dev
- [x] Базовое определение вероятного говорящего по лицам и движению рта во время речи (OpenCV, эвристика).
- [x] Динамическое горизонтальное кадрирование за выбранным лицом с безопасным fallback.
- [ ] Надёжная классификация сериальных опенингов/перебивок с музыкой и закадровой речью.
- [ ] Автоматические зумы и проверка результата по чёрным кадрам/тишине.
- [ ] Тесты на реальных исходниках разного качества и с несколькими говорящими.
- [x] Постэкспортное сканирование чёрных кадров, зависаний и длительной тишины (предупреждения без автоматического удаления).
