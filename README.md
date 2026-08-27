# Koritsu 2.0 (pre)

Генератор схем из исходного кода для языков Python, C++, C#. Глобальное переписывание с версии 1.0 для лучшей работы.


## Пакеты

- `packages/fragmos` — блок-схемы из кода (Python, C++, C#).
- `packages/uml_generator` — UML: диаграмма классов (`extract_py/cs/cpp` + `build_xml`) и
  диаграмма объектов (`objektis`, статическая трассировка `main()` — код не выполняется).

Тесты: `.venv/bin/python -m pytest`. Лаборатории (образцы, галерея PNG, песочница) —
`~/koritsu2-extras/labs/{fragmos,uml}`.
