from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.research.models import Research


def test_openai_structured_research():
    client = OpenAI(api_key=OPENAI_API_KEY)

    response = client.responses.parse(
        model=OPENAI_MODEL,
        tools=[
            {
                "type": "web_search",
            }
        ],
        input=[
            {
                "role": "system",
                "content": (
                    "You are the research engine for Ritzz, "
                    "an educational YouTube channel. "
                    "Research the topic carefully using web sources. "
                    "Separate established facts from popular theories "
                    "or myths. Do not invent sources or facts."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Research this topic: "
                    "Why Do Pirates Wear Eye Patches?"
                ),
            },
        ],
        text_format=Research,
    )

    research = response.output_parsed

    assert research is not None

    assert research.topic
    assert research.category
    assert research.core_question
    assert research.short_answer

    assert len(research.key_facts) > 0
    assert len(research.sources) > 0

    print("\n--- STRUCTURED RESEARCH ---")
    print(research.model_dump_json(indent=4))