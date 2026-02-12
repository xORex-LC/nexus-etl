# DSL Core Issues Audit

## Scope
- Audit target: `connector/domain/dsl`
- Focus: scalability, architecture, cleanliness, reuse, readability, consistency, functional coverage
- Status: open issues (to be prioritized and addressed)

## High Priority

1. Silent dropping of DSL spec errors (`extra` keys are ignored)
- Problem: typos/unknown fields in YAML are silently ignored by Pydantic models.
- Impact: configuration mistakes are not detected early; hard-to-debug runtime behavior.
- Evidence:
  - `connector/domain/dsl/specs.py`
  - Example check confirmed unknown keys are ignored in `MappingSpec`.

2. Build options for unknown dataset do not fail
- Problem: `_load_stage_build_options` returns defaults when dataset is absent instead of raising.
- Impact: misconfigured dataset names are not caught, which hides wiring errors.
- Evidence:
  - `connector/domain/dsl/loader.py:416`
  - `connector/domain/dsl/loader.py:428`

3. Compile-policy flags are partially no-op
- Problem: several declared options are not used in compile/runtime flow.
- Impact: false confidence in strict/validation modes.
- Evidence:
  - Declared in `connector/domain/dsl/build_options.py:23-37`
  - No effective usage for:
    - `strict`
    - `fail_on_unknown_ops`
    - `fail_on_schema_warnings`
    - `emit_compile_report`
    - `require_targets_exist_in_sink_spec`

4. No compile-time validation of DSL operations
- Problem: unknown ops are discovered only at runtime in `TransformationEngine.apply`.
- Impact: fail-late behavior on production data.
- Evidence:
  - `connector/domain/dsl/engine.py:60-70`

5. Low diagnostic context for DSL operation failures
- Problem: `DSL_OP_FAILED` stores only exception string, without op name/args/path context.
- Impact: weak observability for массовые runtime errors.
- Evidence:
  - `connector/domain/dsl/engine.py:73-80`

## Medium Priority

6. Monolithic DSL contracts file
- Problem: one large file contains all stage and cache models.
- Impact: reduced readability, higher change-collision risk, harder ownership split.
- Evidence:
  - `connector/domain/dsl/specs.py` (~869 LOC)

7. Loader has too many responsibilities
- Problem: one module handles stage spec loading, cache spec loading, options merge, template expansion.
- Impact: high coupling, difficult testing and extension.
- Evidence:
  - `connector/domain/dsl/loader.py`
  - Stage loaders: `load_*_spec_for_dataset`
  - Cache loaders: `load_cache_*`
  - Options merge: `load_*_build_options*`
  - Enrich template expansion: `_expand_enrich_templates`

8. Fragile repository root resolution
- Problem: root path depends on static `parents[3]`.
- Impact: path breakage risk if package/file layout changes.
- Evidence:
  - `connector/domain/dsl/loader.py:394-397`

9. Ambiguous cache build-options merge for multi-dataset runtime
- Problem: runtime merges overrides from all cache datasets into one options dict.
- Impact: one dataset may unintentionally override another.
- Evidence:
  - `connector/domain/dsl/loader.py:304-319`

10. Inconsistent `on_error` vocabulary across DSL domains
- Problem: transform specs use `warn`, cache specs use `warning`.
- Impact: inconsistency for shared tooling/docs and future common handlers.
- Evidence:
  - Transform: `connector/domain/dsl/specs.py:42`, `:196`, `:255`
  - Cache: `connector/domain/dsl/specs.py:740`, `:797`

11. Operation registry allows silent override
- Problem: `register()` replaces existing op with same name without protection.
- Impact: accidental shadowing of core ops.
- Evidence:
  - `connector/domain/dsl/registry.py:34-35`

12. Hot-path inefficiencies in core ops
- Problem: repeated regex compile/mapping rebuild in per-row ops.
- Impact: throughput degradation on large ETL volumes.
- Evidence:
  - `connector/domain/dsl/ops.py:330` (`re.compile` per call)
  - `connector/domain/dsl/ops.py:428` (rebuild casefold mapping per call)

13. Duplicate model semantics in cache DSL
- Problem: `ValueExprSpec` and `CacheProjectionRuleSpec` duplicate similar source/value/ops/on_error contract.
- Impact: maintenance overhead and divergence risk.
- Evidence:
  - `connector/domain/dsl/specs.py:729`
  - `connector/domain/dsl/specs.py:785`

14. Validation DSL contract exists but is not wired as stage runtime
- Problem: `ValidationSpec` and loader exist, but no active stage runtime wiring path.
- Impact: functional gap between declared DSL capabilities and effective runtime.
- Evidence:
  - `connector/domain/dsl/specs.py:307`
  - `connector/domain/dsl/loader.py:127`
  - No direct runtime stage usage in transform engines.

15. Overloaded public facade in `__init__`
- Problem: one package facade exports both transform and cache DSL APIs in one surface.
- Impact: increased coupling and larger import surface.
- Evidence:
  - `connector/domain/dsl/__init__.py`

## Suggested Execution Order

### P0
- Enforce strict schema for DSL models (forbid unknown keys).
- Fail fast for unknown dataset in build-options loaders.
- Implement compile-time op validation (or explicitly remove no-op flags).

### P1
- Split `specs.py` and `loader.py` by domain boundaries (transform/cache).
- Improve `DSL_OP_FAILED` diagnostics payload.
- Fix multi-dataset cache options merge semantics.

### P2
- Unify `on_error` vocabulary.
- Add registry duplicate protection policy.
- Optimize hot-path ops and remove model duplication in cache DSL.

