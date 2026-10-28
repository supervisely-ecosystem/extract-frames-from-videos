"""Runs that extracted nothing, or not everything, must not be reported as a success."""

import os

from conftest import FakeApi


def test_no_videos_fails_and_leaves_no_empty_project(run_app):
    api = FakeApi((1, "videos"), [(10, 1, None, "A")], {})
    error = run_app(api, step=10)
    assert error is not None
    assert api.created_projects == {}


def test_unreadable_video_fails_task_and_keeps_other_frames(run_app, video, tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video at all")
    api = FakeApi(
        (1, "videos"),
        [(10, 1, None, "A")],
        {10: [(100, "a.mp4", 5, video(5)), (101, "broken.mp4", 30, str(broken))]},
    )
    error = run_app(api, step=5)
    assert error is not None and "broken.mp4" in str(error)
    assert api.names_in("A") == ["100_frame_000000.jpg"]
    assert api.output_project in api.created_projects


def test_invalid_step_fails_before_creating_anything(run_app, video):
    api = FakeApi((1, "videos"), [(10, 1, None, "A")], {10: [(100, "a.mp4", 5, video(5))]})
    error = run_app(api, step=0)
    assert error is not None and "step" in str(error).lower()
    assert api.created_projects == {}


def test_video_name_cannot_place_the_download_outside_the_data_dir(run_app, video, tmp_path):
    seen = []
    api = FakeApi((1, "videos"), [(10, 1, None, "A")], {10: [(100, "../../evil.mp4", 5, video(5))]})
    download = api.video.download_path
    api.video.download_path = lambda id, path: (seen.append(path), download(id, path))
    assert run_app(api, step=5) is None
    data_dir = os.path.realpath(tmp_path / "data")
    assert seen and all(
        os.path.commonpath([os.path.realpath(p), data_dir]) == data_dir for p in seen
    )
