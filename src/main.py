import os
import supervisely_lib as sly

TEAM_ID = int(os.environ['modal.state.teamId'])
WORKSPACE_ID = int(os.environ['modal.state.workspaceId'])
PROJECT_ID = int(os.environ["modal.state.slyProjectId"])
DATASET_ID = os.environ.get("modal.state.slyDatasetId", None)
if DATASET_ID is not None:
    DATASET_ID = int(DATASET_ID)
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
    else:
        datasets = [api.dataset.get_info_by_id(DATASET_ID)]

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
                res_dataset = api.dataset.create(res_project.id, info.name)

            shared_meta = {
                "original_project_id": project.id,
                "original_project_name": project.name,
                "original_dataset_id": dataset.id,
                "original_dataset_name": dataset.name,
            }
            frames_dir = os.path.join(my_app.data_dir, "frames")
            sly.fs.mkdir(frames_dir)
            metas = []
            paths = []
            names = []
            progress = sly.Progress(info.name, int(info.frames_count/FRAMES_STEP) + 1)
            for frame_index in range(0, info.frames_count, FRAMES_STEP):
                image_name = "{}_frame_{:06d}.jpg".format(info.id, frame_index)
                image_path = os.path.join(frames_dir, image_name)
                api.video.frame.download_path(info.id, frame_index, image_path)
                metas.append({
                    **shared_meta,
                    "original_video_id": info.id,
                    "original_video_name": info.name,
                    "frame": frame_index
                })
                paths.append(image_path)
                names.append(image_name)
                progress.iter_done_report()
            api.image.upload_paths(res_dataset.id, names, paths, metas=metas)
            sly.fs.clean_dir(frames_dir)

    api.task.set_output_project(task_id, res_project.id, res_project.name)
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