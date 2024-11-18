# Copyright 2024 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import uuid
from contextvars import ContextVar
from typing import List, Dict, Optional

from code_interpreter.utils.validation import AbsolutePath, Hash
from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from code_interpreter.services.storage import Storage
from code_interpreter.services.custom_tool_executor import (
    CustomToolExecuteError,
    CustomToolExecutor,
    CustomToolParseError,
)
from code_interpreter.services.kubernetes_code_executor import KubernetesCodeExecutor

logger = logging.getLogger("code_interpreter_service")


class ExecuteRequest(BaseModel):
    source_file: AbsolutePath
    files: Dict[AbsolutePath, Hash]
    timeout: int = 60

class ExecuteResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    files: Dict[AbsolutePath, Hash]


class ParseCustomToolRequest(BaseModel):
    tool_source_code: str


class ParseCustomToolResponse(BaseModel):
    tool_name: str
    tool_input_schema_json: str
    tool_description: str


class ParseCustomToolErrorResponse(BaseModel):
    error_messages: List[str]


class ExecuteCustomToolRequest(BaseModel):
    tool_source_code: str
    tool_input_json: str


class ExecuteCustomToolResponse(BaseModel):
    tool_output_json: str


class ExecuteCustomToolErrorResponse(BaseModel):
    stderr: str


def create_http_server(
    code_executor: KubernetesCodeExecutor,
    custom_tool_executor: CustomToolExecutor,
    request_id_context_var: ContextVar[str],
    file_storage: Storage,
):
    app = FastAPI()

    def set_request_id():
        request_id = str(uuid.uuid4())
        request_id_context_var.set(request_id)
        return request_id
    
    @app.delete("/v1/files/{file_hash}")
    async def delete_file(
        file_hash: str,
        request_id: str = Depends(set_request_id)
    ):
        await file_storage.delete(file_hash)
        logger.info("Deleted file with hash %s", file_hash)
        return {"message": "File deleted"}

    @app.get("/v1/files/{file_hash}")
    async def get_file(
        file_hash: str,
        delete: bool = False,
        request_id: str = Depends(set_request_id)
    ):
        """Get file content by hash, with optional deletion after retrieval."""
        try:
            async with file_storage.reader(file_hash) as file_reader:
                content = await file_reader.read()
                
            if delete:
                await file_storage.delete(file_hash)
                logger.info("Deleted file with hash %s", file_hash)
                
            return Response(
                content=content,
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": f"attachment; filename={file_hash}"
                }
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"File with hash {file_hash} not found"
            )
        except Exception as e:
            logger.exception("Error retrieving file")
            raise HTTPException(status_code=500, detail=str(e))

    @app.put("/v1/files")
    async def write_file(
        file: UploadFile,
        request_id: str = Depends(set_request_id)
    ):
        """Write uploaded file data to storage and return the hash."""
        try:
            content = await file.read()
            stored_hash = await file_storage.write(content)
            logger.info("Wrote file with hash %s", stored_hash)
            return {"hash": stored_hash}
        except Exception as e:
            logger.exception("Error writing file")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/v1/execute", response_model=ExecuteResponse)
    async def execute(
        request: ExecuteRequest, request_id: str = Depends(set_request_id)
    ):
        logger.info(
            "Executing code with files %s: %s", request.files, request.source_file
        )
        try:
            result = await code_executor.execute(
                source_file=request.source_file,
                files=request.files,
                timeout=request.timeout,
            )
        except Exception as e:
            logger.exception("Error executing code")
            raise HTTPException(status_code=500, detail=str(e))
        logger.info("Code execution completed with result %s", result)
        return result

    @app.post(
        "/v1/parse-custom-tool",
        response_model=ParseCustomToolResponse,
    )
    async def parse_custom_tool(
        request: ParseCustomToolRequest, request_id: str = Depends(set_request_id)
    ):
        logger.info("Parsing custom tool with source code %s", request.tool_source_code)
        custom_tool = custom_tool_executor.parse(
            tool_source_code=request.tool_source_code
        )
        result = ParseCustomToolResponse(
            tool_name=custom_tool.name,
            tool_input_schema_json=json.dumps(custom_tool.input_schema),
            tool_description=custom_tool.description,
        )
        logger.info("Parsed custom tool %s", result)
        return result

    @app.exception_handler(CustomToolParseError)
    async def validation_exception_handler(request, e):
        logger.warning("Invalid custom tool: %s", e.errors)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ParseCustomToolErrorResponse(error_messages=e.errors).model_dump(),
        )

    @app.post(
        "/v1/execute-custom-tool",
        response_model=ExecuteCustomToolResponse,
    )
    async def execute_custom_tool(
        request: ExecuteCustomToolRequest,
        request_id: str = Depends(set_request_id),
    ):
        logger.info(
            "Executing custom tool with source code %s", request.tool_source_code
        )
        result = await custom_tool_executor.execute(
            tool_input=json.loads(request.tool_input_json),
            tool_source_code=request.tool_source_code,
        )
        logger.info("Executed custom tool with result %s", result)
        return ExecuteCustomToolResponse(tool_output_json=json.dumps(result))

    @app.exception_handler(CustomToolExecuteError)
    async def validation_exception_handler(request, e):
        logger.warning("Error executing custom tool: %s", e)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ExecuteCustomToolErrorResponse(stderr=str(e)).model_dump(),
        )

    return app
