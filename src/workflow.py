# This module contains the functions that are used to configure the input and output of the workflow for the current app.

import supervisely as sly
from typing import Union, Literal


def workflow_input(api: sly.Api, id: Union[int, str], type: Literal["project", "dataset"]):
    if type == "project":
        api.app.workflow.add_input_project(int(id))
        sly.logger.debug(f"Workflow: Input project - {id}")
    elif type == "dataset":
        api.app.workflow.add_input_dataset(int(id))
        sly.logger.debug(f"Workflow: Input dataset - {id}")


def workflow_output(api: sly.Api, project_id: int):
    api.app.workflow.add_output_project(project_id)
    sly.logger.debug(f"Workflow: Output project - {project_id}")
