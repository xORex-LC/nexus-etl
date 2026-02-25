from __future__ import annotations

import structlog.testing

from connector.infra.dictionaries.loader_csv import DictionaryCsvLoadEvent
from connector.infra.dictionaries.telemetry import DictionaryTelemetry
from connector.infra.dictionaries.versioning import build_dictionary_version_info


def test_key_fingerprint_is_deterministic_and_not_plaintext() -> None:
    telemetry = DictionaryTelemetry(fingerprint_salt="salt-v1")

    fp1 = telemetry.build_key_fingerprint("Org-1")
    fp2 = telemetry.build_key_fingerprint("Org-1")
    fp3 = telemetry.build_key_fingerprint("Org-2")

    assert fp1 == fp2
    assert fp1 != fp3
    assert len(fp1) == 12
    assert "Org-1" not in fp1


def test_sampling_is_deterministic_for_same_inputs() -> None:
    telemetry = DictionaryTelemetry(fingerprint_salt="salt-v1")
    fp = telemetry.build_key_fingerprint("org-1")

    first_bucket = telemetry._sample_bucket(  # noqa: SLF001 - intentional unit test for deterministic helper
        event="lookup_hit",
        dict_name="organizations",
        key_fingerprint=fp,
    )
    second_bucket = telemetry._sample_bucket(  # noqa: SLF001
        event="lookup_hit",
        dict_name="organizations",
        key_fingerprint=fp,
    )

    assert first_bucket == second_bucket
    assert 0 <= first_bucket < 100
    assert telemetry._should_sample_debug(  # noqa: SLF001
        event="lookup_hit",
        dict_name="organizations",
        key_fingerprint=fp,
    ) == telemetry._should_sample_debug(  # noqa: SLF001
        event="lookup_hit",
        dict_name="organizations",
        key_fingerprint=fp,
    )


def test_record_events_produce_structured_logs_and_snapshot() -> None:
    telemetry = DictionaryTelemetry(
        fingerprint_salt="salt-v1",
        lookup_hit_sample_percent=100,
        lookup_miss_sample_percent=100,
    )
    secret = "SECRET-PLAINTEXT"
    fp = telemetry.build_key_fingerprint(secret)

    with structlog.testing.capture_logs() as cap:
        telemetry.record_lookup_result(
            dict_name="organizations",
            op="lookup",
            hit=True,
            key_fingerprint=fp,
            result_count=1,
            fields=("name",),
            limit=1,
        )
        telemetry.record_lookup_result(
            dict_name="organizations",
            op="contains",
            hit=False,
            key_fingerprint=fp,
            result_count=0,
        )
        telemetry.record_lookup_error(
            dict_name="departments",
            op="lookup",
            key_fingerprint=fp,
            error=ValueError("boom"),
        )

    events = [entry["event"] for entry in cap]
    assert "lookup_hit" in events
    assert "lookup_miss" in events
    assert "lookup_error" in events

    for entry in cap:
        assert entry["component"] == "dictionary"
        assert entry["backend"] == "polars"
        assert "dict_name" in entry
        assert "op" in entry
        assert "key" not in entry
        assert "SECRET-PLAINTEXT" not in str(entry)

    snapshot = telemetry.snapshot()
    assert snapshot["component"] == "dictionary"
    assert snapshot["backend"] == "polars"
    assert snapshot["summary"]["warnings_count"] == 0
    assert snapshot["aggregate"] == {
        "lookup_total": 3,
        "lookup_hit": 1,
        "lookup_miss": 1,
        "lookup_error": 1,
    }
    assert snapshot["dictionaries_detail"]["organizations"]["lookup_total"] == 2
    assert snapshot["dictionaries_detail"]["organizations"]["lookup_hit"] == 1
    assert snapshot["dictionaries_detail"]["organizations"]["lookup_miss"] == 1
    assert snapshot["dictionaries_detail"]["organizations"]["lookup_error"] == 0
    assert snapshot["dictionaries_detail"]["departments"]["lookup_total"] == 1
    assert snapshot["dictionaries_detail"]["departments"]["lookup_error"] == 1
    assert snapshot["dictionaries_detail"]["departments"]["version_info"] is None
    assert secret not in str(snapshot)


def test_record_dictionary_loaded_adds_version_metadata_and_empty_source_warning() -> None:
    telemetry = DictionaryTelemetry(
        fingerprint_salt="salt-v1",
        lookup_hit_sample_percent=0,
        lookup_miss_sample_percent=0,
    )
    telemetry.record_runtime_initialized(
        enabled=True,
        load_strategy="lazy",
        declared_dict_names=("organizations",),
    )
    version_info = build_dictionary_version_info(
        dict_name="organizations",
        schema_hash="a" * 64,
        content_sha256="b" * 64,
        row_count=0,
        loaded_at="2026-02-23T12:00:00Z",
    )

    with structlog.testing.capture_logs() as cap:
        telemetry.record_dictionary_loaded(
            DictionaryCsvLoadEvent(
                dict_name="organizations",
                path="datasets/dictionaries/organizations.csv",
                row_count=0,
                content_sha256="b" * 64,
                source_empty=True,
                version_info=version_info,
            )
        )

    warning_events = [entry for entry in cap if entry.get("event") == "source_empty"]
    assert len(warning_events) == 1
    assert "key" not in warning_events[0]
    assert "SECRET" not in str(warning_events[0])

    snapshot = telemetry.snapshot()
    assert snapshot["summary"] == {
        "runtime_enabled": True,
        "load_strategy": "lazy",
        "declared_dictionaries": ["organizations"],
        "declared_count": 1,
        "loaded_count": 1,
        "warnings_count": 1,
    }
    assert snapshot["anomalies"][0]["code"] == "DICT_SOURCE_EMPTY"
    detail = snapshot["dictionaries_detail"]["organizations"]
    assert detail["row_count"] == 0
    assert detail["fingerprint_kind"] == "content_sha256"
    assert detail["version_info"]["version_id"].startswith("organizations:")
    assert detail["anomalies"][0]["severity"] == "WARNING"
