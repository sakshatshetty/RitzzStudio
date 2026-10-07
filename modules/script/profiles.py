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
            "support that comparison; never force a modern parallel. When a vivid, specific "
            "ancient scene would create a stronger unanswered question than opening with the "
            "modern side, open inside that ancient scene instead and bring in the modern "
            "comparison a beat later; choose the order that earns the strongest open loop for "
            "this topic, not by default or habit."
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
            "and visual moments without inventing sensory or historical details. When the "
            "research supports several connected findings about the same moment or routine, "
            "consider sustaining one continuous concrete scene across them instead of a "
            "separate isolated example per finding."
        ),
        (
            "Anchor important claims in the supplied research and preserve its distinctions "
            "between known, likely, possible, disputed, and unsupported. When the research "
            "itself describes a finding that was doubted, tested, or independently replicated, "
            "consider narrating that scrutiny as part of the evidence rather than only stating "
            "the conclusion; this earns the number or claim instead of asserting it."
        ),
        (
            "Use a myth or common-assumption reversal only when the supplied research supports "
            "it; when natural, phrase it as a prediction the viewer makes and then loses "
            "(contrast two concrete details and ask which belongs to which) rather than only "
            "stating the correction directly."
        ),
        (
            "When the research provides a meaningful quantity (time, rate, frequency, scale), "
            "consider translating it into a direct comparison against the viewer's own "
            "equivalent experience — their day, week, or body — when that comparison is "
            "supported and clarifies the stakes rather than merely stating the number."
        ),
        (
            "When the research describes a process that reinforces or compounds over time "
            "until it cannot be reversed, consider narrating it as a mechanism closing in "
            "explicit causal steps rather than a static list of causes."
        ),
        (
            "Vary questions, explanation, evidence, story, and interpretation; avoid repetitive "
            "cliffhangers, formulaic transitions, and excessive rhetorical questions."
        ),
        (
            "End by answering or reframing the opening mystery and explaining why the answer "
            "matters; when it strengthens the loop, echo the opening's specific concrete image "
            "or phrasing rather than only reframing it in the abstract."
        ),
        (
            "Keep narration conversational, intelligent, accessible, original, and suitable for "
            "natural spoken delivery; never reproduce reference transcript wording."
        ),
        "Make important beats drawable as simple static scenes while keeping factual accuracy first.",
        (
            "Treat all of the above as a menu, not a checklist: choose only the techniques this "
            "specific topic and research actually support, and skip any that would feel forced."
        ),
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
