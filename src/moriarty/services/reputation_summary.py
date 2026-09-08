from __future__ import annotations

from typing import Any
from collections import Counter,defaultdict
import re

from moriarty.domain.models import ProviderResult, ProviderStatus

_SCORES = {
    "dangerous": 100,
    "unsafe": 95,
    "warning": 85,
    "spam": 85,
    "negative": 80,
    "harassing": 75,
    "reported": 60,
    "neutral": 50,
    "positive": 15,
    "safe": 5,
}


def summarize_reputation(results: tuple[ProviderResult, ...]) -> dict[str, Any]:
    sources = tuple(result for result in results if result.provider.startswith("reputation:"))
    applicable = []
    found = []
    labels: list[dict[str, Any]] = []
    weighted_total = 0.0
    total_weight = 0.0

    for result in sources:
        data = result.data or {}
        lookup_status = str(data.get("status") or "")
        if result.status is ProviderStatus.SUCCESS and lookup_status != "not_applicable":
            applicable.append(result.provider)
        if result.status is not ProviderStatus.SUCCESS or lookup_status != "found":
            continue
        found.append(result.provider)
        level = str(data.get("security_level") or "Reported")
        evidence_confidence = max(
            (item.confidence or 0.5 for item in result.evidence), default=0.5
        )
        score = _SCORES.get(level.lower(), 50)
        weighted_total += score * evidence_confidence
        total_weight += evidence_confidence
        labels.append(
            {
                "provider": result.provider,
                "label": level,
                "confidence": round(evidence_confidence, 2),
            }
        )

    risk_score = round(weighted_total / total_weight) if total_weight else None
    if risk_score is None:
        verdict = "insufficient_data"
    elif risk_score >= 80:
        verdict = "high_risk"
    elif risk_score >= 60:
        verdict = "suspicious"
    elif risk_score >= 40:
        verdict = "mixed_or_unverified"
    else:
        verdict = "low_risk"

    values = {item["label"].lower() for item in labels}
    negative = bool(values & {"dangerous", "unsafe", "warning", "spam", "negative", "harassing"})
    positive = bool(values & {"safe", "positive"})
    patterns=_patterns(sources)
    return {
        "verdict": verdict,
        "risk_score": risk_score,
        "queried_sources": len(sources),
        "applicable_sources": len(applicable),
        "found_sources": len(found),
        "conflicting_signals": negative and positive,
        "signals": labels,
        "note": "Community signals are not proof of caller identity or intent.",
        "campaign_clusters":patterns["clusters"],
        "timeline":patterns["timeline"],
        "related_number_mentions":patterns["related_numbers"],
    }


def _patterns(sources:tuple[ProviderResult,...])->dict[str,Any]:
    category_sources=defaultdict(set);category_counts=Counter();dates=Counter();numbers=Counter()
    keywords={"telemarketing":("sales","marketing","offer","contract"),"robocall":("recorded message","robot","automated"),"impersonation":("pretend","impersonat","claiming to be"),"debt_collection":("debt","collection","payment due"),"delivery":("parcel","delivery","courier")}
    for result in sources:
        if result.status is not ProviderStatus.SUCCESS or not result.data:continue
        data=result.data;categories=data.get("categories") or {}
        if isinstance(categories,dict):
            for category,count in categories.items():
                label=str(category).strip().lower().replace(" ","_");amount=int(count) if str(count).isdigit() else 1
                category_counts[label]+=amount;category_sources[label].add(result.provider)
        for comment in data.get("comments") or ():
            lowered=str(comment).lower()
            for label,hints in keywords.items():
                if any(hint in lowered for hint in hints):category_counts[label]+=1;category_sources[label].add(result.provider)
            for value in re.findall(r"\b(?:20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/20\d{2})\b",str(comment)):dates[value]+=1
            for value in re.findall(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)",str(comment)):numbers[" ".join(value.split())]+=1
    clusters=tuple({"category":label,"signal_count":count,"source_count":len(category_sources[label]),"sources":tuple(sorted(category_sources[label]))} for label,count in category_counts.most_common())
    timeline=tuple({"date":date,"report_mentions":count} for date,count in sorted(dates.items()))
    related=tuple({"raw":value,"mention_count":count,"relationship":"co_mentioned_only"} for value,count in numbers.most_common())
    return {"clusters":clusters,"timeline":timeline,"related_numbers":related}
