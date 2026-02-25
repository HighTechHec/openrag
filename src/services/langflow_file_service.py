from typing import Any, Dict, List, Optional

from config.settings import LANGFLOW_INGEST_FLOW_ID, clients
from utils.logging_config import get_logger

logger = get_logger(__name__)


class LangflowFileService:
    def __init__(self):
        self.flow_id_ingest = LANGFLOW_INGEST_FLOW_ID

    async def upload_user_file(
        self, file_tuple, jwt_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upload a file using Langflow Files API v2: POST /api/v2/files.
        Returns JSON with keys: id, name, path, size, provider.
        """
        logger.debug("[LF] Upload (v2) -> /api/v2/files")
        resp = await clients.langflow_request(
            "POST",
            "/api/v2/files",
            files={"file": file_tuple},
            headers={"Content-Type": None},
        )
        logger.debug(
            "[LF] Upload response",
            status_code=resp.status_code,
            reason=resp.reason_phrase,
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Upload failed",
                status_code=resp.status_code,
                reason=resp.reason_phrase,
                body=resp.text,
            )
        resp.raise_for_status()
        return resp.json()

    async def delete_user_file(self, file_id: str) -> None:
        """Delete a file by id using v2: DELETE /api/v2/files/{id}."""
        # NOTE: use v2 root, not /api/v1
        logger.debug("[LF] Delete (v2) -> /api/v2/files/{id}", file_id=file_id)
        resp = await clients.langflow_request("DELETE", f"/api/v2/files/{file_id}")
        logger.debug(
            "[LF] Delete response",
            status_code=resp.status_code,
            reason=resp.reason_phrase,
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Delete failed",
                status_code=resp.status_code,
                reason=resp.reason_phrase,
                body=resp.text[:500],
            )
        resp.raise_for_status()

    async def run_ingestion_flow(
        self,
        file_paths: List[str],
        file_tuples: list[tuple[str, str, str]],
        jwt_token: str,
        session_id: Optional[str] = None,
        runtime_vars: Optional[Dict[str, Any]] = None,
        owner: Optional[str] = None,
        owner_name: Optional[str] = None,
        owner_email: Optional[str] = None,
        connector_type: Optional[str] = None,
        document_id: Optional[str] = None,
        source_url: Optional[str] = None,
        allowed_users: Optional[List[str]] = None,
        allowed_groups: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Trigger the ingestion flow with provided file paths.
        The flow must expose a File component path in input schema or accept files parameter.
        """
        if not self.flow_id_ingest:
            logger.error("[LF] LANGFLOW_INGEST_FLOW_ID is not configured")
            raise ValueError("LANGFLOW_INGEST_FLOW_ID is not configured")

        payload: Dict[str, Any] = {
            "input_value": "Ingest files",
            "input_type": "chat",
            "output_type": "text",  # Changed from "json" to "text"
        }
        if not jwt_token:
            logger.warning("[LF] No JWT token provided")
        if session_id:
            payload["session_id"] = session_id

        logger.debug(
            "[LF] Run ingestion -> /run/%s | files=%s session_id=%s jwt_present=%s",
            self.flow_id_ingest,
            len(file_paths) if file_paths else 0,
            session_id,
            bool(jwt_token),
        )
        # To compute the file size in bytes, use len() on the file content (which should be bytes)
        file_size_bytes = len(file_tuples[0][1]) if file_tuples and len(file_tuples[0]) > 1 else 0
        # Avoid logging full payload to prevent leaking sensitive data (e.g., JWT)

        # Extract file metadata if file_tuples is provided
        filename = str(file_tuples[0][0]) if file_tuples and len(file_tuples) > 0 else ""
        mimetype = str(file_tuples[0][2]) if file_tuples and len(file_tuples) > 0 and len(file_tuples[0]) > 2 else ""

        # Get the current embedding model and provider credentials from config
        from config.settings import get_openrag_config
        from utils.langflow_headers import build_langflow_run_headers
        
        config = get_openrag_config()
        embedding_model = config.knowledge.embedding_model

        header_runtime_vars: Dict[str, Any] = {
            "JWT": jwt_token,
            "OWNER": owner,
            "OWNER_NAME": owner_name,
            "OWNER_EMAIL": owner_email,
            "CONNECTOR_TYPE": connector_type,
            "FILE_PATH": file_paths[0] if file_paths else None,
            "FILENAME": filename,
            "MIMETYPE": mimetype,
            "FILESIZE": file_size_bytes,
            "SELECTED_EMBEDDING_MODEL": embedding_model,
            "DOCUMENT_ID": document_id,
            "SOURCE_URL": source_url,
        }

        # Serialize ACL lists as JSON strings for Langflow global vars
        # (flows will parse these back into lists before indexing)
        if allowed_users is not None:
            header_runtime_vars["ALLOWED_USERS"] = allowed_users or []
        if allowed_groups is not None:
            header_runtime_vars["ALLOWED_GROUPS"] = allowed_groups or []
        if runtime_vars:
            header_runtime_vars.update(runtime_vars)

        headers = build_langflow_run_headers(
            config=config,
            runtime_vars=header_runtime_vars,
            scope="ingest",
        )
        logger.info(f"[LF] Headers {headers}")
        logger.info(f"[LF] Payload {payload}")
        resp = await clients.langflow_request(
            "POST",
            f"/api/v1/run/{self.flow_id_ingest}",
            json=payload,
            headers=headers,
        )
        logger.debug(
            "[LF] Run response", status_code=resp.status_code, reason=resp.reason_phrase
        )
        if resp.status_code >= 400:
            logger.error(
                "[LF] Run failed",
                status_code=resp.status_code,
                reason=resp.reason_phrase,
                body=resp.text[:1000],
            )
        resp.raise_for_status()
        
        # Check if response is actually JSON before parsing
        content_type = resp.headers.get("content-type", "")
        if "application/json" not in content_type:
            logger.error(
                "[LF] Unexpected response content type from Langflow",
                content_type=content_type,
                status_code=resp.status_code,
                body=resp.text[:1000],
            )
            raise ValueError(
                f"Langflow returned {content_type} instead of JSON. "
                f"This may indicate the ingestion flow failed or the endpoint is incorrect. "
                f"Response preview: {resp.text[:500]}"
            )
        
        try:
            resp_json = resp.json()
        except Exception as e:
            logger.error(
                "[LF] Failed to parse run response as JSON",
                body=resp.text[:1000],
                error=str(e),
            )

            raise
        return resp_json

    async def upload_and_ingest_file(
        self,
        file_tuple,
        session_id: Optional[str] = None,
        runtime_vars: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
        jwt_token: Optional[str] = None,
        delete_after_ingest: bool = True,
        owner: Optional[str] = None,
        owner_name: Optional[str] = None,
        owner_email: Optional[str] = None,
        connector_type: Optional[str] = None,   
    ) -> Dict[str, Any]:
        """
        Combined upload, ingest, and delete operation.
        First uploads the file, then runs ingestion on it, then optionally deletes the file.

        Args:
            file_tuple: File tuple (filename, content, content_type)
            session_id: Optional session ID for the ingestion flow
            runtime_vars: Optional runtime global variables for the ingestion flow
            settings: Optional UI settings to convert to runtime global variables
            jwt_token: Optional JWT token for authentication
            delete_after_ingest: Whether to delete the file from Langflow after ingestion (default: True)

        Returns:
            Combined result with upload info, ingestion result, and deletion status
        """
        logger.debug("[LF] Starting combined upload and ingest operation")

        # Step 1: Upload the file
        try:
            upload_result = await self.upload_user_file(file_tuple, jwt_token=jwt_token)
            logger.debug(
                "[LF] Upload completed successfully",
                extra={
                    "file_id": upload_result.get("id"),
                    "file_path": upload_result.get("path"),
                },
            )
        except Exception as e:
            logger.error(
                "[LF] Upload failed during combined operation", extra={"error": str(e)}
            )
            raise Exception(f"Upload failed: {str(e)}")

        # Step 2: Prepare for ingestion
        file_path = upload_result.get("path")
        if not file_path:
            raise ValueError("Upload successful but no file path returned")

        final_runtime_vars: Dict[str, Any] = runtime_vars.copy() if runtime_vars else {}

        if settings:
            logger.debug(
                "[LF] Applying ingestion settings", extra={"settings": settings}
            )

            if settings.get("chunkSize"):
                final_runtime_vars["CHUNK_SIZE"] = settings["chunkSize"]
            if settings.get("chunkOverlap"):
                final_runtime_vars["CHUNK_OVERLAP"] = settings["chunkOverlap"]
            if settings.get("separator"):
                final_runtime_vars["SEPARATOR"] = settings["separator"]
            if settings.get("embeddingModel"):
                final_runtime_vars["SELECTED_EMBEDDING_MODEL"] = settings["embeddingModel"]

            logger.debug(
                "[LF] Runtime vars with settings applied",
                extra={"runtime_vars": final_runtime_vars},
            )

        # Step 3: Run ingestion
        try:
            ingest_result = await self.run_ingestion_flow(
                file_paths=[file_path],
                file_tuples=[file_tuple],
                jwt_token=jwt_token,
                session_id=session_id,
                runtime_vars=final_runtime_vars,
                owner=owner,
                owner_name=owner_name,
                owner_email=owner_email,
                connector_type=connector_type,
            )
            logger.debug("[LF] Ingestion completed successfully")
        except Exception as e:
            logger.error(
                "[LF] Ingestion failed during combined operation",
                extra={"error": str(e), "file_path": file_path},
            )
            # Note: We could optionally delete the uploaded file here if ingestion fails
            raise Exception(f"Ingestion failed: {str(e)}")

        # Step 4: Delete file from Langflow (optional)
        file_id = upload_result.get("id")
        delete_result = None
        delete_error = None

        if delete_after_ingest and file_id:
            try:
                logger.debug(
                    "[LF] Deleting file after successful ingestion",
                    extra={"file_id": file_id},
                )
                await self.delete_user_file(file_id)
                delete_result = {"status": "deleted", "file_id": file_id}
                logger.debug("[LF] File deleted successfully")
            except Exception as e:
                delete_error = str(e)
                logger.warning(
                    "[LF] Failed to delete file after ingestion",
                    extra={"error": delete_error, "file_id": file_id},
                )
                delete_result = {
                    "status": "delete_failed",
                    "file_id": file_id,
                    "error": delete_error,
                }

        # Return combined result
        result = {
            "status": "success",
            "upload": upload_result,
            "ingestion": ingest_result,
            "message": f"File '{upload_result.get('name')}' uploaded and ingested successfully",
        }

        if delete_after_ingest:
            result["deletion"] = delete_result
            if delete_result and delete_result.get("status") == "deleted":
                result["message"] += " and cleaned up"
            elif delete_error:
                result["message"] += f" (cleanup warning: {delete_error})"

        return result
