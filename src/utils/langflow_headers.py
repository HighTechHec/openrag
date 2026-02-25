"""Utility functions for building Langflow request headers."""

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Set

from utils.container_utils import transform_localhost_url

LANGFLOW_GLOBAL_HEADER_PREFIX = "X-Langflow-Global-Var-"
SERIALIZER_STRING = "string"
SERIALIZER_JSON = "json"


@dataclass(frozen=True)
class GlobalVarDefinition:
    required: bool = False
    serializer: str = SERIALIZER_STRING
    scopes: frozenset[str] = frozenset({"all"})


# Centralized Langflow runtime global-variable registry.
# Add new global variables here to make passthrough scalable.
LANGFLOW_GLOBAL_VAR_REGISTRY: Dict[str, GlobalVarDefinition] = {
    # Auth and ownership
    "JWT": GlobalVarDefinition(scopes=frozenset({"chat", "nudges", "ingest"})),
    "OWNER": GlobalVarDefinition(scopes=frozenset({"chat", "nudges", "ingest"})),
    "OWNER_NAME": GlobalVarDefinition(scopes=frozenset({"chat", "nudges", "ingest"})),
    "OWNER_EMAIL": GlobalVarDefinition(scopes=frozenset({"chat", "nudges", "ingest"})),
    "CONNECTOR_TYPE": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    # File/document context
    "FILE_PATH": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    "FILENAME": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    "MIMETYPE": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    "FILESIZE": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    "DOCUMENT_ID": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    "SOURCE_URL": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    "IS_SAMPLE_DATA": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    # ACL
    "ALLOWED_USERS": GlobalVarDefinition(
        serializer=SERIALIZER_JSON, scopes=frozenset({"ingest"})
    ),
    "ALLOWED_GROUPS": GlobalVarDefinition(
        serializer=SERIALIZER_JSON, scopes=frozenset({"ingest"})
    ),
    # Knowledge/query runtime controls
    "SELECTED_EMBEDDING_MODEL": GlobalVarDefinition(
        scopes=frozenset({"chat", "nudges", "ingest"})
    ),
    "CHUNK_SIZE": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    "CHUNK_OVERLAP": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    "SEPARATOR": GlobalVarDefinition(scopes=frozenset({"ingest"})),
    "OPENRAG_QUERY_FILTER": GlobalVarDefinition(
        serializer=SERIALIZER_JSON, scopes=frozenset({"chat", "nudges"})
    ),
    # Provider credentials
    "OPENAI_API_KEY": GlobalVarDefinition(scopes=frozenset({"all"})),
    "ANTHROPIC_API_KEY": GlobalVarDefinition(scopes=frozenset({"all"})),
    "WATSONX_API_KEY": GlobalVarDefinition(scopes=frozenset({"all"})),
    "WATSONX_PROJECT_ID": GlobalVarDefinition(scopes=frozenset({"all"})),
    "OLLAMA_BASE_URL": GlobalVarDefinition(scopes=frozenset({"all"})),
}


def _is_scope_allowed(definition: GlobalVarDefinition, scope: Optional[str]) -> bool:
    if scope is None:
        return True
    return "all" in definition.scopes or scope in definition.scopes


def _serialize_value(value: Any, serializer: str) -> str:
    if serializer == SERIALIZER_JSON:
        return json.dumps(value)
    return str(value)


def get_langflow_global_header_name(key: str) -> str:
    """Build a Langflow global-variable header name from a key."""
    return f"{LANGFLOW_GLOBAL_HEADER_PREFIX}{key.upper()}"


def build_provider_global_vars(config) -> Dict[str, Any]:
    """Build provider credential globals from OpenRAG config."""
    provider_vars: Dict[str, Any] = {}
    if config.providers.openai.api_key:
        provider_vars["OPENAI_API_KEY"] = config.providers.openai.api_key
    if config.providers.anthropic.api_key:
        provider_vars["ANTHROPIC_API_KEY"] = config.providers.anthropic.api_key
    if config.providers.watsonx.api_key:
        provider_vars["WATSONX_API_KEY"] = config.providers.watsonx.api_key
    if config.providers.watsonx.project_id:
        provider_vars["WATSONX_PROJECT_ID"] = config.providers.watsonx.project_id
    if config.providers.ollama.endpoint:
        provider_vars["OLLAMA_BASE_URL"] = transform_localhost_url(
            config.providers.ollama.endpoint
        )
    return provider_vars


def apply_global_vars_to_headers(
    headers: Dict[str, str],
    global_vars: Dict[str, Any],
    *,
    scope: Optional[str] = None,
    allowed_keys: Optional[Iterable[str]] = None,
) -> None:
    """Apply global-variable key/value pairs to request headers.

    Unknown keys are ignored to keep all passthrough keys controlled by registry.
    """
    if not global_vars:
        return

    allow_set: Optional[Set[str]] = None
    if allowed_keys is not None:
        allow_set = {str(key).upper() for key in allowed_keys}

    for key, raw_value in global_vars.items():
        normalized_key = str(key).upper()
        definition = LANGFLOW_GLOBAL_VAR_REGISTRY.get(normalized_key)
        if definition is None:
            continue
        if allow_set is not None and normalized_key not in allow_set:
            continue
        if not _is_scope_allowed(definition, scope):
            continue
        if raw_value is None:
            continue
        if isinstance(raw_value, str) and raw_value.strip() == "":
            continue

        headers[get_langflow_global_header_name(normalized_key)] = _serialize_value(
            raw_value, definition.serializer
        )


def build_langflow_run_headers(
    *,
    config=None,
    runtime_vars: Optional[Dict[str, Any]] = None,
    scope: Optional[str] = None,
    include_provider_credentials: bool = True,
) -> Dict[str, str]:
    """Build run-request headers for Langflow global-variable passthrough."""
    headers: Dict[str, str] = {}
    if include_provider_credentials and config is not None:
        apply_global_vars_to_headers(
            headers, build_provider_global_vars(config), scope=scope
        )

    apply_global_vars_to_headers(headers, runtime_vars or {}, scope=scope)
    return headers


def add_provider_credentials_to_headers(headers: Dict[str, str], config) -> None:
    """Backwards-compatible helper used by existing call sites."""
    apply_global_vars_to_headers(headers, build_provider_global_vars(config))


def build_mcp_global_vars_from_config(config) -> Dict[str, str]:
    """Build MCP global variables dictionary from OpenRAG configuration.

    Returns globals without the Langflow header prefix.
    """
    global_vars = build_provider_global_vars(config)
    if config.knowledge.embedding_model:
        global_vars["SELECTED_EMBEDDING_MODEL"] = config.knowledge.embedding_model
    return global_vars

