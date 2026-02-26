"""Shared helper functions for integration tests.

Both test_api_endpoints.py and test_anthropic_endpoints.py import from here
so that polling / readiness / env-setup logic is defined in one place.
"""

import asyncio
import os
import subprocess
import sys

import httpx

from config.model_constants import OPENAI_DEFAULT_EMBEDDING_MODEL


def dump_docker_logs(container_name_pattern: str = "langflow", tail: int = 100):
    """Dump Docker container logs for debugging."""
    try:
        find_cmd = ["docker", "ps", "-a", "--filter", f"name={container_name_pattern}", "--format", "{{.ID}}"]
        result = subprocess.run(find_cmd, capture_output=True, text=True, timeout=5)
        container_ids = result.stdout.strip().split('\n')

        if not container_ids or not container_ids[0]:
            print(f"[DEBUG] No Docker containers found matching pattern: {container_name_pattern}")
            return

        for container_id in container_ids:
            if not container_id:
                continue
            print(f"\n{'='*80}")
            print(f"[DEBUG] Docker logs for container {container_id} (last {tail} lines):")
            print(f"{'='*80}")

            logs_cmd = ["docker", "logs", "--tail", str(tail), container_id]
            logs_result = subprocess.run(logs_cmd, capture_output=True, text=True, timeout=10)
            print(logs_result.stdout)
            if logs_result.stderr:
                print("[STDERR]:", logs_result.stderr)
            print(f"{'='*80}\n")
    except subprocess.TimeoutExpired:
        print(f"[DEBUG] Timeout while fetching docker logs for {container_name_pattern}")
    except Exception as e:
        print(f"[DEBUG] Failed to fetch docker logs for {container_name_pattern}: {e}")


async def wait_for_service_ready(client: httpx.AsyncClient, timeout_s: float = 30.0):
    """Poll existing endpoints until the app and OpenSearch are ready.

    Strategy:
    - GET /auth/me should return 200 immediately (confirms app is up).
    - POST /search with query "*" avoids embeddings and checks OpenSearch/index readiness.
    """
    from session_manager import SessionManager, AnonymousUser
    import hashlib
    import jwt as jwt_lib
    sm = SessionManager("test")
    test_token = sm.create_jwt_token(AnonymousUser())
    token_hash = hashlib.sha256(test_token.encode()).hexdigest()[:16]
    print(f"[DEBUG] Generated test JWT token hash: {token_hash}")
    print(f"[DEBUG] Using key paths: private={sm.private_key_path}, public={sm.public_key_path}")
    with open(sm.public_key_path, 'rb') as f:
        pub_key_hash = hashlib.sha256(f.read()).hexdigest()[:16]
    print(f"[DEBUG] Public key hash: {pub_key_hash}")
    decoded = jwt_lib.decode(test_token, options={"verify_signature": False})
    print(f"[DEBUG] JWT claims: iss={decoded.get('iss')}, sub={decoded.get('sub')}, aud={decoded.get('aud')}, roles={decoded.get('roles')}")

    opensearch_url = f"https://{os.getenv('OPENSEARCH_HOST', 'localhost')}:{os.getenv('OPENSEARCH_PORT', '9200')}"
    print(f"[DEBUG] Testing JWT auth directly against: {opensearch_url}/documents/_search")
    async with httpx.AsyncClient(verify=False) as os_client:
        r_os = await os_client.post(
            f"{opensearch_url}/documents/_search",
            headers={"Authorization": f"Bearer {test_token}"},
            json={"query": {"match_all": {}}, "size": 0}
        )
        print(f"[DEBUG] Direct OpenSearch JWT test: status={r_os.status_code}, body={r_os.text[:500]}")
        if r_os.status_code == 401:
            print("[DEBUG] OpenSearch rejected JWT! OIDC config not working.")
        else:
            print("[DEBUG] OpenSearch accepted JWT!")

    deadline = asyncio.get_event_loop().time() + timeout_s
    last_err = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            r1 = await client.get("/auth/me")
            print(f"[DEBUG] /auth/me status={r1.status_code}, body={r1.text[:200]}")
            if r1.status_code in (401, 403):
                raise AssertionError(f"/auth/me returned {r1.status_code}: {r1.text}")
            if r1.status_code != 200:
                await asyncio.sleep(0.5)
                continue
            r2 = await client.post("/search", json={"query": "*", "limit": 0})
            print(f"[DEBUG] /search status={r2.status_code}, body={r2.text[:200]}")
            if r2.status_code in (401, 403):
                print(f"[DEBUG] Search failed with auth error. Response: {r2.text}")
                raise AssertionError(f"/search returned {r2.status_code}: {r2.text}")
            if r2.status_code == 200:
                print("[DEBUG] Service ready!")
                return
            last_err = r2.text
        except AssertionError:
            raise
        except Exception as e:
            last_err = str(e)
            print(f"[DEBUG] Exception during readiness check: {e}")
        await asyncio.sleep(0.5)
    raise AssertionError(f"Service not ready in time: {last_err}")


async def wait_for_task_completion(
    client: httpx.AsyncClient, task_id: str, timeout_s: float = 180.0
) -> dict:
    """Poll /tasks/{task_id} until the task completes or fails."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_payload = None
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/tasks/{task_id}")
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                last_payload = resp.text
            else:
                status = (data.get("status") or "").lower()
                if status == "completed":
                    return data
                if status == "failed":
                    raise AssertionError(f"Task {task_id} failed: {data}")
                last_payload = data
        elif resp.status_code == 404:
            last_payload = resp.text
        else:
            last_payload = resp.text
        await asyncio.sleep(1.0)
    raise AssertionError(
        f"Task {task_id} did not complete in time. Last payload: {last_payload}"
    )


async def wait_for_langflow_chat(
    client: httpx.AsyncClient, payload: dict, timeout_s: float = 120.0
) -> dict:
    """Poll /langflow until a non-empty response is returned."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_payload = None
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.post("/langflow", json=payload)
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                last_payload = resp.text
            else:
                response_text = data.get("response")
                if isinstance(response_text, str) and response_text.strip():
                    return data
                last_payload = data
        else:
            last_payload = resp.text
        await asyncio.sleep(1.0)

    print("\n[DEBUG] /langflow timed out. Dumping Langflow container logs...")
    dump_docker_logs(container_name_pattern="langflow", tail=200)
    raise AssertionError(f"/langflow never returned a usable response. Last payload: {last_payload}")


async def wait_for_nudges(
    client: httpx.AsyncClient, chat_id: str | None = None, timeout_s: float = 90.0
) -> dict:
    """Poll /nudges until a non-empty response is returned."""
    endpoint = "/nudges" if not chat_id else f"/nudges/{chat_id}"
    deadline = asyncio.get_event_loop().time() + timeout_s
    last_payload = None
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(endpoint)
        if resp.status_code == 200:
            try:
                data = resp.json()
            except Exception:
                last_payload = resp.text
            else:
                response_text = data.get("response")
                if isinstance(response_text, str) and response_text.strip():
                    return data
                last_payload = data
        else:
            last_payload = resp.text
        await asyncio.sleep(1.0)

    print(f"\n[DEBUG] {endpoint} timed out. Dumping Langflow container logs...")
    dump_docker_logs(container_name_pattern="langflow", tail=200)
    raise AssertionError(f"{endpoint} never returned a usable response. Last payload: {last_payload}")


COMMON_MODULES_TO_CLEAR = [
    "api.router",
    "api.connector_router",
    "config.settings",
    "auth_middleware",
    "main",
    "api",
    "services",
    "services.search_service",
]


def clear_cached_modules(extra: list[str] | None = None):
    """Remove cached modules so that fresh env vars / settings are picked up."""
    modules = list(COMMON_MODULES_TO_CLEAR)
    if extra:
        modules.extend(extra)
    for mod in modules:
        sys.modules.pop(mod, None)


async def create_app_with_clean_index():
    """Create the ASGI app, run startup tasks, ensure a clean OpenSearch index."""
    from main import create_app, startup_tasks
    from config.settings import clients, get_index_name

    await clients.initialize()
    try:
        await clients.opensearch.indices.delete(index=get_index_name())
        await asyncio.sleep(1)
    except Exception:
        pass

    app = await create_app()
    await startup_tasks(app.state.services)

    from main import _ensure_opensearch_index
    await _ensure_opensearch_index()

    try:
        count_response = await clients.opensearch.count(index=get_index_name())
        doc_count = count_response.get('count', 0)
        assert doc_count == 0, f"Index should be empty after startup but contains {doc_count} documents"
    except Exception:
        pass

    return app


def set_common_test_env(
    disable_langflow_ingest: bool = True,
    embedding_provider: str = "openai",
    embedding_model: str = OPENAI_DEFAULT_EMBEDDING_MODEL,
    llm_provider: str | None = None,
    llm_model: str | None = None,
):
    """Set environment variables commonly needed by integration tests."""
    os.environ["DISABLE_INGEST_WITH_LANGFLOW"] = "true" if disable_langflow_ingest else "false"
    os.environ["DISABLE_STARTUP_INGEST"] = "true"
    os.environ["EMBEDDING_MODEL"] = embedding_model
    os.environ["EMBEDDING_PROVIDER"] = embedding_provider
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = ""
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = ""
    if llm_provider:
        os.environ["LLM_PROVIDER"] = llm_provider
    if llm_model:
        os.environ["LLM_MODEL"] = llm_model
