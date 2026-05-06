# Nuitka Standalone Blueprint

Временная рабочая заметка по сборке проекта в standalone-дистрибутив через Nuitka.

Статус: draft  
Фокус: только standalone-версия для Linux servers  
Актуально на дату: 2026-05-06

## 1. Цель

Собрать CLI-приложение `nexus` в standalone-дистрибутив без поставки исходных
Python-модулей проекта на сервер.

Ожидаемый результат:

- на сервер доставляется готовая runtime-директория;
- основной запуск идёт через бинарь `nexus`;
- Python-код проекта не лежит на сервере в виде `.py`;
- runtime-данные (`datasets`, конфиги, секреты, кэш, отчёты) живут как внешние файлы.

## 2. Почему standalone, а не package/module mode

Для этого репозитория standalone-режим лучше, чем сборка только в `.so`:

- не требует системного Python на сервере;
- лучше подходит для CLI-доставки;
- проще отлаживать missing data files;
- меньше operational complexity, чем compiled package + wheel + target CPython ABI.

Для текущего проекта `.so`-режим можно оставить как дополнительную ветку позже, но
не как основной production deployment format.

## 3. Репозиторные особенности, влияющие на сборку

### 3.1. YAML/DSL являются runtime-данными

Проект активно читает YAML-файлы из `datasets/`:

- dataset registry;
- source/mapping/normalize/enrich/match/resolve/sink specs;
- target specs;
- dictionary manifests/specs.

Это не package resources в текущем дизайне, а внешние runtime-файлы. Значит:

- их не надо пытаться "спрятать" в `.so`;
- их нужно класть рядом со standalone-дистрибутивом;
- loader'ы должны уметь стабильно находить их вне репозитория.

### 3.2. Сейчас есть конфликт `registry.yml` vs `registry.yaml`

В коде и документации исторически используется `datasets/registry.yml`, но в
репозитории реально есть файл:

- `datasets/registry.yaml`

При этом часть runtime/test-сценариев использует:

- `datasets/employees.registry.yaml`

Это нужно выровнять до внедрения сборки, иначе path resolution останется хрупким.

### 3.3. Сейчас runtime path partially завязан на repo root

Критичный участок:

- `connector/domain/dsl/loader/_common.py`

Сейчас там есть поиск ближайшего parent с `datasets/registry.yml` и fallback на
исторический `parents[4]`. Для standalone deployment это ненадёжный контракт.

## 4. Целевой runtime contract

Standalone-дистрибутив должен работать не из корня репозитория, а из собственной
runtime-директории.

Целевой контракт:

- если `dataset.registry_path` явно задан, использовать его;
- если `dataset.registry_path` не задан, брать registry из runtime layout рядом
  с дистрибутивом;
- пути к `cache`, `logs`, `reports` должны быть deploy-friendly;
- код не должен искать "корень репозитория" как обязательный runtime root.

## 5. Целевая структура standalone runtime

Предлагаемая структура:

```text
nexus.dist/
  nexus
  datasets/
    registry.yaml
    employees.registry.yaml
    *.yaml
    dictionaries/
    targets/
  examples/
    configs/
      config_example.yml
  var/
    cache/
    logs/
    reports/
  environment/
```

Если потребуется server-package layout:

```text
/opt/nexus/
  nexus
  datasets/
  examples/configs/
  var/cache/
  var/logs/
  var/reports/
  environment/
```

## 6. Что нужно поправить в коде до сборки

### 6.1. Выровнять имя registry-файла

Нужно выбрать канонический вариант:

- `registry.yaml`

Почему именно он:

- реальный файл уже существует в репозитории;
- остальные DSL-файлы у вас уже в `.yaml`;
- это уменьшает количество специальных случаев.

Нужно:

- обновить loader defaults;
- обновить docs/examples/tests, которые ждут `registry.yml`;
- оставить временную совместимость, если это нужно для migration window.

### 6.2. Убрать обязательную зависимость от repo root

Нужно заменить current fallback policy на явную runtime policy.

Рекомендуемый подход:

- добавить helper вида `connector/common/runtime_paths.py`;
- в нём определить функции для вычисления runtime root;
- использовать их в DSL loaders и связанных runtime-компонентах.

Ожидаемые helpers:

- `get_runtime_root()`
- `get_datasets_root()`
- `get_var_root()`
- `get_default_registry_path()`

Базовая идея:

- в compiled/standalone runtime опираться на директорию исполняемого файла;
- в dev-режиме сохранять поддержку запуска из checkout.

### 6.3. Зафиксировать default path policy

Текущее состояние:

- `cache_dir: "./cache"`
- `log_dir: "./logs"`
- `report_dir: "./reports"`

Целевой deploy-friendly вариант:

- `cache_dir: "./var/cache"`
- `log_dir: "./var/logs"`
- `report_dir: "./var/reports"`

Если менять дефолты рискованно, можно:

- оставить старые дефолты для dev;
- в standalone config template использовать `./var/...`.

### 6.4. Оставить конфиг и datasets внешними

Не надо встраивать в логику такие предположения:

- что `config.yml` лежит внутри бинаря;
- что datasets package-embedded;
- что `cwd` совпадает с местом запуска.

Правильный контракт:

- `config.yml` внешний;
- `datasets/` внешний;
- secrets/files для vault тоже внешние.

## 7. Файлы, которые с высокой вероятностью потребуют правок

Обязательно:

- `connector/domain/dsl/loader/_common.py`
- `connector/domain/dictionary_dsl/loader.py`
- `connector/config/models.py`
- `examples/configs/config_example.yml`
- `README.md`

Вероятно:

- `connector/delivery/cli/dictionaries_container.py`
- `tests/...`, где захардкожен `registry.yml`
- build/CI scripts

## 8. Build layout внутри репозитория

Нельзя смешивать setuptools build и standalone artifacts в одной плоской директории.

Рекомендуемый layout:

```text
build/
  nuitka/
    standalone/
      nexus.dist/
      compile-report.xml
  artifacts/
    nexus-linux-x86_64.tar.gz
```

Если позже появится отдельная compiled-package ветка, её держать отдельно:

```text
build/
  nuitka/
    standalone/
    module/
  artifacts/
```

## 9. Команда Nuitka для первого рабочего PoC

Базовая команда:

```bash
python3 -m nuitka \
  --mode=standalone \
  --assume-yes-for-downloads \
  --follow-imports \
  --output-dir=build/nuitka/standalone \
  --output-filename=nexus \
  --remove-output \
  --include-data-dir=datasets=datasets \
  --include-data-files=examples/configs/config_example.yml=examples/configs/config_example.yml \
  --nofollow-import-to=tests \
  --report=build/nuitka/standalone/compile-report.xml \
  connector/main.py
```

Замечания:

- `datasets/` включается как внешний runtime data dir;
- example config кладётся в дистрибутив как reference;
- `tests` исключаются из follow graph;
- `compile-report.xml` нужен для аудита dependency graph и data inclusion.

## 10. Что проверять после первой сборки

Минимальный smoke checklist:

- `nexus --help`
- `nexus --config ... --help`
- `nexus vault-management --help`
- `nexus mapping --help`
- чтение registry и stage YAML;
- создание `logs/reports/cache`;
- запуск не из корня репозитория, а из другой директории.

Важно проверять запуск так, чтобы не было случайной опоры на checkout path.

## 11. Makefile targets

Минимальный набор целей:

- `clean`
- `test`
- `build-standalone`
- `smoke-standalone`
- `package-artifacts`

Черновой состав:

```makefile
PYTHON ?= python3
NUITKA ?= $(PYTHON) -m nuitka

.PHONY: clean test build-standalone smoke-standalone package-artifacts

clean:
	rm -rf build/nuitka build/artifacts

test:
	$(PYTHON) -m pytest -q

build-standalone:
	$(NUITKA) \
	  --mode=standalone \
	  --assume-yes-for-downloads \
	  --follow-imports \
	  --output-dir=build/nuitka/standalone \
	  --output-filename=nexus \
	  --remove-output \
	  --include-data-dir=datasets=datasets \
	  --include-data-files=examples/configs/config_example.yml=examples/configs/config_example.yml \
	  --nofollow-import-to=tests \
	  --report=build/nuitka/standalone/compile-report.xml \
	  connector/main.py

smoke-standalone:
	build/nuitka/standalone/nexus.dist/nexus --help
	build/nuitka/standalone/nexus.dist/nexus --config build/nuitka/standalone/nexus.dist/examples/configs/config_example.yml --help

package-artifacts:
	mkdir -p build/artifacts
	tar -C build/nuitka/standalone -czf build/artifacts/nexus-linux-x86_64.tar.gz nexus.dist
```

## 12. Linux CI pipeline

Минимальный pipeline:

1. `lint + tests`
2. `build-standalone`
3. `smoke-standalone`
4. `package-artifact`

Рекомендуемые действия:

- установить `nuitka`, `ordered-set`, `zstandard`;
- собирать на предсказуемом Linux image;
- сохранить `compile-report.xml` как artifact;
- сохранить `nexus-linux-x86_64.tar.gz` как build artifact.

## 13. Риски

### 13.1. ABI и glibc

Standalone-дистрибутив всё равно зависит от того, на каком Linux-окружении он был
собран. Если собрать на слишком новом образе, можно получить проблемы на старых
серверах.

Практический вывод:

- собирать на том же baseline, что и production fleet;
- если fleet неоднородный, нужна matrix или более старый compatible base image.

### 13.2. Native dependencies

Нужно отдельно проверить поведение зависимостей:

- `polars`
- `cryptography`
- `argon2-cffi`

Они могут потребовать отдельной валидации на target-like Linux environment.

### 13.3. Path assumptions

Главный логический риск не в компиляции, а в runtime path resolution.

Если код продолжит ожидать:

- repo root;
- конкретный `cwd`;
- старое имя `registry.yml`;

то standalone PoC будет нестабилен.

## 14. Поэтапный план внедрения

### Этап 1. Stabilize runtime paths

- выбрать канонический `registry.yaml`;
- обновить default registry path в loaders;
- вынести runtime path helpers;
- убрать обязательный repo-root fallback.

### Этап 2. Stabilize deploy config

- обновить `examples/configs/config_example.yml`;
- определить standalone-friendly defaults для `paths`;
- описать deploy layout в `README.md`.

### Этап 3. Build PoC

- добавить `Makefile` или `scripts/build_nuitka.sh`;
- собрать `build/nuitka/standalone/nexus.dist`;
- прогнать smoke checks.

### Этап 4. CI

- автоматизировать сборку на Linux;
- публиковать tarball artifact;
- сохранять compile report.

## 15. Решения, которые приняты в этой заметке

- production focus: только `standalone`;
- datasets/configs/secrets остаются внешними файлами;
- runtime path contract должен быть явным;
- `registry.yaml` должен стать каноническим именем;
- build artifacts нужно раскладывать отдельно от setuptools outputs.

## 16. Следующий практический шаг

Следующий шаг после этой заметки:

- внести path-stabilization правки в loaders и config defaults;
- затем добавить `Makefile` и первую команду `build-standalone`.
