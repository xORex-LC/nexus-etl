from __future__ import annotations

from connector.domain.planning.rules import LinkFieldRule, LinkKeyRule, LinkRules


def build_link_rules() -> LinkRules:
    return LinkRules(
        fields=(
            LinkFieldRule(
                field="manager_id",
                target_dataset="employees",
                resolve_keys=(
                    LinkKeyRule(name="match_key", field="manager_id"),
                ),
                dedup_rules=(
                    ("organization_id",),
                ),
                target_id_field="_ouid",
                coerce="int",
            ),
            LinkFieldRule(
                field="organization_id",
                target_dataset="organizations",
                resolve_keys=(
                    LinkKeyRule(name="name", field="organization_id"),
                ),
                dedup_rules=(
                    ("code",),
                ),
                target_id_field="_ouid",
                coerce="int",
            ),
        ),
    )
