from types import SimpleNamespace

from utils.langflow_headers import (
    build_langflow_run_headers,
    get_langflow_global_header_name,
)


def _mock_config():
    return SimpleNamespace(
        providers=SimpleNamespace(
            openai=SimpleNamespace(api_key="openai-key"),
            anthropic=SimpleNamespace(api_key="anthropic-key"),
            watsonx=SimpleNamespace(api_key="watsonx-key", project_id="watsonx-project"),
            ollama=SimpleNamespace(endpoint="http://localhost:11434"),
        ),
        knowledge=SimpleNamespace(embedding_model="text-embedding-3-large"),
    )


def test_build_langflow_run_headers_serializes_json_and_scalars():
    config = _mock_config()
    headers = build_langflow_run_headers(
        config=config,
        scope="ingest",
        runtime_vars={
            "JWT": "token-123",
            "ALLOWED_USERS": ["u1", "u2"],
            "CHUNK_SIZE": 1000,
            "OPENRAG_QUERY_FILTER": {"limit": 10},  # ignored in ingest scope
        },
    )

    assert headers[get_langflow_global_header_name("JWT")] == "token-123"
    assert headers[get_langflow_global_header_name("ALLOWED_USERS")] == '["u1", "u2"]'
    assert headers[get_langflow_global_header_name("CHUNK_SIZE")] == "1000"
    assert get_langflow_global_header_name("OPENRAG_QUERY_FILTER") not in headers


def test_build_langflow_run_headers_includes_provider_credentials():
    config = _mock_config()
    headers = build_langflow_run_headers(config=config, scope="chat", runtime_vars={})

    assert headers[get_langflow_global_header_name("OPENAI_API_KEY")] == "openai-key"
    assert headers[get_langflow_global_header_name("ANTHROPIC_API_KEY")] == "anthropic-key"
    assert headers[get_langflow_global_header_name("WATSONX_API_KEY")] == "watsonx-key"
    assert headers[get_langflow_global_header_name("WATSONX_PROJECT_ID")] == "watsonx-project"
    assert headers[get_langflow_global_header_name("OLLAMA_BASE_URL")].endswith(":11434")
