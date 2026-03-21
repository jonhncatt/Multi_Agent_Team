from __future__ import annotations

import re
from typing import Any


def citation_kind(citation: dict[str, Any]) -> str:
    kind = str(citation.get("kind") or "").strip().lower()
    if kind in {"evidence", "candidate"}:
        return kind
    return "candidate" if str(citation.get("tool") or "").strip() == "search_web" else "evidence"


def citation_strength(citation: dict[str, Any]) -> int:
    if citation_kind(citation) != "evidence":
        return 0
    confidence = str(citation.get("confidence") or "medium").strip().lower()
    return {"high": 3, "medium": 2, "low": 1}.get(confidence, 2)


def extract_answer_summary(agent: Any, final_text: str) -> str:
    cleaned = " ".join(str(final_text or "").strip().split())
    if not cleaned:
        return ""
    sentence = re.split(r"(?<=[。.!?！？])\s+", cleaned, maxsplit=1)[0]
    return agent._shorten(sentence or cleaned, 220)


def split_claim_candidates(agent: Any, final_text: str) -> list[str]:
    raw = str(final_text or "").strip()
    if not raw:
        return []
    normalized = raw.replace("\r\n", "\n")
    candidates: list[str] = []
    for line in normalized.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if not line:
            continue
        parts = [item.strip() for item in re.split(r"(?<=[。.!?！？])\s+", line) if item.strip()]
        candidates.extend(parts or [line])
        if len(candidates) >= 8:
            break
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        compact = " ".join(item.split())
        if len(compact) < 8:
            continue
        key = compact.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(agent._shorten(compact, 220))
        if len(out) >= 5:
            break
    return out


def normalize_claim_record(
    agent: Any,
    *,
    statement: str,
    citation_ids: list[str],
    confidence: str,
    status: str,
    citations_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    linked_ids = [cid for cid in citation_ids if cid in citations_by_id][:4]
    linked_citations = [citations_by_id[cid] for cid in linked_ids]
    evidence_strength = max((citation_strength(item) for item in linked_citations), default=0)
    has_evidence = any(citation_kind(item) == "evidence" for item in linked_citations)

    normalized_confidence = confidence if confidence in {"high", "medium", "low"} else "medium"
    normalized_status = status if status in {"supported", "partially_supported", "needs_review"} else "needs_review"

    if not linked_ids:
        normalized_confidence = "low"
        normalized_status = "needs_review"
    elif not has_evidence:
        normalized_confidence = "low"
        normalized_status = "needs_review"
    elif evidence_strength <= 1:
        if normalized_confidence == "high":
            normalized_confidence = "medium"
        if normalized_status == "supported":
            normalized_status = "partially_supported"

    return {
        "statement": agent._shorten(statement, 220),
        "citation_ids": linked_ids,
        "confidence": normalized_confidence,
        "status": normalized_status,
    }


def augment_bundle_warnings(agent: Any, *, warnings: list[str], citations: list[dict[str, Any]]) -> list[str]:
    normalized = agent._normalize_string_list(warnings, limit=5, item_limit=220)
    if not citations:
        return normalized
    if all(citation_kind(item) == "candidate" for item in citations if isinstance(item, dict)):
        normalized = agent._normalize_string_list(
            ["当前来源仅为搜索候选链接，尚未抓取正文，结论需复核。", *normalized],
            limit=5,
            item_limit=220,
        )
    return normalized


def strip_answer_bundle_meta(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": str(bundle.get("summary") or "").strip(),
        "claims": list(bundle.get("claims") or []),
        "citations": list(bundle.get("citations") or []),
        "warnings": list(bundle.get("warnings") or []),
    }


def fallback_answer_bundle(
    agent: Any,
    *,
    final_text: str,
    citations: list[dict[str, Any]],
    reviewer_brief: Any,
    conflict_brief: Any = None,
) -> dict[str, Any]:
    reviewer_payload = agent._role_payload_dict(reviewer_brief)
    conflict_payload = agent._role_payload_dict(conflict_brief)
    summary = extract_answer_summary(agent, final_text)
    citations_by_id = {
        str(item.get("id") or "").strip(): item for item in citations if str(item.get("id") or "").strip()
    }
    evidence_ids = [cid for cid, item in citations_by_id.items() if citation_kind(item) == "evidence"]
    candidate_ids = [cid for cid, item in citations_by_id.items() if citation_kind(item) == "candidate"]
    claims: list[dict[str, Any]] = []
    for statement in split_claim_candidates(agent, final_text)[:5]:
        linked_ids = evidence_ids[: min(2, len(evidence_ids))] or candidate_ids[: min(2, len(candidate_ids))]
        claims.append(
            normalize_claim_record(
                agent,
                statement=statement,
                citation_ids=linked_ids,
                confidence="medium" if evidence_ids else "low",
                status="supported" if evidence_ids else "needs_review",
                citations_by_id=citations_by_id,
            )
        )
    warnings = agent._normalize_string_list(
        list(reviewer_payload.get("risks") or [])
        + list(reviewer_payload.get("followups") or [])
        + list(conflict_payload.get("concerns") or []),
        limit=5,
        item_limit=220,
    )
    warnings = augment_bundle_warnings(agent, warnings=warnings, citations=citations)
    return {
        "summary": summary,
        "claims": claims,
        "citations": citations,
        "warnings": warnings,
        "usage": agent._empty_usage(),
        "effective_model": "",
        "notes": [],
    }
