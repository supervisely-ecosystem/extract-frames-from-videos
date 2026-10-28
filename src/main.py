import os
import supervisely as sly
import workflow as w
import cv2
from supervisely import handle_exceptions
from dotenv import load_dotenv

if sly.is_development():
    debug_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'debug.env')
    load_dotenv(debug_env_path)

TEAM_ID = sly.env.team_id()
WORKSPACE_ID = sly.env.workspace_id()
PROJECT_ID = sly.env.project_id()
DATASET_ID = sly.env.dataset_id(raise_not_found=False)
if DATASET_ID is not None:
    DATASET_ID = int(DATASET_ID)
FRAMES_STEP = int(os.environ["modal.state.framesStep"])
DATASETS_STRUCTURE = os.environ["modal.state.datasetsStructure"]
RESULT_PROJECT_NAME = os.environ["modal.state.projectName"]
TASK_ID = int(os.environ['TASK_ID'])
DATA_DIR = sly.app.get_data_dir()
api = sly.Api.from_env()

def frame_batches_generator(video_path, frame_count, step, batch_size):
    cap = cv2.VideoCapture(video_path)
    batch = []
    for frame_index in range(0, frame_count, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = cap.read()
        if not ret:
            break
        batch.append((frame_index, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch
    cap.release()

def selected_datasets(all_datasets, dataset_id=None):
    """The datasets to process, parents before children: the whole project tree, or the
    selected dataset and all datasets nested in it."""
    children = {}
    for dataset in all_datasets:
        children.setdefault(dataset.parent_id, []).append(dataset)
    if dataset_id is None:
        roots = children.get(None, [])
    else:
        roots = [dataset for dataset in all_datasets if dataset.id == dataset_id]
        if not roots:
            raise ValueError(f"Dataset {dataset_id} is not in project {PROJECT_ID}")
    ordered, stack = [], list(reversed(roots))
    while stack:
        dataset = stack.pop()
        ordered.append(dataset)
        stack.extend(reversed(children.get(dataset.id, [])))
    return ordered


@sly.timeit
@handle_exceptions(has_ui=False)
def extract_frames(task_id):
    if FRAMES_STEP < 1:
        raise ValueError(f"Frames step must be 1 or more, got {FRAMES_STEP}")
    project = api.project.get_info_by_id(PROJECT_ID)
    datasets = selected_datasets(api.dataset.get_list(project.id, recursive=True), DATASET_ID)
    if DATASET_ID is None:
        w.workflow_input(api, project.id, "project")
    else:
        w.workflow_input(api, DATASET_ID, "dataset")

    res_project = api.project.create(WORKSPACE_ID,
                                     RESULT_PROJECT_NAME,
                                     type=sly.ProjectType.IMAGES,
                                     description=project.description,
                                     change_name_if_conflict=True)
    res_datasets = {}  # source dataset id -> result dataset (keep original)
    total_frames, total_videos, failed_videos = 0, 0, []
    for dataset in datasets:
        res_dataset = None
        if DATASETS_STRUCTURE == "keep original":
            parent = res_datasets.get(dataset.parent_id)
            res_dataset = api.dataset.create(
                res_project.id,
                dataset.name,
                dataset.description,
                change_name_if_conflict=True,
                parent_id=parent.id if parent is not None else None,
            )
            res_datasets[dataset.id] = res_dataset
        videos_info = api.video.get_list(dataset.id)
        for info in videos_info:
            if DATASETS_STRUCTURE == "create dataset for every video":
                res_dataset = api.dataset.create(res_project.id, f"{info.id}_{info.name}")

            # local name from the id: video names are user data and must not pick the path
            video_path = os.path.join(DATA_DIR, f"{info.id}{sly.fs.get_file_ext(info.name)}")

            sly.logger.info(f"Downloading video: {info.name}")
            download_progress = sly.Progress(f"Downloading video: {info.name}", 1)
            api.video.download_path(info.id, video_path)
            download_progress.iter_done_report()

            shared_meta = {
                "original_project_id": project.id,
                "original_project_name": project.name,
                "original_dataset_id": dataset.id,
                "original_dataset_name": dataset.name,
                "original_video_id": info.id,
                "original_video_name": info.name,
            }
            cnt_extracted_frames = len(range(0, info.frames_count, FRAMES_STEP))
            progress = sly.Progress(info.name, cnt_extracted_frames)
            extracted = 0
            for batch in frame_batches_generator(video_path, info.frames_count, FRAMES_STEP, 10):
                indices = [frame_index for frame_index, _ in batch]
                frames = [frame for _, frame in batch]

                metas = [{**shared_meta, "frame": index} for index in indices]
                names = [f"{info.id}_frame_{index:06d}.jpg" for index in indices]

                sly.logger.info(f"Uploading {len(names)} frames: {progress.current}/{cnt_extracted_frames}")
                api.image.upload_nps(res_dataset.id, names, frames, progress.iters_done_report, metas)
                extracted += len(names)
            sly.fs.silent_remove(video_path)
            total_frames += extracted
            total_videos += 1
            if extracted == 0 and cnt_extracted_frames > 0:
                sly.logger.warning(f"No frame could be read from video '{info.name}' (id {info.id})")
                failed_videos.append(f"{info.name} (id {info.id})")
            elif extracted < cnt_extracted_frames:
                sly.logger.warning(
                    f"Video '{info.name}' (id {info.id}): {extracted} of {cnt_extracted_frames} "
                    "frames extracted, reading stopped early"
                )

    if total_frames == 0:
        # the project was created by this task and is empty: do not leave it behind
        api.project.remove(res_project.id)
        if failed_videos:
            reason = f"unreadable videos: {', '.join(failed_videos[:10])}"
        elif total_videos:
            reason = f"{total_videos} video(s) without frames"
        else:
            reason = "no videos in the selected project or dataset"
        raise RuntimeError(f"No frames were extracted ({reason}); no project was created")

    api.task.set_output_project(task_id, res_project.id, res_project.name)
    w.workflow_output(api, res_project.id)
    if failed_videos:
        raise RuntimeError(
            f"{len(failed_videos)} video(s) could not be read and have no frames in project "
            f"'{res_project.name}' (id {res_project.id}): {', '.join(failed_videos[:10])}"
            + (f" and {len(failed_videos) - 10} more" if len(failed_videos) > 10 else "")
        )


def main():
    sly.logger.info("Script arguments", extra={
        "TEAM_ID": TEAM_ID,
        "WORKSPACE_ID": WORKSPACE_ID,
        "PROJECT_ID": PROJECT_ID,
        "DATASET_ID": DATASET_ID
    })
    extract_frames(TASK_ID)


if __name__ == "__main__":
    sly.main_wrapper("main", main)
