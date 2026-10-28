"""Behaviour that already worked before the fixes (regression guard)."""

from conftest import FakeApi


def test_keep_original_flat_project(run_app, video):
    api = FakeApi(
        (1, "videos"),
        [(10, 1, None, "A"), (11, 1, None, "B")],
        {10: [(100, "a.mp4", 25, video(25))], 11: [(101, "b.mp4", 10, video(10))]},
    )
    assert run_app(api, step=10) is None
    assert list(api.created_projects.values()) == ["extracted-frames"]
    assert api.dataset_paths() == ["A", "B"]
    assert api.names_in("A") == [
        "100_frame_000000.jpg",
        "100_frame_000010.jpg",
        "100_frame_000020.jpg",
    ]
    assert api.names_in("B") == ["101_frame_000000.jpg"]
    for im in api.images:
        assert im["frame"] == im["meta"]["frame"]  # the stored pixels are the indexed frame
    assert api.images[0]["meta"] == {
        "original_project_id": 1,
        "original_project_name": "videos",
        "original_dataset_id": 10,
        "original_dataset_name": "A",
        "original_video_id": 100,
        "original_video_name": "a.mp4",
        "frame": 0,
    }
    assert api.output_project in api.created_projects


def test_dataset_for_every_video(run_app, video):
    api = FakeApi(
        (1, "videos"),
        [(10, 1, None, "A")],
        {10: [(100, "a.mp4", 5, video(5)), (101, "b.mp4", 5, video(5))]},
    )
    assert run_app(api, step=2, structure="create dataset for every video") is None
    assert api.dataset_paths() == ["100_a.mp4", "101_b.mp4"]
    assert api.names_in("100_a.mp4") == [
        "100_frame_000000.jpg",
        "100_frame_000002.jpg",
        "100_frame_000004.jpg",
    ]


def test_step_one_extracts_every_frame_in_order(run_app, video):
    api = FakeApi((1, "videos"), [(10, 1, None, "A")], {10: [(100, "a.mp4", 40, video(40))]})
    assert run_app(api, step=1) is None
    assert [im["frame"] for im in api.images] == list(range(40))
    assert [im["meta"]["frame"] for im in api.images] == list(range(40))


def test_launch_from_flat_dataset(run_app, video):
    api = FakeApi(
        (1, "videos"),
        [(10, 1, None, "A"), (11, 1, None, "B")],
        {10: [(100, "a.mp4", 5, video(5))], 11: [(101, "b.mp4", 5, video(5))]},
    )
    assert run_app(api, dataset_id=11, step=5) is None
    assert api.dataset_paths() == ["B"]
