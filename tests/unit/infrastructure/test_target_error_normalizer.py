from __future__ import annotations

from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.target.core.engines.error_normalizer import TargetErrorNormalizer
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.providers.ankey_rest.provider import build_transport_compiler_registry
from connector.infra.target.providers.ankey_rest.spec import build_ankey_spec


def test_from_status_maps_to_fault_and_system_code() -> None:
    normalizer = TargetErrorNormalizer(
        TargetKernel(
            build_ankey_spec(),
            compiler_registry=build_transport_compiler_registry(),
        )
    )

    result = normalizer.from_status(401)

    assert result.fault_kind == "AUTH"
    assert result.error_code == SystemErrorCode.AUTH_UNAUTHORIZED


def test_from_error_code_maps_network_error_to_transient() -> None:
    normalizer = TargetErrorNormalizer(
        TargetKernel(
            build_ankey_spec(),
            compiler_registry=build_transport_compiler_registry(),
        )
    )

    result = normalizer.from_error_code("NETWORK_ERROR")

    assert result.fault_kind == "TRANSIENT"
    assert result.error_code == SystemErrorCode.INFRA_UNAVAILABLE


def test_from_status_or_code_prefers_error_code() -> None:
    normalizer = TargetErrorNormalizer(
        TargetKernel(
            build_ankey_spec(),
            compiler_registry=build_transport_compiler_registry(),
        )
    )

    result = normalizer.from_status_or_code(status_code=401, error_code="NETWORK_ERROR")

    assert result.fault_kind == "TRANSIENT"
    assert result.error_code == SystemErrorCode.INFRA_UNAVAILABLE
