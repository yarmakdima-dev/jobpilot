Input: profile_json, cv_text, role_title, jd_text

Use only these profile fields:
- strategy.stated_priorities
- strategy.recent_moves
- insider_signal.self_description_quotes
- insider_signal.stated_values
- hiring_signal.recurring_jd_language
- operator_fit.addressable_problems

Output JSON only, this schema:
{
  "relevance_briefing": ["string"],  // 5-8 bullets, highest-signal points from above fields
  "cv_edits": [
    {"role": "string", "original": "string", "proposed": "string", "reason": "string"}
  ],
  "cuts": [{"role": "string", "bullet": "string", "reason": "string"}],
  "gaps": ["string"]  // what the company wants that the CV does not show
}

Rules:
- Do not fabricate experience. If a gap exists, list it in "gaps".
- "proposed" bullets must be in the candidate's existing voice: short, declarative, numbers where available.
- Mirror company language from self_description_quotes only where honest.