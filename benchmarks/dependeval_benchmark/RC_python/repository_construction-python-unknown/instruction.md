
## Code to Analyze

```
'katana-skipper/api/api/tasks.py'
:from .worker import app
from skipper_lib.events.event_producer import EventProducer
from celery.utils.log import get_task_logger
import json
import skipper_lib.workflow.workflow_helper as workflow_helper
import os


celery_log = get_task_logger(__name__)


@app.task(name='api.process_workflow')
def process_workflow(payload):
    payload_json = json.loads(payload)
    task_type = payload_json['task_type']

    queue_name = workflow_helper.call(task_type,
                                      os.getenv('WORKFLOW_URL',
                                                'http://127.0.0.1:5000/api/v1/skipper/workflow/'),
                                      '_async')

    if queue_name is '-':
        return

    event_producer = EventProducer(username=os.getenv('RABBITMQ_USER', 'skipper'),
                                   password=os.getenv('RABBITMQ_PASSWORD', 'welcome1'),
                                   host=os.getenv('RABBITMQ_HOST', '127.0.0.1'),
                                   port=os.getenv('RABBITMQ_PORT', 5672),
                                   service_name='api_async',
                                   logger=os.getenv('LOGGER_PRODUCER_URL',
                                                    'http://127.0.0.1:5001/api/v1/skipper/logger/log_producer'))
    response = event_producer.call(queue_name, payload)
    response_json = json.loads(response)

    celery_log.info(task_type + " task completed")
    return response_json

'katana-skipper/skipper-lib/skipper_lib/workflow/workflow_helper.py'
:import requests


def call(task_type, url, mode):
    valid = {'_sync', '_async'}
    if mode not in valid:
        raise ValueError("call: status must be one of %r." % valid)

    r = requests.get(url + task_type + mode)
    queue_name = r.json()['queue_name']
    return queue_name

'katana-skipper/api/endpoint.py'
:from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers import skipper, boston, mobilenet
import os

app = FastAPI(openapi_url="/api/v1/skipper/tasks/openapi.json",
              docs_url="/api/v1/skipper/tasks/docs")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

boston_enabled = os.getenv('BOSTON_ENABLED', 'y')
mobilenet_enabled = os.getenv('MOBILENET_ENABLED', 'y')

app.include_router(skipper.router, prefix='/api/v1/skipper/tasks')
if boston_enabled == 'y':
    app.include_router(boston.router, prefix='/api/v1/skipper/tasks')
if mobilenet_enabled == 'y':
    app.include_router(mobilenet.router, prefix='/api/v1/skipper/tasks')

'katana-skipper/api/api/routers/boston.py'
:from fastapi import APIRouter
from ..models import WorkflowTask, WorkflowTaskResult, WorkflowTaskCancelled
from ..models import WorkflowTaskDataTraining, WorkflowTaskDataPredict
from ..tasks import process_workflow
from ..dependencies import sync_request_helper
from celery.result import AsyncResult
from fastapi.responses import JSONResponse

router = APIRouter(
    prefix='/boston',
    tags=['boston']
)


@router.post('/task_training', response_model=WorkflowTask, status_code=202)
def task_training(workflow_task_data: WorkflowTaskDataTraining):
    payload = workflow_task_data.json()

    task_id = process_workflow.delay(payload)

    return {'task_id': str(task_id),
            'task_status': 'Processing'}


@router.get('/{task_id}', response_model=WorkflowTaskResult, status_code=202,
            responses={202: {'model': WorkflowTask, 'description': 'Accepted: Not Ready'}})
async def task_status(task_id):
    task = AsyncResult(task_id)
    if not task.ready():
        return JSONResponse(status_code=202,
                            content={'task_id': str(task_id),
                                     'task_status': 'Processing'})
    result = task.get()
    return {'task_id': task_id,
            'task_status': 'Success',
            'outcome': str(result)}


@router.post('/task_predict', response_model=WorkflowTaskResult, status_code=202,
             responses={202: {'model': WorkflowTaskCancelled, 'description': 'Accepted: Not Ready'}})
def task_predict(workflow_task_data: WorkflowTaskDataPredict):
    response = sync_request_helper(workflow_task_data)

    return {'task_id': '-',
            'task_status': 'Success',
            'outcome': str(response)}

```

# Repository Construction Task

## Problem Statement



## Task Description

Your task is to build a call chain graph that represents the function invocation relationships across the repository. Analyze the code to understand how functions call each other and construct a directed graph representation.

## Repository Information

- **Repository**: N/A
- **Language**: python

## Output Format

Write your answer to `/workspace/submission.json` as a JSON object representing the call graph:

```json
{
  "function1": ["function2", "function3"],
  "function2": ["function4"],
  "function3": [],
  "function4": []
}
```

### Structure:

- **Keys**: Function names (callers)
- **Values**: Arrays of function names that are called by the key function (callees)
- **Empty arrays**: Functions that don't call any other functions
- **Isolated nodes**: Include functions that are never called but exist in the repository

### Alternative Format (List of Edges):

You can also use an edge list format:

```json
[
  {"caller": "function1", "callee": "function2"},
  {"caller": "function1", "callee": "function3"},
  {"caller": "function2", "callee": "function4"}
]
```

## Evaluation

Your submission will be evaluated using graph similarity metrics:

- **Node F1**: Precision and recall of identified functions (15% weight)
- **Edge F1**: Precision and recall of call relationships (85% weight)
- **Final Score**: 0.15 × Node_F1 + 0.85 × Edge_F1

The evaluation emphasizes getting the call relationships correct over identifying all functions.

## Tips

- Focus on accurately identifying which functions call which
- Include all functions in the repository, even if they have no outgoing calls
- Pay attention to indirect calls through variables or callbacks
- Consider method calls on objects and class methods
- Cross-file function calls are especially important
