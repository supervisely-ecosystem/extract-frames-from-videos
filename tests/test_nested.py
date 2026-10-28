"""Nested datasets: old code read only top-level datasets and ignored children."""

from conftest import FakeApi


def _nested(video):
    return FakeApi(
        (1, "videos"),
        [
            (10, 1, None, "p1"),
            (11, 1, 10, "sub"),
            (12, 1, None, "p2"),
            (13, 1, 12, "sub"),
            (14, 1, 13, "deep"),
        ],
        {
            10: [(100, "a.mp4", 5, video(5))],
            11: [(101, "b.mp4", 5, video(5))],
            13: [(102, "c.mp4", 5, video(5))],
            14: [(103, "d.mp4", 5, video(5))],
        },
    )


def test_project_keeps_nested_tree(run_app, video):
    api = _nested(video)
    assert run_app(api, step=5) is None
    assert api.dataset_paths() == ["p1", "p1/sub", "p2", "p2/sub", "p2/sub/deep"]
    assert api.names_in("p2/sub/deep") == ["103_frame_000000.jpg"]
    assert len(api.images) == 4


def test_dataset_launch_includes_children(run_app, video):
    api = _nested(video)
    assert run_app(api, dataset_id=12, step=5) is None
    assert api.dataset_paths() == ["p2", "p2/sub", "p2/sub/deep"]
    assert sorted(im["meta"]["original_video_id"] for im in api.images) == [102, 103]


def test_nested_dataset_for_every_video(run_app, video):
    api = _nested(video)
    assert run_app(api, step=5, structure="create dataset for every video") is None
    assert api.dataset_paths() == ["100_a.mp4", "101_b.mp4", "102_c.mp4", "103_d.mp4"]
