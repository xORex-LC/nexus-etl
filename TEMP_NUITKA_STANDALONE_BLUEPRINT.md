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

## 17. Уточнённая модель runtime-ресурсов

Ниже зафиксирована обновлённая целевая модель, принятая после уточнения
требований к внешним runtime-артефактам.

### 17.1. Базовый принцип

Отказываемся от подхода, где YAML-файлы хранят имена ENV-переменных для путей.

Вместо этого используется единая модель:

- `config.yaml` задаёт корневые runtime-директории;
- DSL/registry/spec/manifest хранят logical или relative refs;
- код резолвит effective filesystem paths через единый runtime resolver.

Это означает:

- YAML остаются переносимыми и самодостаточными;
- deploy-specific filesystem layout не протекает в domain DSL;
- standalone runtime не зависит от `cwd`, repo root и прямых строковых путей.

### 17.2. Приоритет источников path-конфигурации

Принято следующее правило приоритетов:

1. Явный путь из `config.yaml`
2. Runtime-root relative default
3. Linux-compatible fallback profile только как опциональный режим

ENV как основной механизм path-конфигурации не используется.

### 17.3. Именованные runtime roots

Целевая модель runtime resolver должна поддерживать именованные roots:

- `runtime_root`
- `config_root`
- `datasets_root`
- `dictionary_data_root`
- `dictionary_specs_root`
- `source_projection_root`
- `target_projection_root`
- `cache_root`
- `logs_root`
- `reports_root`

Назначение:

- `runtime_root` — корень runtime-артефактов standalone deployment;
- `config_root` — каталог c `config.yaml` и прочими конфигурационными YAML;
- `datasets_root` — dataset-level DSL декларации стадий и dataset registry;
- `dictionary_data_root` — CSV/данные словарей;
- `dictionary_specs_root` — dictionary spec/manifest YAML;
- `source_projection_root` — source projection YAML;
- `target_projection_root` — target/cache projection YAML;
- `cache_root` — sqlite/local mirror state;
- `logs_root` — runtime logs;
- `reports_root` — output reports.

### 17.4. Recommended runtime layout

Целевой runtime layout по умолчанию:

```text
nexus/
  datasets/
    <dataset_name>/
      mapping.yaml
      normalize.yaml
      enrich.yaml
      match.yaml
      resolve.yaml
      sink.yaml
  dictionaries/
    <dataset_name>/
      dictionary.csv
      dictionary_2.csv
    manifest.yaml
  etc/
    config.yaml
    dictionaries/
      <dataset_name>/
        dictionary.yaml
        dictionary_2.yaml
      manifest.yaml
    source-projection/
      datasets/
        <dataset_name>/
          source.yaml
    target-projection/
      <target_name>/
        target.yaml
  reports/
  var/
    cache/
    logs/
```

Важно:

- это дерево описывает только runtime artifacts, но не код и не bundled binaries;
- standalone binary может лежать рядом с этим деревом или внутри этого дерева,
  пока resolver корректно определяет `runtime_root`.

### 17.5. Что хранится в config.yaml

`config.yaml` должен стать главным местом, где пользователь задаёт корневые пути.

Минимально нужны поля для:

- `runtime_root`
- `config_root`
- `datasets_root`
- `dictionary_data_root`
- `dictionary_specs_root`
- `source_projection_root`
- `target_projection_root`
- `cache_dir`
- `log_dir`
- `report_dir`

Примечание:

- для обратной совместимости возможны старые поля (`cache_dir`, `log_dir`, `report_dir`);
- но новые roots должны стать canonical source of truth для resolver.

### 17.6. Что хранится в registry/spec/manifest

Принято следующее правило:

- registry/spec/manifest не хранят deploy-specific absolute roots;
- они хранят logical или relative refs внутри своей предметной области.

Например:

- dataset stage YAML paths — относительно `datasets_root`;
- dictionary spec/manifest YAML paths — относительно `dictionary_specs_root`;
- dictionary CSV paths — относительно `dictionary_data_root`;
- target/cache projection YAML — относительно `target_projection_root`;
- source projection YAML — относительно `source_projection_root`.

### 17.7. Resolution policy

Резолвинг путей должен быть централизован.

Целевой runtime resolver:

- знает именованные roots;
- знает policy для разных типов ресурсов;
- возвращает абсолютные `Path` для фактического IO;
- не читает YAML и не знает DSL semantics.

Примеры типов ресурсов:

- dataset stage specs
- dataset registry
- dictionary spec
- dictionary manifest
- dictionary CSV snapshot
- source projection
- target projection
- cache db
- logs
- reports

### 17.8. Responsibility boundaries

Разделение ответственности фиксируется так:

`config layer`

- загружает и валидирует пользовательские пути;
- не читает DSL и не выполняет IO resource lookup.

`runtime resolver layer`

- знает runtime roots и policy path resolution;
- не знает бизнес-смысла YAML и не валидирует domain models.

`DSL loaders`

- знают, какой логический ресурс им нужен;
- не знают deploy layout и не ищут repo root.

`infra loaders`

- выполняют фактическое IO по уже резолвленным путям;
- не определяют root policy самостоятельно.

### 17.9. Принятые решения

Зафиксированы следующие решения:

- не использовать ENV indirection внутри YAML;
- использовать `config.yaml` как главный источник runtime path configuration;
- хранить в DSL logical/relative refs, а не абсолютные deploy paths;
- ввести named runtime roots;
- централизовать resolution policy в одном thin runtime resolver;
- считать standalone deployment основным production target.

## 18. Анализ текущего состояния кода

Ниже зафиксирована карта текущих path/runtime contracts и расхождений с новой
целевой моделью.

### 18.1. Что уже сделано

В коде уже есть первый шаг в сторону нового runtime contract:

- добавлен `connector/common/runtime_paths.py`;
- `connector/domain/dsl/loader/_common.py` переведён на runtime root/datasets root;
- `connector/domain/dictionary_dsl/loader.py` упрощён и больше не держит
  собственную repo-root эвристику;
- `connector/delivery/cli/dictionaries_container.py` использует resolver для
  выбора registry filename.

Это полезный старт, но целевая модель runtime roots и typed resource resolution
пока не реализована полностью.

### 18.2. Главные источники "двух истин"

#### A. `datasets_root` пока играет роль универсального root-а

Сейчас значительная часть DSL runtime считает, что все YAML-ресурсы резолвятся
относительно одного `datasets_root`.

Затронутые модули:

- `connector/domain/transform_dsl/loader.py`
- `connector/domain/cache_dsl/loader.py`
- `connector/domain/target_dsl/loader.py`
- `connector/domain/dataset_dsl/loader.py`
- `connector/domain/dictionary_dsl/loader.py`

Конфликт с целевой моделью:

- по новой модели у разных типов ресурсов должны быть разные logical roots
  (`datasets_root`, `dictionary_specs_root`, `dictionary_data_root`,
  `source_projection_root`, `target_projection_root`).

#### B. Source path resolution всё ещё завязан на ENV contract

Текущее поведение:

- `source.location_ref` хранит имя ENV переменной;
- runtime пытается прочитать путь из process environment;
- при отсутствии значения используется `source.location`.

Затронутые модули:

- `connector/domain/transform_dsl/specs/source.py`
- `connector/domain/transform_dsl/loader.py`

Конфликт с целевой моделью:

- принято решение отказаться от ENV indirection внутри YAML;
- source runtime должен использовать config-driven/runtime-resolver-driven path policy.

#### C. Config layer знает только старые operational paths

Сейчас в config-model есть только:

- `paths.cache_dir`
- `paths.log_dir`
- `paths.report_dir`
- `dataset.registry_path`

Затронутые модули:

- `connector/config/models.py`
- `connector/config/loader.py`
- `examples/configs/config_example.yml`

Проблема:

- новых canonical runtime roots ещё нет;
- runtime resource model пока не может быть выражена через config-layer.
- `config.loader` по-прежнему поддерживает ENV overrides как часть merge-логики,
  что создаёт второй path/config channel, если не будет явно ограничено новой моделью.

#### D. Dictionary CSV резолвятся неявно через `datasets_root`

Текущее поведение:

- CSV loader строит path как `datasets_root / spec.source.location`;
- отдельная директория `./dictionaries` может использоваться только как
  побочный эффект через relative path вроде `../dictionaries/foo.csv`.

Затронутые модули:

- `connector/infra/dictionaries/loader_csv.py`
- `connector/infra/dictionaries/dsl_runtime.py`
- `connector/domain/dictionary_dsl/specs.py`

Проблема:

- это неявный contract;
- `dictionary_data_root` пока не существует как first-class runtime root;
- spec/manifest/loader разделяют старую path semantics.

#### E. Dictionary spec и manifest всё ещё используют строковое path equality

Текущее поведение:

- runtime compile step требует строкового совпадения
  `spec.source.location == manifest.csv_path` после простой нормализации.

Затронутый модуль:

- `connector/infra/dictionaries/dsl_runtime.py`

Проблема:

- это не typed resource contract, а строковое сравнение;
- новая модель требует logical/relative refs внутри `dictionary_data_root`,
  а не path hacks через `datasets_root`.

#### F. Legacy fallback по имени registry-файла ещё сохраняется

Сейчас runtime resolver поддерживает:

- `registry.yaml`
- `registry.yml`

Затронутый модуль:

- `connector/common/runtime_paths.py`

Проблема:

- это допустимо как migration layer;
- но не должно остаться final source of truth после cleanup.

#### G. Runtime root resolution пока всё ещё допускает ENV override

Сейчас в runtime path layer остаётся:

- `NEXUS_RUNTIME_ROOT`

Затронутый модуль:

- `connector/common/runtime_paths.py`

Проблема:

- если целевая модель окончательно уходит от ENV как runtime path mechanism,
  этот override должен быть удалён или по крайней мере перестать быть canonical behavior.

#### H. YAML templates и examples фиксируют старую path semantics

Сейчас шаблоны и примеры документируют legacy contract:

- `datasets/yaml_templates/registry.yaml`
- `datasets/yaml_templates/source.yaml`
- `datasets/dictionaries/dictionary.yaml`
- `datasets/dictionaries/manifest.yaml`
- `examples/configs/config_example.yml`

Что именно legacy:

- `datasets/registry.yml` как runtime default в комментариях;
- `location_ref` как нормальный источник physical path;
- dictionary CSV "relative from datasets root";
- старые defaults `./cache`, `./logs`, `./reports`.

Проблема:

- даже если код будет переведён, шаблоны продолжат переintroduce старый contract.

#### I. DI wiring для SQLite всё ещё владеет file naming policy локально

Сейчас naming/path policy для sqlite-файлов зашита прямо в CLI composition root:

- `connector/delivery/cli/containers.py`

Текущее поведение:

- `ankey_cache.sqlite3` строится из `cache_dir`;
- `ankey_vault.sqlite3` строится из `cache_dir`, если нет override;
- `identity.sqlite3` строится из `cache_dir`, если нет override.

Проблема:

- это отдельная локальная path policy;
- её нужно подчинить единому runtime/config contract, а не держать в DI helper functions.

### 18.3. Модули, которые необходимо перевести на новый contract

#### 1. Foundation: config + runtime resolver

Нужно перевести:

- `connector/config/models.py`
- `connector/config/loader.py`
- `examples/configs/config_example.yml`
- `connector/common/runtime_paths.py`
- `datasets/yaml_templates/registry.yaml`
- `datasets/yaml_templates/source.yaml`

Что должно появиться:

- named runtime roots;
- canonical config contract для resource roots;
- typed resolution policy для разных типов runtime-ресурсов.

#### 2. Все DSL loaders

Нужно перевести:

- `connector/domain/transform_dsl/loader.py`
- `connector/domain/cache_dsl/loader.py`
- `connector/domain/target_dsl/loader.py`
- `connector/domain/dataset_dsl/loader.py`
- `connector/domain/dictionary_dsl/loader.py`

Что должно исчезнуть:

- assumption, что любой YAML-файл лежит под `datasets_root`.

#### 3. Source runtime

Нужно перевести:

- `connector/domain/transform_dsl/specs/source.py`
- `connector/domain/transform_dsl/loader.py`
- `connector/infra/sources/csv_reader.py`
- `datasets/source.yaml`
- `datasets/yaml_templates/source.yaml`
- `datasets/employees/source_1/source.yaml`
- `datasets/employees/source_2/source.yaml`

Что должно исчезнуть:

- `location_ref` как основной path mechanism;
- ENV-based resolution для runtime data files.

#### 4. Dictionary runtime

Нужно перевести:

- `connector/infra/dictionaries/loader_csv.py`
- `connector/infra/dictionaries/dsl_runtime.py`
- `connector/domain/dictionary_dsl/specs.py`
- `connector/delivery/cli/dictionaries_container.py`
- `datasets/dictionaries/dictionary.yaml`
- `datasets/dictionaries/manifest.yaml`
- `datasets/dictionaries/ankey.dictionary.manifest.yaml`
- `datasets/dictionaries/departments.dictionary.yaml`
- `datasets/dictionaries/job_title.dictionary.yaml`

Что должно появиться:

- явный `dictionary_specs_root`;
- явный `dictionary_data_root`;
- resource resolution без implicit `../dictionaries`.

#### 5. Operational outputs

Нужно перевести:

- `connector/config/models.py`
- `connector/infra/logging/setup.py`
- `connector/infra/artifacts/report_renderer.py`
- sqlite path wiring, использующее `cache_dir`
- `connector/delivery/cli/containers.py`
- `examples/configs/config_example.yml`

Что должно появиться:

- canonical defaults под runtime layout:
  - `var/cache`
  - `var/logs`
  - `reports`

### 18.4. Legacy-механизмы, которые должны быть удалены

После завершения миграции не должны оставаться как canonical behavior:

- `location_ref` и ENV-based source path resolution;
- `NEXUS_RUNTIME_ROOT` как canonical runtime root override;
- config path overrides через ENV, если финальная модель запрещает ENV-channel;
- fallback `registry.yml`;
- прямые canonical defaults `./cache`, `./logs`, `./reports`;
- прямое использование `datasets_root` как универсального root-а для всех
  resource types;
- production path logic, основанная на `Path(__file__).resolve().parents[...]`
  или repo-root эвристиках.
- yaml templates/examples, документирующие старую path semantics.

### 18.5. Future single source of truth

После миграции единственная истина должна быть такой:

- `config.yaml` задаёт runtime roots;
- runtime resolver переводит logical refs в absolute filesystem paths;
- registry/spec/manifest содержат только logical/relative refs;
- DSL loaders не знают deploy layout;
- infra loaders не определяют root policy самостоятельно.

### 18.6. Критичный список миграции

Минимальный набор модулей, которые определяют успех миграции:

- `connector/config/models.py`
- `connector/config/loader.py`
- `connector/common/runtime_paths.py`
- `connector/domain/transform_dsl/loader.py`
- `connector/domain/cache_dsl/loader.py`
- `connector/domain/target_dsl/loader.py`
- `connector/domain/dictionary_dsl/loader.py`
- `connector/infra/dictionaries/loader_csv.py`
- `connector/infra/dictionaries/dsl_runtime.py`
- `connector/domain/transform_dsl/specs/source.py`
- `connector/delivery/cli/containers.py`
- `datasets/yaml_templates/registry.yaml`
- `datasets/yaml_templates/source.yaml`
- `datasets/dictionaries/dictionary.yaml`
- `datasets/dictionaries/manifest.yaml`

Если эти модули не будут приведены к новому contract, в проекте сохранятся
две несовместимые модели runtime path resolution.

### 18.7. Дополнительные наблюдения после контрольного прохода

- Tracked dataset instances уже используют смешанную модель:
  `datasets/employees/source_1/source.yaml` и `datasets/employees/source_2/source.yaml`
  всё ещё завязаны на `location_ref`, а dictionary manifests/specs частично уже
  используют `../dictionaries/...`.
- Примеры и тестовые fixtures массово закрепляют legacy names/paths:
  `registry.yml`, `EMPLOYEES_SOURCE_PATH`, `./cache`, `./logs`, `./reports`.
  Это не production-код, но это важный migration surface: без обновления тестов и
  шаблонов старая модель будет возвращаться в кодовую базу.
- DI composition root сейчас содержит inline path helpers для sqlite-файлов.
  Их нельзя оставить как отдельный "тихий стандарт", если хотим один canonical resolver.

## 19. Migration Backlog

Ниже зафиксирован поэтапный backlog миграции на новую runtime model. Он должен
использоваться как основной execution plan.

### 19.1. Цели backlog

Backlog должен привести кодовую базу к состоянию, где:

- существует один canonical runtime contract;
- config-layer выражает все нужные runtime roots;
- DSL/spec/manifest используют logical или relative refs;
- production code не зависит от repo root, `cwd`, `registry.yml`, `location_ref`;
- standalone deployment может работать без `.py` модулей проекта и без legacy path logic.

### 19.2. Этап 0. Freeze Contract

Цель:

- закрепить новую runtime model как единственную целевую.

Сделать:

- утвердить набор named runtime roots:
  - `runtime_root`
  - `config_root`
  - `datasets_root`
  - `dictionary_specs_root`
  - `dictionary_data_root`
  - `source_projection_root`
  - `target_projection_root`
  - `cache_root`
  - `logs_root`
  - `reports_root`
- утвердить, что YAML больше не используют ENV indirection для path resolution;
- утвердить, что `registry.yaml` является каноническим именем;
- утвердить, что `location_ref` удаляется из production contract;
- утвердить, что standalone deployment является primary production target.

Артефакты:

- этот blueprint документ;
- согласованное архитектурное решение по runtime resource model.

Критерий готовности:

- все дальнейшие изменения ссылаются только на эту модель.

### 19.3. Этап 1. Foundation: Config Model

Цель:

- сделать новый runtime contract выражаемым через `config.yaml`.

Нужно изменить:

- `connector/config/models.py`
- `connector/config/loader.py`
- `examples/configs/config_example.yml`
- unit-тесты config-layer

Что должно появиться:

- новая секция runtime resource roots;
- separation между resource roots и operational output dirs;
- migration-safe bridge от старых полей к новым.

Новые поля (предварительный целевой набор):

- `runtime.runtime_root`
- `runtime.config_root`
- `runtime.datasets_root`
- `runtime.dictionary_specs_root`
- `runtime.dictionary_data_root`
- `runtime.source_projection_root`
- `runtime.target_projection_root`
- `paths.cache_dir`
- `paths.log_dir`
- `paths.report_dir`

Важно:

- старые `cache_dir`, `log_dir`, `report_dir` можно временно сохранить;
- но они должны быть приведены к runtime layout и перестать быть единственными
  файловыми path knobs системы.

Критерий готовности:

- `AppConfig` может описать полный runtime filesystem contract.

### 19.4. Этап 2. Foundation: Runtime Resolver API

Цель:

- заменить текущий `runtime_paths.py` на полноценный typed runtime resolver.

Нужно изменить:

- `connector/common/runtime_paths.py`
- unit-тесты в `tests/unit/runtime`

Что должно появиться:

- immutable runtime snapshot;
- typed methods для разных resource families;
- policy resolution только в одном месте;
- отказ от ENV-based runtime-root contract как canonical behavior.

Пример целевого API:

- `resolve_dataset_registry()`
- `resolve_dataset_stage_ref(ref)`
- `resolve_dictionary_spec_ref(ref)`
- `resolve_dictionary_manifest_ref(ref)`
- `resolve_dictionary_data_ref(ref)`
- `resolve_source_projection_ref(ref)`
- `resolve_target_projection_ref(ref)`
- `resolve_cache_path(name)`
- `resolve_log_file(name)`
- `resolve_report_file(name)`

Что должно исчезнуть:

- локальные path helpers в loader'ах;
- `NEXUS_RUNTIME_ROOT` как canonical runtime mechanism, если он не нужен как
  осознанный compatibility mode.

Критерий готовности:

- production path policy живёт только в runtime resolver layer.

### 19.5. Этап 3. DSL Loaders Migration

Цель:

- убрать модель, где `datasets_root` является универсальным root для всех YAML.

Нужно изменить:

- `connector/domain/transform_dsl/loader.py`
- `connector/domain/cache_dsl/loader.py`
- `connector/domain/target_dsl/loader.py`
- `connector/domain/dataset_dsl/loader.py`
- `connector/domain/dictionary_dsl/loader.py`

Что должно измениться:

- loaders больше не строят filesystem paths самостоятельно;
- loaders запрашивают у runtime resolver типизированный resource path;
- registry paths трактуются как logical/relative refs, а не как implicit paths
  от `datasets_root` для всех resource families.

Критерий готовности:

- ни один production DSL loader не содержит собственной root policy.

### 19.6. Этап 4. Source Runtime Migration

Цель:

- удалить ENV-based source path resolution.

Нужно изменить:

- `connector/domain/transform_dsl/specs/source.py`
- `connector/domain/transform_dsl/loader.py`
- `connector/infra/sources/csv_reader.py`
- `datasets/source.yaml`
- `datasets/yaml_templates/source.yaml`
- tracked source DSL:
  - `datasets/employees/source_1/source.yaml`
  - `datasets/employees/source_2/source.yaml`

Что должно исчезнуть:

- `location_ref`;
- вызовы `os.getenv()` как часть runtime path resolution;
- документация "source path comes from ENV name inside YAML".

Что должно появиться:

- source DSL хранит logical или relative ref;
- source data path резолвится через config + runtime resolver.

Критерий готовности:

- source runtime больше не зависит от process ENV для physical source file path.

### 19.7. Этап 5. Dictionary Runtime Migration

Цель:

- сделать `dictionary_specs_root` и `dictionary_data_root` first-class concepts.

Нужно изменить:

- `connector/infra/dictionaries/loader_csv.py`
- `connector/infra/dictionaries/dsl_runtime.py`
- `connector/domain/dictionary_dsl/specs.py`
- `connector/delivery/cli/dictionaries_container.py`
- dictionary templates и tracked specs/manifests:
  - `datasets/dictionaries/dictionary.yaml`
  - `datasets/dictionaries/manifest.yaml`
  - `datasets/dictionaries/ankey.dictionary.manifest.yaml`
  - `datasets/dictionaries/departments.dictionary.yaml`
  - `datasets/dictionaries/job_title.dictionary.yaml`

Что должно измениться:

- dictionary spec YAML резолвятся через `dictionary_specs_root`;
- dictionary manifest YAML резолвятся через `dictionary_specs_root`;
- dictionary CSV paths резолвятся через `dictionary_data_root`;
- строковое/неявное `../dictionaries` перестаёт быть mechanism of truth.

Особый риск:

- `dsl_runtime.py` сейчас сравнивает `spec.source.location` и `manifest.csv_path`
  как строки; этот contract нужно заменить на semantic/path-family contract.

Критерий готовности:

- dictionary runtime работает без path-hacks относительно `datasets_root`.

### 19.8. Этап 6. Operational Paths and SQLite

Цель:

- подчинить cache/logs/reports/sqlite единому runtime contract.

Нужно изменить:

- `connector/config/models.py`
- `connector/infra/logging/setup.py`
- `connector/infra/artifacts/report_renderer.py`
- `connector/delivery/cli/containers.py`
- sqlite-related DI wiring и tests

Что должно измениться:

- `cache_dir`, `log_dir`, `report_dir` должны перейти на canonical defaults:
  - `var/cache`
  - `var/logs`
  - `reports`
- naming/path policy для:
  - `ankey_cache.sqlite3`
  - `ankey_vault.sqlite3`
  - `identity.sqlite3`
  должна быть вынесена из локальных DI helpers в единый runtime/config contract.

Критерий готовности:

- operational outputs и sqlite file paths резолвятся без локальных path policies.

### 19.9. Этап 7. Templates, Examples, Tracked DSL

Цель:

- не оставить старую модель в официальных templates/examples.

Нужно изменить:

- `datasets/yaml_templates/registry.yaml`
- `datasets/yaml_templates/source.yaml`
- `datasets/yaml_templates/cache.yaml`
- `datasets/yaml_templates/target.yaml`
- `datasets/dictionaries/dictionary.yaml`
- `datasets/dictionaries/manifest.yaml`
- `examples/configs/config_example.yml`
- tracked registry/spec/manifests при необходимости

Что должно исчезнуть:

- комментарии про `datasets/registry.yml` как runtime default;
- описание dictionary CSV как "relative from datasets root";
- `location_ref` как нормальный паттерн конфигурации;
- defaults `./cache`, `./logs`, `./reports`.

Критерий готовности:

- новые файлы, создаваемые пользователем по templates/examples, уже живут в новой модели.

### 19.10. Этап 8. Tests Migration

Цель:

- тесты должны закреплять только новую runtime model.

Нужно изменить:

- unit tests в `tests/unit/runtime`
- unit/integration tests для DSL loaders
- dictionary/source/config-related tests
- fixtures:
  - `tests/conftest.py`
  - `tests/integration/secrets/_temp_registry.py`
  - `tests/integration/delivery/test_dictionary_container.py`
  - source-related e2e/integration tests

Что должно исчезнуть:

- fixtures, закрепляющие `registry.yml`;
- fixtures, закрепляющие `EMPLOYEES_SOURCE_PATH` как canonical behavior;
- fixtures, закрепляющие `./cache`, `./logs`, `./reports` как canonical defaults;
- тестовые path hacks с `../dictionaries`, если новая модель их запрещает.

Критерий готовности:

- тестовый контур подтверждает только новую path semantics.

### 19.11. Этап 9. Legacy Cleanup

Цель:

- удалить все временные compatibility branches.

Удалить:

- fallback `registry.yml`;
- `location_ref`;
- source runtime ENV path resolution;
- `NEXUS_RUNTIME_ROOT`, если не остаётся как supported compatibility feature;
- устаревшие comments/docs/templates про legacy path semantics;
- прямые canonical defaults `./cache`, `./logs`, `./reports`, если они были только migration bridge.

Критерий готовности:

- в production-коде и официальных templates остаётся только одна runtime model.

### 19.12. Рекомендуемый порядок выполнения

Рекомендуемый порядок этапов:

1. Этап 1 — Config Model
2. Этап 2 — Runtime Resolver API
3. Этап 3 — DSL Loaders Migration
4. Этап 5 — Dictionary Runtime Migration
5. Этап 4 — Source Runtime Migration
6. Этап 6 — Operational Paths and SQLite
7. Этап 7 — Templates, Examples, Tracked DSL
8. Этап 8 — Tests Migration
9. Этап 9 — Legacy Cleanup

Почему так:

- сначала foundation;
- затем общий runtime resolution;
- потом YAML/dictionary contracts;
- затем source runtime;
- затем operational outputs;
- и только после этого cleanup совместимости.

### 19.13. Ближайший practical start

Следующий практический шаг по backlog:

- начать Этап 1 и Этап 2;
- сначала расширить config model;
- затем на этой основе собрать final runtime resolver API.

Это даст стабильный фундамент для остальных миграций и не заставит переписывать
loader'ы дважды.
