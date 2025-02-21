import os
import supervisely_lib as sly
import workflow as w
import cv2

TEAM_ID = int(os.environ['context.teamId'])
WORKSPACE_ID = int(os.environ['context.workspaceId'])
PROJECT_ID = int(os.environ["modal.state.slyProjectId"])
DATASET_ID = os.environ.get("modal.state.slyDatasetId", None)
if DATASET_ID is not None:
    DATASET_ID = int(DATASET_ID)
FRAMES_STEP = int(os.environ["modal.state.framesStep"])
DATASETS_STRUCTURE = os.environ["modal.state.datasetsStructure"]
RESULT_PROJECT_NAME = os.environ["modal.state.projectName"]

my_app = sly.AppService()

def frame_batches_generator(video_path, frame_count, step, batch_size):
    cap = cv2.VideoCapture(video_path)
    batch = []
    for frame_index in range(0, frame_count, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ret, frame = cap.read()
        if not ret:
            break
        batch.append((frame_index, frame))
        if len(batch) == batch_size:
            yield batch
            batch = []
    cap.release()

@my_app.callback("extract_frames")
@sly.timeit
def extract_frames(api: sly.Api, task_id, context, state, app_logger):
    project = api.project.get_info_by_id(PROJECT_ID)
    if DATASET_ID is None:
        datasets = api.dataset.get_list(project.id)
        w.workflow_input(api, project.id, "project")
    else:
        datasets = [api.dataset.get_info_by_id(DATASET_ID)]
        w.workflow_input(api, DATASET_ID, "dataset")

    res_project = api.project.create(WORKSPACE_ID,
                                     RESULT_PROJECT_NAME,
                                     type=sly.ProjectType.IMAGES,
                                     description=project.description,
                                     change_name_if_conflict=True)
    for dataset in datasets:
        res_dataset = None
        if DATASETS_STRUCTURE == "keep original":
            res_dataset = api.dataset.create(res_project.id, dataset.name, dataset.description)
        videos_info = api.video.get_list(dataset.id)
        for info in videos_info:
            if DATASETS_STRUCTURE == "create dataset for every video":
                res_dataset = api.dataset.create(res_project.id, f"{info.id}_{info.name}")

            video_path = my_app.data_dir + info.name

            app_logger.info(f"Downloading video: {info.name}")
            download_progress = sly.Progress(f"Downloading video: {info.name}", 1)
            api.video.download_path(info.id, video_path, download_progress.iters_done_report)

            shared_meta = {
                "original_project_id": project.id,
                "original_project_name": project.name,
                "original_dataset_id": dataset.id,
                "original_dataset_name": dataset.name,
                "original_video_id": info.id,
                "original_video_name": info.name,
            }
            cnt_extracted_frames = int(info.frames_count/FRAMES_STEP) + 1
            progress = sly.Progress(info.name, cnt_extracted_frames)
            for batch in frame_batches_generator(video_path, info.frames_count, FRAMES_STEP, 10):
                indices = [frame_index for frame_index, _ in batch]
                frames = [cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) for _, frame in batch]

                metas = [{**shared_meta, "frame": index} for index in indices]
                names = [f"{info.id}_frame_{index:06d}.jpg" for index in indices]

                app_logger.info(f"Uploading {len(names)} frames: {progress.current}/{cnt_extracted_frames}")
                api.image.upload_nps(res_dataset.id, names, frames, progress.iters_done_report, metas)
            sly.fs.clean_dir(my_app.data_dir)

    api.task.set_output_project(task_id, res_project.id, res_project.name)
    w.workflow_output(api, res_project.id)
    my_app.stop()


def main():
    sly.logger.info("Script arguments", extra={
        "TEAM_ID": TEAM_ID,
        "WORKSPACE_ID": WORKSPACE_ID,
        "PROJECT_ID": PROJECT_ID,
        "DATASET_ID": DATASET_ID
    })
    my_app.run(initial_events=[{"command": "extract_frames"}])


if __name__ == "__main__":
    sly.main_wrapper("main", main)
