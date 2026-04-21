You are a research analyst producing a machine-readable company profile.

Target company: {COMPANY_NAME}
Optional context: {OPTIONAL_CONTEXT}
Date: {DATE}

Produce TWO outputs in this exact order, separated by the line `---SPLIT---`.

OUTPUT 1: A single JSON object. No prose before or after. No markdown fences. Valid JSON only. Use this schema exactly. Every field must be present. If a value is unknown, use null (not "unknown", not an empty string). Arrays may be empty []. Strings must be factual and short — no marketing language, no adjectives unless they appear in a direct quote. Dates in ISO format (YYYY-MM-DD or YYYY-MM).

{
  "meta": {
    "company": "string",
    "profile_date": "YYYY-MM-DD",
    "confidence": "high|medium|low"
  },
  "snapshot": {
    "legal_name": "string|null",
    "hq": "string|null",
    "founded": "YYYY|null",
    "employee_count": "integer|null",
    "employee_count_source": "string|null",
    "ownership": "public|private|pe_backed|vc_backed|subsidiary|null",
    "ticker": "string|null",
    "latest_revenue_usd": "integer|null",
    "latest_revenue_year": "YYYY|null",
    "description_one_line": "string",
    "industry": "string",
    "sub_industry": "string|null",
    "geographies": ["string"]
  },
  "business_model": {
    "revenue_streams": ["string"],
    "pricing_model": "string|null",
    "products": ["string"],
    "customer_segments": ["string"],
    "competitors": ["string"],
    "scale_metrics": [{"metric": "string", "value": "string", "as_of": "YYYY-MM|null"}]
  },
  "strategy": {
    "stated_priorities": ["string"],
    "recent_moves": [{"date": "YYYY-MM", "type": "acquisition|divestiture|layoff|restructure|product_launch|market_entry|leadership_change|other", "description": "string", "source_id": "integer"}],
    "public_challenges": ["string"],
    "ai_posture": {
      "public_statements": ["string"],
      "shipped_products": ["string"],
      "ai_hiring_signal": "aggressive|moderate|minimal|none|unknown"
    }
  },
  "leadership": {
    "ceo": {"name": "string|null", "background_one_line": "string|null", "tenure_start": "YYYY-MM|null"},
    "c_suite": [{"name": "string", "role": "string", "background_one_line": "string"}],
    "board_notable": [{"name": "string", "affiliation": "string"}],
    "recent_changes": [{"date": "YYYY-MM", "description": "string"}]
  },
  "outside_in": {
    "analyst_framing": ["string"],
    "press_themes": ["string"],
    "review_themes_positive": ["string"],
    "review_themes_negative": ["string"],
    "review_sources": ["g2|gartner_peer|trustpilot|glassdoor|other"],
    "recent_pr_wins": ["string"],
    "recent_pr_problems": ["string"]
  },
  "insider_signal": {
    "self_description_quotes": [{"quote": "string", "source": "homepage|about|careers|blog|linkedin"}],
    "stated_values": ["string"],
    "communication_tone": {
      "formal_casual": "formal|neutral|casual|null",
      "bold_cautious": "bold|neutral|cautious|null",
      "product_led_people_led": "product|balanced|people|null",
      "specific_abstract": "specific|mixed|abstract|null"
    },
    "what_gets_celebrated": ["string"],
    "employee_sentiment_positive": ["string"],
    "employee_sentiment_negative": ["string"]
  },
  "hiring_signal": {
    "active_role_categories": [{"category": "string", "volume": "high|medium|low"}],
    "recurring_jd_language": ["string"],
    "interview_process_themes": ["string"],
    "comp_bands": [{"role": "string", "range_usd": "string", "source": "string"}]
  },
  "operator_fit": {
    "plausible_functions": ["string"],
    "senior_hiring_functions": ["string"],
    "addressable_problems": ["string"]
  },
  "risk": {
    "red_flags": ["string"],
    "open_questions": ["string"]
  },
  "sources": [{"id": "integer", "url": "string", "type": "primary|secondary", "description": "string"}]
}

---SPLIT---

OUTPUT 2: A human-readable Markdown summary of the JSON above. Maximum 400 words. Use short sections. Do not repeat every field — surface only what a human skimming for 60 seconds needs. End with a "Key open questions" section pulling from risk.open_questions.

Rules:
- Do not invent data. null is always better than a guess.
- Quotes in insider_signal.self_description_quotes must be verbatim from the source.
- Every recent_moves entry must have a source_id pointing to sources[].id.
- Prefer primary sources. If only secondary sources exist for a claim, mark confidence as medium or low in meta.