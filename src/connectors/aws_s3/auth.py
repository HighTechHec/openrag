"""Amazon S3 / S3-compatible storage authentication and client factory."""

import os
from typing import Any, Dict, Optional

from utils.logging_config import get_logger

logger = get_logger(__name__)

_DEFAULT_REGION = "us-east-1"


def _resolve_credentials(config: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve S3 credentials from config dict with environment variable fallback.

    Resolution order for each value: config dict → environment variable → default.

    Raises:
        ValueError: If access_key or secret_key cannot be resolved.
    """
    access_key: Optional[str] = config.get("access_key") or os.getenv("AWS_ACCESS_KEY_ID")
    secret_key: Optional[str] = config.get("secret_key") or os.getenv("AWS_SECRET_ACCESS_KEY")

    if not access_key or not secret_key:
        raise ValueError(
            "S3 credentials are required. Provide 'access_key' and 'secret_key' in the "
            "connector config, or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY env vars."
        )

    # endpoint_url is optional — only inject when non-empty (real AWS users don't set it)
    endpoint_url: Optional[str] = config.get("endpoint_url") or os.getenv("AWS_S3_ENDPOINT") or None

    region: str = config.get("region") or os.getenv("AWS_REGION") or _DEFAULT_REGION

    return {
        "access_key": access_key,
        "secret_key": secret_key,
        "endpoint_url": endpoint_url,
        "region": region,
    }


def _build_boto3_kwargs(creds: Dict[str, Any]) -> Dict[str, Any]:
    """Build the keyword arguments for boto3.resource / boto3.client."""
    kwargs: Dict[str, Any] = {
        "aws_access_key_id": creds["access_key"],
        "aws_secret_access_key": creds["secret_key"],
        "region_name": creds["region"],
    }
    if creds["endpoint_url"]:
        kwargs["endpoint_url"] = creds["endpoint_url"]
    return kwargs


def create_s3_resource(config: Dict[str, Any]):
    """Return a boto3 S3 resource (high-level API) for bucket/object access.

    Works with AWS S3, MinIO, Cloudflare R2, and any S3-compatible service.
    """
    try:
        import boto3
    except ImportError as exc:
        raise ImportError(
            "boto3 is required for the S3 connector. "
            "Install it with: pip install boto3"
        ) from exc

    creds = _resolve_credentials(config)
    kwargs = _build_boto3_kwargs(creds)
    logger.debug("Creating S3 resource with HMAC authentication (boto3)")
    return boto3.resource("s3", **kwargs)


def create_s3_client(config: Dict[str, Any]):
    """Return a boto3 S3 low-level client.

    Used for operations such as list_buckets() and get_object_acl().
    """
    try:
        import boto3
    except ImportError as exc:
        raise ImportError(
            "boto3 is required for the S3 connector. "
            "Install it with: pip install boto3"
        ) from exc

    creds = _resolve_credentials(config)
    kwargs = _build_boto3_kwargs(creds)
    logger.debug("Creating S3 client with HMAC authentication (boto3)")
    return boto3.client("s3", **kwargs)


def verify_s3_credentials(config: Dict[str, Any]) -> None:
    """Verify that the S3 credentials in *config* are valid and grant sufficient access.

    Uses the minimal AWS permission available for the caller's IAM policy:

    - When ``bucket_names`` are configured: calls ``HeadBucket`` on each bucket,
      which requires only ``s3:ListBucket`` scoped to that bucket.
    - When no buckets are configured: calls ``ListBuckets`` (``s3:ListAllMyBuckets``).
      An ``AccessDenied`` response is treated as valid credentials — the user simply
      has a bucket-scoped policy and has not configured specific buckets yet.
      Any other error (e.g. ``InvalidAccessKeyId``) propagates as a genuine failure.

    Raises:
        ValueError: If credentials cannot be resolved from *config* or env vars.
        botocore.exceptions.ClientError: If the credentials are invalid or the
            bucket(s) are inaccessible (except for the ``AccessDenied`` case above).
        ImportError: If boto3/botocore is not installed.
    """
    try:
        import botocore.exceptions
    except ImportError as exc:
        raise ImportError(
            "botocore is required for the S3 connector. "
            "Install it with: pip install boto3"
        ) from exc

    client = create_s3_client(config)
    bucket_names: list = config.get("bucket_names") or []

    if bucket_names:
        for bucket in bucket_names:
            client.head_bucket(Bucket=bucket)
    else:
        try:
            client.list_buckets()
        except botocore.exceptions.ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code == "AccessDenied":
                logger.warning(
                    "S3 credentials valid but lack s3:ListAllMyBuckets. "
                    "Proceeding — configure bucket_names to enable auto-discovery."
                )
                return
            raise
