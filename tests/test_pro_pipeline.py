from types import SimpleNamespace

import pytest

from modules.video.pipeline_engine import VideoProductionPipeline
from modules.video.pipeline_models import VideoProductionRequest
from modules.video.pro_director import (
    ProEditPlan,
    ProSceneDirection,
)


class FakeRenderer:
    def __init__(self, events):
        self.events = events
        self.arguments = None

    def render(self, **kwargs):
        self.events.append("render")
        self.arguments = kwargs
        return kwargs["output_file"]


class FakeDirector:
    def __init__(self, events):
        self.events = events

    def create_plan(self, **_kwargs):
        self.events.append("direct")
        return ProEditPlan(
            topic="Test topic",
            total_duration_seconds=1,
            scenes=[
                ProSceneDirection(
                    scene_id="scene_001",
                    start_seconds=0,
                    duration_seconds=1,
                )
            ],
        )

    def save_plan(self, _plan, path):
        self.events.append("save")
        return path


class FakeAssemblyEngine:
    @staticmethod
    def load_storyboard(_path):
        return SimpleNamespace(topic="Test topic")


def _request(tmp_path, style):
    return VideoProductionRequest(
        storyboard_file=str(tmp_path / "storyboard.json"),
        image_directory=str(tmp_path / "images"),
        narration_result_file=str(tmp_path / "narration.json"),
        output_directory=str(tmp_path / "video"),
        editing_style=style,
        sound_effects_directory=(
            str(tmp_path / "effects") if style == "pro" else None
        ),
    )


def test_pro_director_runs_and_saves_plan_before_ffmpeg_render(tmp_path):
    events = []
    renderer = FakeRenderer(events)
    pipeline = VideoProductionPipeline(
        assembly_engine=FakeAssemblyEngine(),
        renderer=renderer,
        pro_director=FakeDirector(events),
    )

    output = pipeline._render_video(
        request=_request(tmp_path, "pro"),
        synchronized_plan=object(),
        motion_plan=object(),
        audio_path=tmp_path / "voice.wav",
        output_video_file=tmp_path / "video" / "render.mp4",
    )

    assert events == ["direct", "save", "render"]
    assert output == tmp_path / "video" / "render.mp4"
    assert renderer.arguments["pro_edit_plan"].topic == "Test topic"


@pytest.mark.parametrize("style", ["hard_cut", "history"])
def test_non_pro_render_skips_director_and_keeps_renderer_call(
    tmp_path,
    style,
):
    events = []
    renderer = FakeRenderer(events)

    class ProDirectorMustNotRun:
        def create_plan(self, **_kwargs):
            pytest.fail("The Pro director must run only in Pro mode.")

    pipeline = VideoProductionPipeline(
        assembly_engine=FakeAssemblyEngine(),
        renderer=renderer,
        pro_director=ProDirectorMustNotRun(),
    )
    output = pipeline._render_video(
        request=_request(tmp_path, style),
        synchronized_plan=object(),
        motion_plan=object(),
        audio_path=tmp_path / "voice.wav",
        output_video_file=tmp_path / "video" / "render.mp4",
    )

    assert events == ["render"]
    assert "pro_edit_plan" not in renderer.arguments
    assert output == tmp_path / "video" / "render.mp4"
