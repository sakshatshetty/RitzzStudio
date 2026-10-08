from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.research.models import Research
from modules.storyboard.models import Storyboard, StoryboardScene
from modules.storyboard.visual_models import (
    SceneVisualContract,
    SceneVisualContractBatch,
    VisualWorldBible,
)

VISUAL_WORLD_BIBLE_FILENAME = "visual_world_bible.json"
SCENE_VISUAL_CONTRACTS_FILENAME = "scene_visual_contracts.json"


class VisualContextEngine:
    """Derive project-wide and per-scene visual constraints from approved inputs."""

    SCENE_BATCH_SIZE = 8

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        self.client = client or OpenAI(api_key=OPENAI_API_KEY)
        self.model = model or OPENAI_MODEL

    def plan(
        self,
        research: Research,
        storyboard: Storyboard,
        project_directory: str | Path,
    ) -> tuple[Storyboard, VisualWorldBible, list[SceneVisualContract]]:
        if not storyboard.scenes:
            raise ValueError("Cannot plan visual context for an empty storyboard.")
        if storyboard.topic != research.topic:
            raise ValueError("Visual context topic does not match approved research.")

        directory = Path(project_directory)
        directory.mkdir(parents=True, exist_ok=True)
        world = self._plan_world(research)
        (directory / VISUAL_WORLD_BIBLE_FILENAME).write_text(
            world.model_dump_json(indent=2),
            encoding="utf-8",
        )
        contracts = self._plan_contracts(research, storyboard, world)
        by_id = {contract.scene_id: contract for contract in contracts}
        scenes = [
            scene.model_copy(update={"visual_contract": by_id[scene.scene_id]})
            for scene in storyboard.scenes
        ]
        updated_storyboard = storyboard.model_copy(update={"scenes": scenes})
        (directory / SCENE_VISUAL_CONTRACTS_FILENAME).write_text(
            json.dumps(
                {
                    "version": 1,
                    "contracts": [
                        contract.model_dump(mode="json")
                        for contract in contracts
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return updated_storyboard, world, contracts

    def _plan_world(self, research: Research) -> VisualWorldBible:
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a visual-context planner. Derive a concise, "
                        "evidence-grounded visual world from approved research. "
                        "Keep the RITZZ art direction fixed: hand-drawn educational "
                        "cartoon, stickman/doodle characters, expressive poses, thick "
                        "black marker-like outlines, controlled imperfection, clean "
                        "shapes, flat colors, and simple but contextually informative "
                        "backgrounds. Never recommend a photographic, cinematic, "
                        "3D, anime, glossy, or corporate-vector style. "
                        "Do not invent a date, place, society, technology, or "
                        "historical constraint that the research does not support. "
                        "Use 'Not established by the approved research.' where "
                        "details are unavailable. Mark historical false for topics "
                        "without a historical setting. Create forbidden visual "
                        "restrictions only when supported by the research and world."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Create the project visual-world bible. Include an explicit "
                        "technology ceiling and generic, context-derived visual "
                        "restrictions. Keep RITZZ's general simple 2D hand-drawn "
                        "stick-figure/cartoon style.\n\nApproved research:\n"
                        f"{research.model_dump_json(indent=2)}"
                    ),
                },
            ],
            text_format=VisualWorldBible,
        )
        world = response.output_parsed
        if not isinstance(world, VisualWorldBible):
            raise RuntimeError("Visual-world planning returned no valid structured result.")
        if world.topic != research.topic:
            raise ValueError("Visual-world planner returned a different topic.")
        if world.historical and not world.technology_ceiling.strip():
            raise ValueError("Historical visual world is missing its technology ceiling.")
        return world

    def _plan_contracts(
        self,
        research: Research,
        storyboard: Storyboard,
        world: VisualWorldBible,
    ) -> list[SceneVisualContract]:
        result: list[SceneVisualContract] = []
        scenes = storyboard.scenes
        for start in range(0, len(scenes), self.SCENE_BATCH_SIZE):
            batch = scenes[start:start + self.SCENE_BATCH_SIZE]
            context = [
                {
                    "scene_id": scene.scene_id,
                    "section_id": scene.section_id,
                    "narration": scene.narration,
                    "sentence_id": scene.sentence_id,
                    "previous_sentence": scene.previous_sentence,
                    "next_sentence": scene.next_sentence,
                    "visual_description": scene.visual_description,
                    "character_action": scene.character_action,
                    "background": scene.background,
                    "props": scene.props,
                }
                for scene in batch
            ]
            neighbors = [
                {
                    "scene_id": scenes[index].scene_id,
                    "narration": scenes[index].narration,
                    "visual_description": scenes[index].visual_description,
                    "character_action": scenes[index].character_action,
                }
                for index in range(max(0, start - 1), min(len(scenes), start + len(batch) + 1))
            ]
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Create scene-level visual contracts using the project "
                            "world bible, approved research, storyboard intent, and "
                            "neighboring scenes. The visual description/action and "
                            "research are authoritative. The current narration sentence "
                            "is the primary visual instruction: determine its subject "
                            "and visible action from that sentence. Use previous/next "
                            "sentences only as continuity context; never substitute a "
                            "neighboring sentence's action. Explicitly resolve ambiguous "
                            "terms in plain visual language. Carry forward the same "
                            "character, object, clothing, color, and environment identities "
                            "unless a scene explicitly changes context. Never add an unsupported "
                            "historical detail. Add only context-relevant forbidden "
                            "objects and required objects. Set semantic_review_reasons "
                            "when a generated image needs special semantic scrutiny, "
                            "such as ambiguity, historical restrictions, key props, "
                            "or a stated continuity dependency."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Return exactly one contract for every requested scene, "
                            "in the same order, preserving scene IDs. Each requested "
                            "scene represents exactly one complete sentence and must "
                            "produce exactly one image. Adjacent scene context is "
                            "reference only and must not be returned as a contract "
                            "unless it is also listed among requested scenes.\n\n"
                            f"Project visual-world bible:\n{world.model_dump_json(indent=2)}\n\n"
                            f"Approved research:\n{research.model_dump_json(indent=2)}\n\n"
                            "Requested scenes:\n"
                            f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
                            "Adjacent scene context:\n"
                            f"{json.dumps(neighbors, ensure_ascii=False, indent=2)}"
                        ),
                    },
                ],
                text_format=SceneVisualContractBatch,
            )
            parsed = response.output_parsed
            if not isinstance(parsed, SceneVisualContractBatch):
                raise RuntimeError(
                    f"Scene visual-contract planning returned no valid result for "
                    f"{[scene.scene_id for scene in batch]}."
                )
            expected_ids = [scene.scene_id for scene in batch]
            actual_ids = [contract.scene_id for contract in parsed.scenes]
            allowed_neighbor_ids = {
                scene["scene_id"] for scene in neighbors
            } - set(expected_ids)
            unexpected_ids = [
                scene_id
                for scene_id in actual_ids
                if scene_id not in expected_ids
                and scene_id not in allowed_neighbor_ids
            ]
            if unexpected_ids:
                raise ValueError(
                    "Scene visual-contract planning returned IDs outside the "
                    f"requested and adjacent scenes: {unexpected_ids!r}."
                )
            requested_contracts = [
                contract
                for contract in parsed.scenes
                if contract.scene_id in expected_ids
            ]
            requested_ids = [
                contract.scene_id for contract in requested_contracts
            ]
            if requested_ids != expected_ids:
                raise ValueError(
                    f"Scene visual-contract IDs did not match the requested order: "
                    f"{requested_ids!r} != {expected_ids!r}."
                )
            result.extend(requested_contracts)
        if len(result) != len(scenes):
            raise RuntimeError("Visual planner did not create a contract for every scene.")
        return result


def load_visual_world_bible(
    project_directory: str | Path,
) -> VisualWorldBible | None:
    path = Path(project_directory) / VISUAL_WORLD_BIBLE_FILENAME
    if not path.is_file():
        return None
    return VisualWorldBible.model_validate_json(path.read_text(encoding="utf-8"))


def contract_payload(scene: StoryboardScene) -> dict[str, Any] | None:
    if scene.visual_contract is None:
        return None
    return scene.visual_contract.model_dump(mode="json")
