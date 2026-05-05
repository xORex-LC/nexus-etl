from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from connector.domain.dictionary_dsl.specs import DictionarySpec
from connector.infra.dictionaries.versioning import (
    build_content_sha256_bytes,
    build_dictionary_schema_hash,
)


def build_temp_employees_registry_with_temp_dictionaries(tmp_path: Path) -> tuple[Path, tuple[str, str]]:
    """
    Назначение:
        Собрать независимый test registry для employees runtime в пределах `tmp_path`.

    Что делает:
        - копирует в temp только нужные dataset/target DSL файлы;
        - создает временный registry с независимыми именами словарей;
        - создает временные dictionary spec/CSV/manifest файлы без зависимости от tracked
          путей и имен словарей репозитория.
    """
    repo_root = Path(__file__).resolve().parents[3]
    repo_datasets = repo_root / "datasets"
    repo_dictionary_sources = repo_root / "dictionaries"

    datasets_root = tmp_path / "datasets"
    dictionaries_dir = datasets_root / "dictionaries"
    dictionary_sources_dir = tmp_path / "dictionaries"
    targets_dir = datasets_root / "targets"
    employees_source_dir = datasets_root / "employees" / "source_2"

    dictionaries_dir.mkdir(parents=True, exist_ok=True)
    dictionary_sources_dir.mkdir(parents=True, exist_ok=True)
    targets_dir.mkdir(parents=True, exist_ok=True)
    employees_source_dir.mkdir(parents=True, exist_ok=True)

    files_to_copy = [
        ("employees/source_2/source.yaml", "employees/source_2/source.yaml"),
        ("employees/source_2/mapping.yaml", "employees/source_2/mapping.yaml"),
        ("employees.normalize.yaml", "employees.normalize.yaml"),
        ("employees.enrich.yaml", "employees.enrich.yaml"),
        ("employees.validate.yaml", "employees.validate.yaml"),
        ("employees.match.yaml", "employees.match.yaml"),
        ("employees.resolve.yaml", "employees.resolve.yaml"),
        ("employees.sink.yaml", "employees.sink.yaml"),
        ("employees.cache.yaml", "employees.cache.yaml"),
        ("organizations.cache.yaml", "organizations.cache.yaml"),
        ("targets/ankey.target.yaml", "targets/ankey.target.yaml"),
    ]

    for src_rel, dst_rel in files_to_copy:
        src = repo_datasets / src_rel
        dst = datasets_root / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    registry_payload = yaml.safe_load((repo_datasets / "employees.registry.yaml").read_text(encoding="utf-8"))

    departments_name = "runtime_units"
    job_title_name = "runtime_titles"
    departments_csv_name = "runtime_units.csv"
    job_title_csv_name = "runtime_titles.csv"
    departments_spec_name = "runtime_units.dictionary.yaml"
    job_title_spec_name = "runtime_titles.dictionary.yaml"
    manifest_name = "manifest.runtime.yaml"

    dictionary_blueprints = [
        (
            repo_datasets / "dictionaries" / "departments.dictionary.yaml",
            repo_dictionary_sources / "departments.csv",
            departments_name,
            departments_spec_name,
            departments_csv_name,
        ),
        (
            repo_datasets / "dictionaries" / "job_title.dictionary.yaml",
            repo_dictionary_sources / "job_title.csv",
            job_title_name,
            job_title_spec_name,
            job_title_csv_name,
        ),
    ]

    manifest_items: dict[str, dict[str, object]] = {}
    registry_items: dict[str, dict[str, object]] = {}

    for spec_src, csv_src, dict_name, spec_filename, csv_filename in dictionary_blueprints:
        spec_payload = yaml.safe_load(spec_src.read_text(encoding="utf-8"))
        spec_payload["dictionary"] = dict_name
        spec_payload["source"]["location"] = f"../dictionaries/{csv_filename}"

        spec_model = DictionarySpec.model_validate(spec_payload)
        csv_bytes = csv_src.read_bytes()

        (dictionaries_dir / spec_filename).write_text(
            yaml.safe_dump(spec_payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        (dictionary_sources_dir / csv_filename).write_bytes(csv_bytes)

        manifest_items[dict_name] = {
            "csv_path": f"../dictionaries/{csv_filename}",
            "content_sha256": build_content_sha256_bytes(csv_bytes),
            "schema_hash": build_dictionary_schema_hash(spec_model),
            "row_count": sum(1 for _ in csv_bytes.decode("utf-8-sig").splitlines()[1:] if _.strip()),
            "updated_at_utc": "2026-05-05T00:00:00Z",
            "owner": "tests",
        }
        registry_items[dict_name] = {
            "spec": f"dictionaries/{spec_filename}",
            "enabled": True,
        }

    registry_payload["dictionaries"]["manifest"] = f"dictionaries/{manifest_name}"
    registry_payload["dictionaries"]["items"] = registry_items

    (datasets_root / "employees.registry.yaml").write_text(
        yaml.safe_dump(registry_payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    (dictionaries_dir / manifest_name).write_text(
        yaml.safe_dump({"version": 1, "items": manifest_items}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    return datasets_root / "employees.registry.yaml", (departments_name, job_title_name)
