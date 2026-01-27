from __future__ import annotations

from connector.infra.cache.cache_spec import CacheSpec, FieldSpec


organizations_cache_spec = CacheSpec(
    dataset="organizations",
    table="organizations",
    primary_key=("_ouid",),
    fields=(
        FieldSpec(name="_ouid", type="int", nullable=False),
        FieldSpec(name="code", type="string", nullable=True),
        FieldSpec(name="name", type="string", nullable=True),
        FieldSpec(name="parent_id", type="int", nullable=True),
        FieldSpec(name="updated_at", type="datetime", nullable=True),
    ),
    indexes=(("parent_id",),),
)
