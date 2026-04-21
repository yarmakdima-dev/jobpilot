Input: profile_json, cv_text, role_title, jd_text, interview_stage

Use the full profile_json.

Output JSON only:
{
  "brief": ["string"],  // exactly 10 bullets from snapshot + strategy + outside_in
  "insider_language": [
    {"phrase": "string", "safe_to_use": true|false, "reason": "string"}
  ],
  "likely_questions": [
    {"question": "string", "category": "behavioral|strategic|role|culture", "stage_fit": "string"}
  ],  // 10 questions calibrated to interview_stage
  "stories": [
    {"label": "string", "situation": "string", "task": "string", "action": "string", "result": "string"}
  ],  // 4-5 STAR stories, 4 sentences max per field
  "questions_to_ask": [
    {"question": "string", "source_field": "string"}  // 5 total: 2 from risk.open_questions, 2 role/team, 1 90-day success
  ],
  "red_flags_to_probe": [
    {"concern": "string", "indirect_phrasing": "string"}
  ]
}