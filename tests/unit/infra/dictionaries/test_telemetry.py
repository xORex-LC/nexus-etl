from __future__ import annotations

import structlog.testing

from connector.infra.dictionaries.telemetry import DictionaryTelemetry


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
    assert snapshot["aggregate"] == {
        "lookup_total": 3,
        "lookup_hit": 1,
        "lookup_miss": 1,
        "lookup_error": 1,
    }
    assert snapshot["dictionaries_detail"]["organizations"] == {
        "lookup_total": 2,
        "lookup_hit": 1,
        "lookup_miss": 1,
        "lookup_error": 0,
    }
    assert snapshot["dictionaries_detail"]["departments"] == {
        "lookup_total": 1,
        "lookup_hit": 0,
        "lookup_miss": 0,
        "lookup_error": 1,
    }
