import os
import requests
import supervisely_lib as sly

TEAM_ID = int(os.environ['modal.state.teamId'])
WORKSPACE_ID = int(os.environ['modal.state.workspaceId'])

PROJECT_ID = int(os.environ["modal.state.slyProjectId"])
DATASET_ID = os.environ.get("modal.state.slyDatasetId")

INPUT_FILE = os.environ.get("modal.state.slyFile")
PROJECT_NAME = os.environ['modal.state.projectName']
DATASET_NAME = os.environ['modal.state.datasetName']

my_app = sly.AppService(ignore_task_id=True)


def download_file(url, local_path, logger, cur_video_index, total_videos_count):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        total_size_in_bytes = int(r.headers.get('content-length', 0))
        progress = sly.Progress("Downloading [{}/{}] {!r}".format(cur_video_index,
                                                                  total_videos_count,
                                                                  sly.fs.get_file_name_with_ext(local_path)),
                                total_size_in_bytes, ext_logger=logger, is_size=True)
        with open(local_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                progress.iters_done_report(len(chunk))
    return local_path


@my_app.callback("import_videos")
@sly.timeit
def import_videos(api: sly.Api, task_id, context, state, app_logger):
    local_file = os.path.join(my_app.data_dir, sly.fs.get_file_name_with_ext(INPUT_FILE))
    api.file.download(TEAM_ID, INPUT_FILE, local_file)

    with open(local_file) as f:
        video_urls = f.readlines()
    # you may also want to remove whitespace characters like `\n` at the end of each line
    video_urls = [x.strip() for x in video_urls]

    project = api.project.get_info_by_name(WORKSPACE_ID, PROJECT_NAME)
    if project is None:
        project = api.project.create(WORKSPACE_ID, PROJECT_NAME, type=sly.ProjectType.VIDEOS)

    dataset = api.dataset.get_info_by_name(project.id, DATASET_NAME)
    if dataset is None:
        dataset = api.dataset.create(project.id, DATASET_NAME)

    for idx, video_url in enumerate(video_urls):
        try:
            app_logger.info("Processing [{}/{}]: {!r}".format(idx, len(video_urls), video_url))
            video_name = sly.fs.get_file_name_with_ext(video_url)
            local_video_path = os.path.join(my_app.data_dir, video_name)
            download_file(video_url, local_video_path, app_logger, idx + 1, len(video_urls))
            item_name = api.video.get_free_name(dataset.id, video_name)  # checks if item with the same name exists in dataset
            api.video.upload_paths(dataset.id, [item_name], [local_video_path])
        except Exception as e:
            app_logger.warn(f"Error during import {video_url}: {repr(e)}")
        finally:
            sly.fs.silent_remove(local_video_path)

    api.task.set_output_project(task_id, project.id, project.name)
    my_app.stop()


def main():
    sly.logger.info("Script arguments", extra={
        "TEAM_ID": TEAM_ID,
        "WORKSPACE_ID": WORKSPACE_ID,
        "INPUT_FILE": INPUT_FILE,
        "PROJECT_NAME": PROJECT_NAME,
    })
    my_app.run(initial_events=[{"command": "import_videos"}])


if __name__ == "__main__":
    sly.main_wrapper("main", main)