"""Configuration-driven editorial profiles for script generation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptProfile:
    profile_id: str
    description: str
    narrative_principles: tuple[str, ...]

    def instructions(self) -> str:
        return "\n".join(f"- {principle}" for principle in self.narrative_principles)


RITZZ_ANCIENT_HUMAN_CURIOSITY = ScriptProfile(
    profile_id="RITZZ_ANCIENT_HUMAN_CURIOSITY",
    description=(
        "Conversational, evidence-led curiosity documentary storytelling "
        "with concrete human experience and an earned payoff."
    ),
    narrative_principles=(
        (
            "Prefer a concrete present-day problem and familiar solution, then connect it "
            "to the same problem in the ancient world when the approved topic and research "
            "support that comparison; never force a modern parallel."
        ),
        (
            "Open a question about how people solved the ancient problem, withhold the full "
            "answer, and make the first investigation begin answering that exact question."
        ),
        (
            "Establish one central mystery, then let each major movement answer one question "
            "while naturally creating or sharpening the next."
        ),
        (
            "Build forward through question, evidence, interpretation, consequence, and reveal "
            "rather than a list of disconnected facts."
        ),
        (
            "Turn supported findings into concrete human situations, choices, constraints, "
            "and visual moments without inventing sensory or historical details."
        ),
        (
            "Anchor important claims in the supplied research and preserve its distinctions "
            "between known, likely, possible, disputed, and unsupported."
        ),
        "Use a myth or common-assumption reversal only when the supplied research supports it.",
        (
            "Vary questions, explanation, evidence, story, and interpretation; avoid repetitive "
            "cliffhangers, formulaic transitions, and excessive rhetorical questions."
        ),
        "End by answering or reframing the opening mystery and explaining why the answer matters.",
        (
            "Keep narration conversational, intelligent, accessible, original, and suitable for "
            "natural spoken delivery; never reproduce reference transcript wording."
        ),
        "Make important beats drawable as simple static scenes while keeping factual accuracy first.",
    ),
)

SCRIPT_PROFILES = {
    RITZZ_ANCIENT_HUMAN_CURIOSITY.profile_id: RITZZ_ANCIENT_HUMAN_CURIOSITY,
}


def get_script_profile(profile_id: str) -> ScriptProfile:
    try:
        return SCRIPT_PROFILES[profile_id]
    except KeyError as exc:
        supported = ", ".join(sorted(SCRIPT_PROFILES))
        raise ValueError(
            f"Unknown script profile {profile_id!r}; configured profiles: {supported}."
        ) from exc
