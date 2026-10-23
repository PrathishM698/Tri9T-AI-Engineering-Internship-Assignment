"""LLM client with strict output validation and deterministic offline fallback."""
import json
import httpx
from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from .schemas import GenerationOutput

SYSTEM_PROMPT = """You are a QA engineer for a fictional home blood pressure monitor. Create 3 to 5 concrete, executable software/device test case ideas ONLY from the supplied source text. Do not invent numeric limits, error codes, timings, or requirements. If the text is ambiguous, state the uncertainty in the requirement field. Return only JSON: {\"test_cases\":[{\"title\":string,\"requirement\":string,\"preconditions\":[string],\"steps\":[string],\"expected_result\":string,\"risk\":\"low\"|\"medium\"|\"high\"}]}. Each case must include actionable steps and an observable expected result."""

def fallback_cases(source_text: str):
    excerpt = " ".join(source_text.split())[:500] or "No source text supplied."
    return {"test_cases": [
        {"title":"Verify requirement is represented", "requirement":f"Source requirement to verify: {excerpt}", "preconditions":["Test environment is configured according to the approved device instructions."], "steps":["Identify the relevant device behavior described by the selected source text.","Execute the behavior using the approved procedure.","Record the observed response and compare it with the source requirement."], "expected_result":"The observed behavior matches the selected source text; any ambiguity is recorded for engineering review.", "risk":"medium"},
        {"title":"Verify behavior is repeatable", "requirement":f"Repeat the behavior described in: {excerpt}", "preconditions":["The device is in the documented starting state."], "steps":["Run the documented procedure once and record the result.","Restore the documented starting state.","Repeat the same procedure and compare results."], "expected_result":"Repeated runs produce behavior consistent with the requirement; deviations are logged.", "risk":"medium"},
        {"title":"Verify unsupported or ambiguous conditions are surfaced", "requirement":f"Check interpretation of the selected source: {excerpt}", "preconditions":["The selected requirement and its source version are available to the tester."], "steps":["Review the selected text for missing thresholds, undefined states, or unclear wording.","Attempt to derive an executable expected result without adding assumptions.","Flag any unresolved detail for clarification before approving the test."], "expected_result":"The test is executable only where the source supports it; unsupported assumptions are explicitly flagged.", "risk":"high"}
    ]}

async def generate_cases(source_text: str) -> tuple[dict, str]:
    if not LLM_API_KEY:
        validated = GenerationOutput.model_validate(fallback_cases(source_text))
        return validated.model_dump(), "offline_fallback"
    payload = {"model": LLM_MODEL, "temperature": 0.1, "response_format": {"type":"json_object"}, "messages":[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":"Source text:\n"+source_text+"\nReturn JSON only."}]}
    last_error = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(f"{LLM_BASE_URL}/chat/completions", headers={"Authorization":f"Bearer {LLM_API_KEY}","Content-Type":"application/json"}, json=payload)
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
            data = json.loads(raw)
            validated = GenerationOutput.model_validate(data)
            return validated.model_dump(), "llm"
        except Exception as exc:
            last_error = str(exc)
            # Retry once with an explicit repair instruction, preserving source text.
            payload["messages"].append({"role":"user","content":"Your previous response was invalid. Return valid JSON matching the exact schema, with 3 to 5 cases. Do not include markdown fences."})
    # Fail safely instead of storing malformed output as valid generated test cases.
    raise RuntimeError(f"LLM output failed JSON/schema validation after retry: {last_error}")
