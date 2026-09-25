from modules.research.models import KeyFact, Research, Source
from modules.research.validation import validate_research


def research_with_fact(**overrides):
    return Research(
        topic="Why do cats purr?",
        category="Science",
        core_question="Why do cats purr?",
        short_answer="Cats purr for several reasons.",
        key_facts=[KeyFact(
            fact="Cats purr during some social situations.",
            importance="high",
            confidence="high",
            sources=overrides.get("sources", ["source_001"]),
        )],
        sources=overrides.get("source_list", [Source(
            id="source_001",
            title="A source",
            url="https://example.com/cats",
            publisher="Example",
            relevance="Supports the claim.",
            tier="2",
            source_type="journalism",
        )]),
    )


def test_validation_passes_when_important_claims_have_known_sources():
    report = validate_research(research_with_fact())
    assert report.status == "PASS"
    assert report.claims[0].status == "PASS"


def test_validation_fails_when_important_claim_has_no_source():
    report = validate_research(research_with_fact(sources=[]))
    assert report.status == "FAIL"
    assert "no source" in report.claims[0].issues[0].casefold()


def test_validation_reviews_low_confidence_claims():
    research = research_with_fact()
    research.key_facts[0].confidence = "low"
    report = validate_research(research)
    assert report.status == "REVIEW"
    assert any("cautious wording" in issue for issue in report.issues)


def test_validation_flags_potentially_contradictory_claims_for_review():
    research = research_with_fact()
    research.key_facts.append(KeyFact(
        fact="Cats do not purr during some social situations.",
        importance="medium",
        confidence="medium",
        sources=["source_001"],
    ))
    report = validate_research(research)
    assert report.status == "REVIEW"
    assert report.contradictions
