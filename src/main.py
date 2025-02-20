import os
import supervisely_lib as sly
import workflow as w

if sly.is_development():
    from dotenv import load_dotenv
    load_dotenv("debug.env")
    load_dotenv(os.path.expanduser("~/supervisely.env"))
    TEAM_ID = int(os.environ['modal.state.teamId'])
    WORKSPACE_ID = int(os.environ['modal.state.workspaceId'])
    PROJECT_ID = int(os.environ['modal.state.slyProjectId'])
    DATASET_ID = os.environ.get('modal.state.slyDatasetId', None)
    if DATASET_ID is not None:
        DATASET_ID = int(DATASET_ID)
else:
    TEAM_ID = sly.env.team_id()
    WORKSPACE_ID = sly.env.workspace_id()
    PROJECT_ID = sly.env.project_id()
    DATASET_ID = sly.env.dataset_id(False)

FRAMES_STEP = int(os.environ["modal.state.framesStep"])
DATASETS_STRUCTURE = os.environ["modal.state.datasetsStructure"]
RESULT_PROJECT_NAME = os.environ["modal.state.projectName"]

my_app = sly.AppService()


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

            for batch_indices in sly.batched(list(range(0, info.frames_count, FRAMES_STEP)), batch_size=10):
                metas = [{**shared_meta, "frame": frame_index} for frame_index in batch_indices]
                names = [f"{info.id}_frame_{frame_index:06d}.jpg" for frame_index in batch_indices]

                app_logger.info(f"Downloading {len(names)} frames: {progress.current}/{cnt_extracted_frames}")
                imgs = api.video.frame.download_nps(info.id, batch_indices)

                app_logger.info(f"Uploading {len(names)} frames: {progress.current}/{cnt_extracted_frames}")
                api.image.upload_nps(res_dataset.id, names, imgs, progress.iters_done_report, metas)

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
