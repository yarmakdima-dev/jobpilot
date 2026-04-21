Input: profile_json, cv_text, role_title, jd_text, lead_source

Use only these profile fields:
- strategy.stated_priorities
- strategy.recent_moves
- outside_in.press_themes
- insider_signal.self_description_quotes
- insider_signal.communication_tone

Output JSON only:
{
  "letter": "string",  // 250-350 words, no headers, no bullets, no em-dash overuse
  "alternative_openings": ["string", "string", "string"],
  "anchor_used": {"field": "string", "value": "string"}  // which profile fact anchored the opening
}

Voice: reflective, direct, specific. No "passionate about," "excited to," "I believe."
Structure: opening anchored to a real strategy or press theme / why-me with 2-3 CV-specific connections / optional why-them from insider_signal if honest / one-sentence close.