from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.langflow_mcp_service import LangflowMCPService
from utils.langflow_headers import build_mcp_global_vars_from_config


def _config(selected_provider: str):
    return SimpleNamespace(
        knowledge=SimpleNamespace(
            embedding_model="text-embedding-3-small",
            embedding_provider=selected_provider,
        ),
        providers=SimpleNamespace(
            openai=SimpleNamespace(api_key="openai-key", configured=True),
            anthropic=SimpleNamespace(api_key="anthropic-key", configured=True),
            watsonx=SimpleNamespace(api_key="wx-key", project_id="wx-proj", endpoint="https://wx", configured=True),
            ollama=SimpleNamespace(endpoint="http://localhost:11434", configured=True),
        ),
    )


def _config_single_provider(selected_provider: str):
    provider = selected_provider.lower().strip()
    return SimpleNamespace(
        knowledge=SimpleNamespace(
            embedding_model="text-embedding-3-small",
            embedding_provider=provider,
        ),
        providers=SimpleNamespace(
            openai=SimpleNamespace(
                api_key="openai-key" if provider == "openai" else "",
                configured=provider == "openai",
            ),
            anthropic=SimpleNamespace(
                api_key="anthropic-key" if provider == "anthropic" else "",
                configured=provider == "anthropic",
            ),
            watsonx=SimpleNamespace(
                api_key="wx-key" if provider == "watsonx" else "",
                project_id="wx-proj" if provider == "watsonx" else "",
                endpoint="https://wx",
                configured=provider == "watsonx",
            ),
            ollama=SimpleNamespace(
                endpoint="http://localhost:11434" if provider == "ollama" else "",
                configured=provider == "ollama",
            ),
        ),
    )


@pytest.mark.asyncio
async def test_build_mcp_global_vars_single_provider_selection_only_emits_that_provider():
    cfg = _config_single_provider("openai")

    vars_out = await build_mcp_global_vars_from_config(cfg, flows_service=None)

    assert vars_out["OPENAI_API_KEY"] == "openai-key"
    assert vars_out["SELECTED_EMBEDDING_MODEL"] == "text-embedding-3-small"
    assert "ANTHROPIC_API_KEY" not in vars_out
    assert "WATSONX_APIKEY" not in vars_out
    assert "WATSONX_PROJECT_ID" not in vars_out
    assert "OLLAMA_BASE_URL" not in vars_out


@pytest.mark.asyncio
async def test_build_mcp_global_vars_includes_all_configured_providers():
    cfg = _config("openai")

    vars_out = await build_mcp_global_vars_from_config(cfg, flows_service=None)

    assert vars_out["OPENAI_API_KEY"] == "openai-key"
    assert vars_out["ANTHROPIC_API_KEY"] == "anthropic-key"
    assert vars_out["WATSONX_APIKEY"] == "wx-key"
    assert vars_out["WATSONX_PROJECT_ID"] == "wx-proj"
    assert vars_out["OLLAMA_BASE_URL"].endswith(":11434")
    assert vars_out["SELECTED_EMBEDDING_MODEL"] == "text-embedding-3-small"


def test_patch_mcp_server_args_prunes_stale_provider_headers():
    svc = LangflowMCPService()
    existing_args = [
        "mcp-proxy",
        "--headers", "X-Langflow-Global-Var-OPENAI_API_KEY", "old-openai",
        "--headers", "X-Langflow-Global-Var-OLLAMA_BASE_URL", "http://localhost:11434",
        "--headers", "X-Langflow-Global-Var-WATSONX_APIKEY", "old-wx",
        "--headers", "X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL", "old-model",
    ]

    new_vars = {
        "OPENAI_API_KEY": "new-openai",
        "SELECTED_EMBEDDING_MODEL": "text-embedding-3-small",
    }
    updated = svc._upsert_global_var_headers_in_args(existing_args, new_vars)
    updated_joined = " ".join(updated)

    assert "X-Langflow-Global-Var-OPENAI_API_KEY new-openai" in updated_joined
    assert "X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL text-embedding-3-small" in updated_joined
    assert "X-Langflow-Global-Var-OLLAMA_BASE_URL" not in updated_joined
    assert "X-Langflow-Global-Var-WATSONX_APIKEY" not in updated_joined


@pytest.mark.asyncio
async def test_update_mcp_servers_applies_all_provider_credentials():
    svc = LangflowMCPService()

    server_detail = {
        "command": "uvx",
        "args": [
            "mcp-proxy",
            "--headers", "X-Langflow-Global-Var-OPENAI_API_KEY", "old-openai",
            "--headers", "X-Langflow-Global-Var-OLLAMA_BASE_URL", "http://localhost:11434",
            "--headers", "X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL", "old-model",
        ],
    }
    patch_resp = MagicMock(status_code=200, text="ok")

    async def _request(method, endpoint=None, **kwargs):
        if method == "GET" and endpoint == "/api/v2/mcp/servers":
            return MagicMock(status_code=200, json=lambda: [{"name": "lf-starter_project"}])
        if method == "GET" and endpoint == "/api/v2/mcp/servers/lf-starter_project":
            return MagicMock(status_code=200, json=lambda: server_detail)
        if method == "PATCH" and endpoint == "/api/v2/mcp/servers/lf-starter_project":
            args = kwargs["json"]["args"]
            args_joined = " ".join(args)
            assert "X-Langflow-Global-Var-OPENAI_API_KEY new-openai" in args_joined
            assert "X-Langflow-Global-Var-ANTHROPIC_API_KEY new-anthropic" in args_joined
            assert "X-Langflow-Global-Var-WATSONX_APIKEY new-wx" in args_joined
            assert "X-Langflow-Global-Var-WATSONX_PROJECT_ID new-wx-proj" in args_joined
            assert "X-Langflow-Global-Var-OLLAMA_BASE_URL http://localhost:11434" in args_joined
            assert "X-Langflow-Global-Var-SELECTED_EMBEDDING_MODEL text-embedding-3-small" in args_joined
            return patch_resp
        raise AssertionError(f"unexpected call: {method} {endpoint}")

    with patch("services.langflow_mcp_service.clients.langflow_request", new=AsyncMock(side_effect=_request)):
        result = await svc.update_mcp_servers_with_global_vars(
            {
                "OPENAI_API_KEY": "new-openai",
                "ANTHROPIC_API_KEY": "new-anthropic",
                "WATSONX_APIKEY": "new-wx",
                "WATSONX_PROJECT_ID": "new-wx-proj",
                "OLLAMA_BASE_URL": "http://localhost:11434",
                "SELECTED_EMBEDDING_MODEL": "text-embedding-3-small",
            }
        )

    assert result == {"updated": 1, "failed": 0, "total": 1}
