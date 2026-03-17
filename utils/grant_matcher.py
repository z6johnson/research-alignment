import json
import os
import re

from litellm import completion


def _get_model():
    model = os.getenv("LITELLM_MODEL", "api-gpt-oss-120b")
    if "/" not in model:
        model = f"openai/{model}"
    return model


def _call_llm(system_prompt, user_prompt, max_tokens=2000, temperature=0.1):
    """Make a LiteLLM completion call and return the content string."""
    response = completion(
        model=_get_model(),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
        api_key=os.getenv("LITELLM_API_KEY"),
        api_base=os.getenv("LITELLM_API_BASE"),
    )
    return response.choices[0].message.content


def _parse_json_response(text):
    """Parse JSON from an LLM response, handling markdown fences."""
    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting from markdown code fence
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding the first { or [ and matching to last } or ]
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError("Could not parse JSON from LLM response")


EXTRACT_SYSTEM_PROMPT = """\
You are an expert research grant analyst. You will be given the text of a \
grant opportunity document. Extract the requirements and produce a structured \
summary in JSON format. Focus on:

1. A brief summary of the grant opportunity (2-3 sentences capturing the \
purpose, scope, and what the funder is looking for)
2. Investigator requirements — what expertise, qualifications, and roles \
the grant describes (use the grant's own terminology for roles; do not \
impose labels like "PI" or "Co-PI" unless the grant explicitly uses them)
3. Key personnel or team composition needs
4. Required expertise areas and disciplines
5. Preferred qualifications (degrees, experience level, specific skills)
6. Any eligibility constraints (career stage, institution type, etc.)

Return ONLY valid JSON with this structure:
{
  "grant_title": "string or null",
  "funding_agency": "string or null",
  "grant_summary": "A 2-3 sentence summary of the grant opportunity, its \
purpose, and what it seeks to fund.",
  "investigator_requirements": [
    {
      "role": "role as described in the grant (e.g., Lead Investigator, \
Project Director, or simply Investigator)",
      "expertise_areas": ["list of required expertise domains"],
      "qualifications": ["list of degree/experience requirements"],
      "constraints": ["any eligibility constraints"]
    }
  ],
  "overall_research_themes": ["list of broad research themes in the grant"]
}

If investigator roles are not explicitly defined, create a single entry with \
role "Investigator" containing all requirements. \
Do NOT invent requirements that are not stated or clearly implied."""

MATCH_SYSTEM_PROMPT = """\
You are a research collaboration matchmaker for UC San Diego. You will receive:
1. Extracted requirements from a grant opportunity
2. A list of faculty members with their research interests

Your task: Rank the faculty by how well their research interests align with \
the grant requirements. For each match, evaluate these dimensions:

- expertise_alignment (0-100): How closely the faculty member's research \
interests and expertise match the grant's required research areas
- methodological_fit (0-100): How well the researcher's methods align with \
the methodological needs of the opportunity
- track_record (0-100): Strength of relevant publication and funding history \
relative to the opportunity's scope

The overall match_score should reflect a weighted synthesis of these \
dimensions (expertise alignment is most important, followed by \
methodological fit, then track record).

Do NOT assign or recommend investigator roles (PI, Co-PI, etc.). The \
purpose of this tool is to identify aligned faculty — role decisions belong \
to the research team.

Return ONLY valid JSON as an array of matches, ordered by relevance (best \
first). Include AT MOST 15 matches. Only include faculty with meaningful \
alignment (score >= 40). Each match object:
{
  "faculty_id": <integer index from the faculty list>,
  "match_score": <integer 0-100>,
  "expertise_alignment": <integer 0-100>,
  "methodological_fit": <integer 0-100>,
  "track_record": <integer 0-100>,
  "match_reasoning": "2-3 sentence explanation of why this faculty member \
is a strong match, referencing specific research interests and grant \
requirements."
}"""


def extract_grant_requirements(grant_text):
    """Call #1: Extract investigator requirements from grant text."""
    user_prompt = (
        "Here is the grant opportunity document text:\n\n"
        "---\n"
        f"{grant_text}\n"
        "---\n\n"
        "Extract the requirements and summary as specified."
    )
    raw = _call_llm(EXTRACT_SYSTEM_PROMPT, user_prompt, max_tokens=2000, temperature=0.1)
    return _parse_json_response(raw)


def match_faculty(requirements, faculty_with_interests):
    """Call #2: Match faculty against extracted grant requirements."""
    # Build compact faculty summary
    lines = []
    for idx, f in enumerate(faculty_with_interests):
        degrees = ", ".join(f.get("degrees") or [])
        name = f"{f['first_name']} {f['last_name']}"
        interests = (
            f.get("_effective_interests")
            or f.get("research_interests_enriched")
            or f.get("research_interests")
            or "N/A"
        )
        summary = f"ID:{idx} | {name}, {degrees} | {f['title']} | Interests: {interests}"
        extras = []
        if f.get("expertise_keywords"):
            extras.append(f"Keywords: {', '.join(f['expertise_keywords'])}")
        if f.get("funded_grants"):
            extras.append(f"Grants: {len(f['funded_grants'])} funded")
        if f.get("h_index"):
            extras.append(f"h-index: {f['h_index']}")
        if extras:
            summary += f" | {' | '.join(extras)}"
        lines.append(summary)
    faculty_summary = "\n".join(lines)

    user_prompt = (
        "## Grant Requirements\n"
        f"{json.dumps(requirements, indent=2)}\n\n"
        "## Faculty Directory\n"
        f"{faculty_summary}\n\n"
        "Rank the best-matching faculty for this grant."
    )
    raw = _call_llm(MATCH_SYSTEM_PROMPT, user_prompt, max_tokens=4000, temperature=0.2)
    matches = _parse_json_response(raw)

    # Enrich matches with full faculty data
    enriched = []
    for m in matches:
        fid = m.get("faculty_id")
        if fid is None or fid < 0 or fid >= len(faculty_with_interests):
            continue
        faculty = faculty_with_interests[fid]
        enriched.append(
            {
                "rank": len(enriched) + 1,
                "first_name": faculty["first_name"],
                "last_name": faculty["last_name"],
                "degrees": faculty.get("degrees", []),
                "title": faculty.get("title", ""),
                "email": faculty.get("email"),
                "research_interests": faculty.get("research_interests", ""),
                "match_score": m.get("match_score", 0),
                "expertise_alignment": m.get("expertise_alignment", 0),
                "methodological_fit": m.get("methodological_fit", 0),
                "track_record": m.get("track_record", 0),
                "match_reasoning": m.get("match_reasoning", ""),
            }
        )

    # Sort by score descending
    enriched.sort(key=lambda x: x["match_score"], reverse=True)
    for i, m in enumerate(enriched):
        m["rank"] = i + 1

    return enriched


def process_grant(grant_text, faculty_data):
    """Coordinate the full grant matching pipeline.

    Args:
        grant_text: Extracted text from the grant document.
        faculty_data: List of faculty dicts from faculty.json.

    Returns:
        Dict with grant_summary, matches, and metadata.
    """
    requirements = extract_grant_requirements(grant_text)

    faculty_with_interests = [
        f for f in faculty_data if f.get("research_interests")
    ]
    faculty_without = [
        f for f in faculty_data if not f.get("research_interests")
    ]

    matches = match_faculty(requirements, faculty_with_interests)

    return {
        "grant_summary": requirements,
        "matches": matches,
        "faculty_without_interests_count": len(faculty_without),
        "total_faculty_considered": len(faculty_with_interests),
    }
