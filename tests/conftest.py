"""Offline test harness for extract-frames-from-videos.

src/main.py is imported with the task context in env vars and sly.Api.from_env replaced by an
in-memory fake (no Supervisely server). Videos are real files written with OpenCV whose frames
carry their own index (black/white stripes), so the tests can check which frame was stored under which index.

App code is imported from ../src, or from $APP_SRC (run the same tests against another checkout).

    pip install -r dev_requirements.txt pytest && python -m pytest tests
"""

import importlib
import os
import shutil
import sys
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

SRC = os.path.abspath(
    os.environ.get("APP_SRC", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
)
APP_MODULES = ("main", "workflow")


BITS, STRIPE, HEIGHT = 8, 8, 32  # frame index as 8 black/white stripes (survives compression)


def write_video(path, n_frames):
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 30, (BITS * STRIPE, HEIGHT))
    for i in range(n_frames):
        frame = np.zeros((HEIGHT, BITS * STRIPE, 3), np.uint8)
        for bit in range(BITS):
            if i >> bit & 1:
                frame[:, bit * STRIPE : (bit + 1) * STRIPE] = 255
        writer.write(frame)
    writer.release()
    return path


def frame_index(frame):
    """Decodes the index written by write_video from an RGB frame."""
    frame = np.asarray(frame)
    return sum(
        1 << bit
        for bit in range(BITS)
        if frame[:, bit * STRIPE + 2 : (bit + 1) * STRIPE - 2].mean() > 127
    )


class FakeApi:
    """projects: {id: name}; datasets: [(id, project_id, parent_id, name)];
    videos: {dataset_id: [(id, name, frames_count, local_path_or_None)]}"""

    def __init__(self, project, datasets, videos):
        self.src_project = SimpleNamespace(id=project[0], name=project[1], description="desc")
        self.src_datasets = [
            SimpleNamespace(id=i, project_id=p, parent_id=par, name=n, description="")
            for i, p, par, n in datasets
        ]
        self.src_videos = videos
        self.created_projects = {}  # id -> name
        self.removed_projects = []
        self.created_datasets = {}  # id -> SimpleNamespace(name, parent_id, project_id)
        self.images = []  # dicts: dataset, name, frame, meta
        self.output_project = None
        self.project = SimpleNamespace(
            get_info_by_id=self._get_project,
            create=self._create_project,
            remove=self._remove_project,
        )
        self.dataset = SimpleNamespace(
            get_list=self._get_datasets,
            get_info_by_id=lambda id: next(d for d in self.src_datasets if d.id == id),
            create=self._create_dataset,
        )
        self.video = SimpleNamespace(get_list=self._get_videos, download_path=self._download)
        self.image = SimpleNamespace(upload_nps=self._upload_nps)
        self.task = SimpleNamespace(set_output_project=self._set_output_project)
        noop = lambda *a, **k: None  # noqa: E731
        self.app = SimpleNamespace(
            workflow=SimpleNamespace(
                add_input_project=noop, add_input_dataset=noop, add_output_project=noop
            )
        )

    def _get_project(self, id):
        assert id == self.src_project.id
        return self.src_project

    def _create_project(
        self, workspace_id, name, type=None, description="", change_name_if_conflict=False
    ):
        pid = 900 + len(self.created_projects) + len(self.removed_projects)
        self.created_projects[pid] = name
        return SimpleNamespace(id=pid, name=name)

    def _remove_project(self, id):
        self.created_projects.pop(id)
        self.removed_projects.append(id)

    def _get_datasets(self, project_id, filters=None, recursive=False, parent_id=None):
        out = [d for d in self.src_datasets if d.project_id == project_id]
        if parent_id is not None:
            return [d for d in out if d.parent_id == parent_id]
        if not recursive:
            return [d for d in out if d.parent_id is None]
        return out

    def _create_dataset(
        self, project_id, name, description="", change_name_if_conflict=False, parent_id=None
    ):
        siblings = [
            d.name
            for d in self.created_datasets.values()
            if d.project_id == project_id and d.parent_id == parent_id
        ]
        if name in siblings:
            if not change_name_if_conflict:
                raise RuntimeError(f"Dataset with name '{name}' already exists")
            name = f"{name}_001"
        did = 7000 + len(self.created_datasets)
        self.created_datasets[did] = SimpleNamespace(
            id=did, name=name, parent_id=parent_id, project_id=project_id
        )
        return SimpleNamespace(id=did, name=name)

    def _get_videos(self, dataset_id):
        return [
            SimpleNamespace(id=i, name=n, frames_count=fc, dataset_id=dataset_id)
            for i, n, fc, _ in self.src_videos.get(dataset_id, [])
        ]

    def _download(self, id, path):
        (src,) = [p for vids in self.src_videos.values() for i, _, _, p in vids if i == id]
        shutil.copy(src, path)

    def _upload_nps(self, dataset_id, names, imgs, progress_cb=None, metas=None):
        for name, img, meta in zip(names, imgs, metas):
            self.images.append(
                {"dataset": dataset_id, "name": name, "frame": frame_index(img), "meta": meta}
            )
        if progress_cb:
            progress_cb(len(names))
        return [SimpleNamespace(id=len(self.images) - k, name=n) for k, n in enumerate(names)]

    def _set_output_project(self, task_id, project_id, project_name=None):
        self.output_project = project_id

    # assertion helpers
    def dataset_paths(self):
        def path(d):
            parent = self.created_datasets.get(d.parent_id)
            return (path(parent) + "/" if parent else "") + d.name

        return sorted(path(d) for d in self.created_datasets.values())

    def names_in(self, dataset_path):
        (did,) = [i for i, d in self.created_datasets.items() if self._path(i) == dataset_path]
        return sorted(im["name"] for im in self.images if im["dataset"] == did)

    def _path(self, did):
        d = self.created_datasets[did]
        return (self._path(d.parent_id) + "/" if d.parent_id else "") + d.name


@pytest.fixture
def run_app(tmp_path, monkeypatch):
    """run_app(api, dataset_id=None, step=10, structure="keep original", name="extracted-frames")
    -> exception raised by the app (None on success)."""
    import supervisely as sly

    def _run(api, dataset_id=None, step=10, structure="keep original", name="extracted-frames"):
        env = {
            "ENV": "production",
            "TASK_ID": "1",
            "context.teamId": "8",
            "context.workspaceId": "9",
            "context.projectId": str(api.src_project.id),
            "modal.state.framesStep": str(step),
            "modal.state.datasetsStructure": structure,
            "modal.state.projectName": name,
            "SLY_APP_DATA_DIR": str(tmp_path / "data"),
        }
        os.makedirs(env["SLY_APP_DATA_DIR"], exist_ok=True)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        if dataset_id is None:
            monkeypatch.delenv("context.datasetId", raising=False)
        else:
            monkeypatch.setenv("context.datasetId", str(dataset_id))
        monkeypatch.setattr(sly.Api, "from_env", classmethod(lambda cls, *a, **k: api))
        monkeypatch.syspath_prepend(SRC)
        for mod in APP_MODULES:
            sys.modules.pop(mod, None)
        try:
            main = importlib.import_module("main")
            main.main()
        except BaseException as e:  # noqa: BLE001 - SystemExit included, the test inspects it
            return e
        return None

    yield _run
    for mod in APP_MODULES:
        sys.modules.pop(mod, None)


@pytest.fixture
def video(tmp_path):
    """video(n_frames) -> path of a real mp4 whose frame i shows the number i."""
    counter = iter(range(10**6))

    def make(n_frames):
        return write_video(str(tmp_path / f"v{next(counter)}.mp4"), n_frames)

    return make
