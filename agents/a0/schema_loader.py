"""Convert company_profile_schema_v0_2.json into a Gemini-compatible responseSchema.

Gemini's structured output accepts a subset of JSON Schema:
  - type: string | number | integer | boolean | array | object
  - properties, items, required
  - enum, nullable
  - No $ref, no definitions, no anyOf/oneOf

This module defines the schema directly as a Python dict rather than trying to
parse the documentation-style company_profile_schema.json at runtime.  If the
canonical schema changes, update both files and bump the version comment below.

Schema version: company_profile_schema v0.2 (2026-04-21)
"""

from __future__ import annotations

# ── Leader entry sub-schema (reused for CEO, co-founders, C-suite, board) ─────

_WAR_POSITION = {
    "type": "object",
    "nullable": True,
    "properties": {
        "applies": {"type": "boolean", "nullable": True},
        "value": {
            "type": "string",
            "nullable": True,
            "enum": [
                "explicit_anti_war",
                "explicit_pro_war",
                "accommodative",
                "silent",
                "not_researched",
            ],
        },
        "evidence": {"type": "string", "nullable": True},
        "research_scope": {"type": "string", "nullable": True},
        "confidence": {
            "type": "string",
            "nullable": True,
            "enum": ["high", "medium", "low"],
        },
    },
    "required": ["applies", "value", "evidence", "research_scope", "confidence"],
}

_PARALLEL_BUSINESS = {
    "type": "object",
    "nullable": True,
    "properties": {
        "present": {"type": "boolean"},
        "businesses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "jurisdiction": {"type": "string"},
                    "active": {"type": "boolean"},
                    "overlap_risk": {"type": "string", "nullable": True},
                    "carve_out_escalation": {"type": "boolean"},
                },
                "required": [
                    "name",
                    "role",
                    "jurisdiction",
                    "active",
                    "carve_out_escalation",
                ],
            },
        },
    },
    "required": ["present", "businesses"],
}

_LEADER_ENTRY = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "title": {"type": "string"},
        "origin": {"type": "string", "nullable": True},
        "current_base": {"type": "string", "nullable": True},
        "background": {"type": "string", "nullable": True},
        "public_voice_signal": {"type": "string", "nullable": True},
        "war_position": _WAR_POSITION,
        "parallel_business_flag": _PARALLEL_BUSINESS,
        "concentration_risk_notes": {"type": "string", "nullable": True},
    },
    "required": ["name", "title"],
}

# ── Judgment-call item ─────────────────────────────────────────────────────────

_JUDGMENT_CALL_ITEM = {
    "type": "object",
    "properties": {
        "gate_id": {"type": "string"},
        "reason": {"type": "string"},
        "signals_pro": {"type": "array", "items": {"type": "string"}},
        "signals_con": {"type": "array", "items": {"type": "string"}},
        "recommended_probes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["gate_id", "reason", "signals_pro", "signals_con", "recommended_probes"],
}

# ── Full company profile schema ────────────────────────────────────────────────

GEMINI_COMPANY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        # ── Metadata ──────────────────────────────────────────────────────────
        "instance_meta": {
            "type": "object",
            "properties": {
                "generated": {"type": "string"},
                "target_role": {"type": "string"},
                "role_url": {"type": "string"},
                "research_depth": {
                    "type": "string",
                    "enum": ["light", "medium", "heavy"],
                },
                "researcher": {"type": "string"},
                "confidence_notes": {"type": "string"},
            },
            "required": [
                "generated",
                "target_role",
                "role_url",
                "research_depth",
                "researcher",
                "confidence_notes",
            ],
        },
        # ── Name confusion check ──────────────────────────────────────────────
        "name_confusion_check": {
            "type": "object",
            "properties": {
                "none_found": {"type": "boolean"},
                "similar_names_found": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "domain": {"type": "string"},
                            "distinguishing_facts": {"type": "string"},
                            "contamination_risk": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                            "notes": {"type": "string"},
                        },
                        "required": [
                            "name",
                            "domain",
                            "distinguishing_facts",
                            "contamination_risk",
                            "notes",
                        ],
                    },
                },
            },
            "required": ["none_found", "similar_names_found"],
        },
        # ── Snapshot ──────────────────────────────────────────────────────────
        "snapshot": {
            "type": "object",
            "properties": {
                "legal_name": {"type": "string"},
                "dba": {"type": "string", "nullable": True},
                "domain": {"type": "string"},
                "secondary_domains": {"type": "array", "items": {"type": "string"}},
                "founded": {"type": "string", "nullable": True},
                "hq": {"type": "string"},
                "primary_market": {"type": "string"},
                "sector": {"type": "string"},
                "sub_sector": {"type": "string"},
                "headcount_estimate": {"type": "string", "nullable": True},
                "funding_stage": {"type": "string", "nullable": True},
                "profitability_claim": {"type": "string", "nullable": True},
            },
            "required": [
                "legal_name",
                "domain",
                "hq",
                "primary_market",
                "sector",
                "sub_sector",
                "secondary_domains",
            ],
        },
        # ── Business model ────────────────────────────────────────────────────
        "business_model": {
            "type": "object",
            "properties": {
                "revenue_model": {"type": "string"},
                "pricing": {"type": "string", "nullable": True},
                "core_services": {"type": "array", "items": {"type": "string"}},
                "structure": {"type": "string", "nullable": True},
                "customer_base_size_claim": {"type": "string", "nullable": True},
                "revenue_claim": {"type": "string", "nullable": True},
                "customer_satisfaction_signals": {"type": "string", "nullable": True},
            },
            "required": ["revenue_model", "core_services"],
        },
        # ── Strategy ──────────────────────────────────────────────────────────
        "strategy_and_direction": {
            "type": "object",
            "properties": {
                "stated_mission": {"type": "string", "nullable": True},
                "growth_vector": {"type": "string", "nullable": True},
                "recent_moves": {"type": "array", "items": {"type": "string"}},
                "strategic_bets": {"type": "array", "items": {"type": "string"}},
                "tam_claim": {"type": "string", "nullable": True},
            },
            "required": ["recent_moves", "strategic_bets"],
        },
        # ── Leadership ────────────────────────────────────────────────────────
        "leadership": {
            "type": "object",
            "properties": {
                "ceo": _LEADER_ENTRY,
                "co_founders": {"type": "array", "items": _LEADER_ENTRY},
                "c_suite": {"type": "array", "items": _LEADER_ENTRY},
                "board": {"type": "array", "items": _LEADER_ENTRY},
                "advisors_referenced_in_role": {
                    "type": "array",
                    "items": _LEADER_ENTRY,
                },
                "leadership_pattern_observations": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["leadership_pattern_observations"],
        },
        # ── Market view ───────────────────────────────────────────────────────
        "market_view_outside_in": {
            "type": "object",
            "properties": {
                "competitive_set": {"type": "array", "items": {"type": "string"}},
                "market_regulatory_context": {"type": "string", "nullable": True},
                "macro_tailwinds": {"type": "array", "items": {"type": "string"}},
                "macro_headwinds": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "competitive_set",
                "macro_tailwinds",
                "macro_headwinds",
            ],
        },
        # ── Insider signal ────────────────────────────────────────────────────
        "insider_signal_self_description": {
            "type": "object",
            "properties": {
                "jd_language_excerpts": {"type": "array", "items": {"type": "string"}},
                "ceo_recent_public_voice": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "dissonance_flags": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "jd_language_excerpts",
                "ceo_recent_public_voice",
                "dissonance_flags",
            ],
        },
        # ── Hiring signal ─────────────────────────────────────────────────────
        "hiring_signal": {
            "type": "object",
            "properties": {
                "role_seniority": {"type": "string"},
                "comp_range": {"type": "string", "nullable": True},
                "location_policy": {"type": "string"},
                "location_fit_for_user": {"type": "string"},
                "mandate_tier": {
                    "type": "string",
                    "nullable": True,
                    "enum": ["1", "2", "3"],
                },
                "hand_off_test_status": {"type": "string", "nullable": True},
                "red_flags_in_jd": {"type": "array", "items": {"type": "string"}},
                "green_flags_in_jd": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "role_seniority",
                "location_policy",
                "location_fit_for_user",
                "red_flags_in_jd",
                "green_flags_in_jd",
            ],
        },
        # ── Risks ─────────────────────────────────────────────────────────────
        "risks_and_open_questions": {
            "type": "object",
            "properties": {
                "regulatory_risk": {
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                        },
                        "notes": {"type": "string"},
                    },
                    "required": ["level", "notes"],
                },
                "litigation_risk": {
                    "type": "object",
                    "properties": {
                        "level": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                        },
                        "active_cases": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "case": {"type": "string"},
                                    "type": {"type": "string"},
                                    "status": {"type": "string"},
                                    "materiality": {"type": "string"},
                                },
                                "required": ["case", "type", "status", "materiality"],
                            },
                        },
                    },
                    "required": ["level", "active_cases"],
                },
                "governance_flags": {"type": "array", "items": {"type": "string"}},
                "domain_exclusion_check": {"type": "string"},
            },
            "required": [
                "regulatory_risk",
                "litigation_risk",
                "governance_flags",
                "domain_exclusion_check",
            ],
        },
        # ── Judgment calls ────────────────────────────────────────────────────
        "gate_needs_judgment_call": {
            "type": "object",
            "properties": {
                "blocked": {"type": "boolean"},
                "items": {"type": "array", "items": _JUDGMENT_CALL_ITEM},
            },
            "required": ["blocked", "items"],
        },
        # ── Source index ──────────────────────────────────────────────────────
        "source_index": {
            "type": "object",
            "properties": {
                "S1": {"type": "string", "nullable": True},
                "S2": {"type": "string", "nullable": True},
                "S3": {"type": "string", "nullable": True},
                "S4": {"type": "string", "nullable": True},
                "S5": {"type": "string", "nullable": True},
                "S6": {"type": "string", "nullable": True},
                "S7": {"type": "string", "nullable": True},
                "S8": {"type": "string", "nullable": True},
            },
        },
    },
    "required": [
        "instance_meta",
        "name_confusion_check",
        "snapshot",
        "business_model",
        "strategy_and_direction",
        "leadership",
        "market_view_outside_in",
        "insider_signal_self_description",
        "hiring_signal",
        "risks_and_open_questions",
        "gate_needs_judgment_call",
        "source_index",
    ],
}


def get_gemini_schema() -> dict:
    """Return the Gemini-compatible responseSchema for company profiles."""
    return GEMINI_COMPANY_SCHEMA
