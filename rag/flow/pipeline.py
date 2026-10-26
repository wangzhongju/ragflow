#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
import asyncio
import datetime
import json
import logging
import random
from timeit import default_timer as timer
from agent.canvas import Graph
from api.db.services.document_service import DocumentService
from api.db.services.task_service import has_canceled, TaskService, CANVAS_DEBUG_DOC_ID
from rag.utils.redis_conn import REDIS_CONN


class Pipeline(Graph):
    def __init__(self, dsl: str | dict, tenant_id=None, doc_id=None, task_id=None, flow_id=None, language=None):
        if isinstance(dsl, dict):
            dsl = json.dumps(dsl, ensure_ascii=False)
        super().__init__(dsl, tenant_id, task_id)
        if doc_id == CANVAS_DEBUG_DOC_ID:
            doc_id = None
        self._doc_id = doc_id
        self._flow_id = flow_id
        self._language = language
        self._component_progress: dict[str, float] = {}
        self._last_log_component = None
        self._kb_id = None
        if self._doc_id:
            self._kb_id = DocumentService.get_knowledgebase_id(doc_id)
            if not self._kb_id:
                self._doc_id = None

    def callback(self, component_name: str, progress: float | int | None = None, message: str = "") -> None:
        from common.exceptions import TaskCanceledException

        log_key = f"{self._flow_id}-{self.task_id}-logs"
        timestamp = timer()
        if has_canceled(self.task_id):
            progress = -1
            message += "[CANCEL]"
        # Running task state must outlive the short-lived Redis trace cache.
        if component_name in self.components and progress is not None:
            previous = self._component_progress.get(component_name, 0.0)
            self._component_progress[component_name] = -1 if previous < 0 or progress < 0 else max(previous, min(progress, 1.0))
        message = str(message or "")
        now = datetime.datetime.now().strftime("%H:%M:%S")
        if component_name != "END" and self._doc_id and self.task_id:
            finished = -1 if any(value < 0 for value in self._component_progress.values()) else sum(self._component_progress.values()) / max(1, len(self.components))
            msg = ""
            if message.strip():
                if self._last_log_component != component_name:
                    msg = f"\n-------------------------------------\n[{self.get_component_name(component_name)}]:\n"
                msg += f"{now}: {message}\n"
            try:
                TaskService.update_progress(self.task_id, {"progress": finished, "progress_msg": msg})
            except Exception:
                logging.getLogger(__name__).exception("Failed to update pipeline task progress for %s", self.task_id)

        # Numeric-only updates advance the task without timestamp-only log lines.
        if not message.strip():
            if has_canceled(self.task_id):
                raise TaskCanceledException(message)
            return
        self._last_log_component = component_name
        try:
            bin = REDIS_CONN.get(log_key)
            obj = json.loads(bin.encode("utf-8")) if bin else []
            if obj:
                if obj[-1]["component_id"] == component_name:
                    obj[-1]["trace"].append(
                        {
                            "progress": progress,
                            "message": message,
                            "datetime": datetime.datetime.now().strftime("%H:%M:%S"),
                            "timestamp": timestamp,
                            "elapsed_time": timestamp - obj[-1]["trace"][-1]["timestamp"],
                        }
                    )
                else:
                    obj.append(
                        {
                            "component_id": component_name,
                            "trace": [{"progress": progress, "message": message, "datetime": datetime.datetime.now().strftime("%H:%M:%S"), "timestamp": timestamp, "elapsed_time": 0}],
                        }
                    )
            else:
                obj = [
                    {
                        "component_id": component_name,
                        "trace": [{"progress": progress, "message": message, "datetime": datetime.datetime.now().strftime("%H:%M:%S"), "timestamp": timestamp, "elapsed_time": 0}],
                    }
                ]
            if component_name == "END" and not self._doc_id:
                obj[-1]["trace"][-1]["dsl"] = json.loads(str(self))
            REDIS_CONN.set_obj(log_key, obj, 60 * 30)

        except Exception as e:
            logging.exception(e)

        if has_canceled(self.task_id):
            raise TaskCanceledException(message)

    def fetch_logs(self):
        log_key = f"{self._flow_id}-{self.task_id}-logs"
        try:
            bin = REDIS_CONN.get(log_key)
            if bin:
                return json.loads(bin.encode("utf-8"))
        except Exception as e:
            logging.exception(e)
        return []

    async def run(self, **kwargs):
        self._component_progress.clear()
        self._last_log_component = None
        log_key = f"{self._flow_id}-{self.task_id}-logs"
        try:
            REDIS_CONN.set_obj(log_key, [], 60 * 10)
        except Exception as e:
            logging.exception(e)
        self.error = ""
        if not self.path:
            self.path.append("File")
            cpn_obj = self.get_component_obj(self.path[0])
            await cpn_obj.invoke(**kwargs)
            if cpn_obj.error():
                self.error = "[ERROR]" + cpn_obj.error()
                self.callback(cpn_obj.component_name, -1, self.error)

        if self._doc_id:
            TaskService.update_progress(
                self.task_id, {"progress": random.randint(0, 5) / 100.0, "progress_msg": "Start the pipeline...", "begin_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            )

        idx = len(self.path) - 1
        cpn_obj = self.get_component_obj(self.path[idx])
        idx += 1
        self.path.extend(cpn_obj.get_downstream())

        while idx < len(self.path) and not self.error:
            last_cpn = self.get_component_obj(self.path[idx - 1])
            cpn_obj = self.get_component_obj(self.path[idx])

            async def invoke():
                nonlocal last_cpn, cpn_obj
                await cpn_obj.invoke(**last_cpn.output())

            tasks = []
            tasks.append(asyncio.create_task(invoke()))
            await asyncio.gather(*tasks)

            if cpn_obj.error():
                self.error = "[ERROR]" + cpn_obj.error()
                self.callback(cpn_obj._id, -1, self.error)
                break
            idx += 1
            self.path.extend(cpn_obj.get_downstream())

        self.callback("END", 1 if not self.error else -1, json.dumps(self.get_component_obj(self.path[-1]).output(), ensure_ascii=False))

        if not self.error:
            return self.get_component_obj(self.path[-1]).output()

        TaskService.update_progress(self.task_id, {"progress": -1, "progress_msg": f"[ERROR]: {self.error}"})

        return {}
