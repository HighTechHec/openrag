"""Unit tests for verify_s3_credentials() and S3Connector.authenticate()."""
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_error(code: str):
    """Build a botocore ClientError with the given error code."""
    import botocore.exceptions

    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": code}},
        "operation",
    )


# ---------------------------------------------------------------------------
# verify_s3_credentials — bucket_names configured
# ---------------------------------------------------------------------------

class TestVerifyWithBuckets:
    def _make_client(self):
        mock_client = MagicMock()
        mock_client.head_bucket.return_value = {}
        return mock_client

    def test_success_calls_head_bucket_for_each_bucket(self):
        from connectors.aws_s3.auth import verify_s3_credentials

        config = {
            "access_key": "AKIA_FAKE",
            "secret_key": "fake_secret",
            "bucket_names": ["bucket-a", "bucket-b"],
        }
        mock_client = self._make_client()

        with patch("connectors.aws_s3.auth.create_s3_client", return_value=mock_client):
            verify_s3_credentials(config)

        assert mock_client.head_bucket.call_count == 2
        mock_client.head_bucket.assert_any_call(Bucket="bucket-a")
        mock_client.head_bucket.assert_any_call(Bucket="bucket-b")

    def test_head_bucket_403_propagates(self):
        from connectors.aws_s3.auth import verify_s3_credentials

        config = {
            "access_key": "AKIA_FAKE",
            "secret_key": "fake_secret",
            "bucket_names": ["restricted-bucket"],
        }
        mock_client = self._make_client()
        mock_client.head_bucket.side_effect = _client_error("403")

        with patch("connectors.aws_s3.auth.create_s3_client", return_value=mock_client):
            with pytest.raises(Exception):
                verify_s3_credentials(config)

    def test_head_bucket_404_propagates(self):
        from connectors.aws_s3.auth import verify_s3_credentials

        config = {
            "access_key": "AKIA_FAKE",
            "secret_key": "fake_secret",
            "bucket_names": ["nonexistent-bucket"],
        }
        mock_client = self._make_client()
        mock_client.head_bucket.side_effect = _client_error("NoSuchBucket")

        with patch("connectors.aws_s3.auth.create_s3_client", return_value=mock_client):
            with pytest.raises(Exception):
                verify_s3_credentials(config)


# ---------------------------------------------------------------------------
# verify_s3_credentials — no bucket_names
# ---------------------------------------------------------------------------

class TestVerifyWithoutBuckets:
    def _make_client(self):
        mock_client = MagicMock()
        mock_client.list_buckets.return_value = {"Buckets": []}
        return mock_client

    def test_success_calls_list_buckets(self):
        from connectors.aws_s3.auth import verify_s3_credentials

        config = {"access_key": "AKIA_FAKE", "secret_key": "fake_secret"}
        mock_client = self._make_client()

        with patch("connectors.aws_s3.auth.create_s3_client", return_value=mock_client):
            verify_s3_credentials(config)

        mock_client.list_buckets.assert_called_once()

    def test_access_denied_does_not_raise(self):
        """Bucket-scoped IAM users receive AccessDenied on ListBuckets — treat as valid creds."""
        from connectors.aws_s3.auth import verify_s3_credentials

        config = {"access_key": "AKIA_FAKE", "secret_key": "fake_secret"}
        mock_client = self._make_client()
        mock_client.list_buckets.side_effect = _client_error("AccessDenied")

        with patch("connectors.aws_s3.auth.create_s3_client", return_value=mock_client):
            # Should not raise
            verify_s3_credentials(config)

    def test_invalid_access_key_propagates(self):
        from connectors.aws_s3.auth import verify_s3_credentials

        config = {"access_key": "INVALID", "secret_key": "INVALID"}
        mock_client = self._make_client()
        mock_client.list_buckets.side_effect = _client_error("InvalidAccessKeyId")

        with patch("connectors.aws_s3.auth.create_s3_client", return_value=mock_client):
            with pytest.raises(Exception):
                verify_s3_credentials(config)

    def test_signature_mismatch_propagates(self):
        from connectors.aws_s3.auth import verify_s3_credentials

        config = {"access_key": "AKIA_FAKE", "secret_key": "wrong_secret"}
        mock_client = self._make_client()
        mock_client.list_buckets.side_effect = _client_error("SignatureDoesNotMatch")

        with patch("connectors.aws_s3.auth.create_s3_client", return_value=mock_client):
            with pytest.raises(Exception):
                verify_s3_credentials(config)

    def test_empty_bucket_names_list_treated_as_no_buckets(self):
        """An explicit empty list should follow the no-buckets path."""
        from connectors.aws_s3.auth import verify_s3_credentials

        config = {
            "access_key": "AKIA_FAKE",
            "secret_key": "fake_secret",
            "bucket_names": [],
        }
        mock_client = self._make_client()

        with patch("connectors.aws_s3.auth.create_s3_client", return_value=mock_client):
            verify_s3_credentials(config)

        mock_client.list_buckets.assert_called_once()
        mock_client.head_bucket.assert_not_called()


# ---------------------------------------------------------------------------
# S3Connector.authenticate()
# ---------------------------------------------------------------------------

class TestS3ConnectorAuthenticate:
    def _make_connector(self, bucket_names=None):
        from connectors.aws_s3.connector import S3Connector

        config = {
            "access_key": "AKIA_FAKE",
            "secret_key": "fake_secret",
        }
        if bucket_names is not None:
            config["bucket_names"] = bucket_names
        return S3Connector(config)

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        connector = self._make_connector(bucket_names=["my-bucket"])

        with patch("connectors.aws_s3.connector.verify_s3_credentials"):
            result = await connector.authenticate()

        assert result is True
        assert connector._authenticated is True

    @pytest.mark.asyncio
    async def test_returns_false_on_failure(self):
        connector = self._make_connector(bucket_names=["my-bucket"])

        with patch(
            "connectors.aws_s3.connector.verify_s3_credentials",
            side_effect=_client_error("403"),
        ):
            result = await connector.authenticate()

        assert result is False
        assert connector._authenticated is False

    @pytest.mark.asyncio
    async def test_returns_true_when_access_denied_on_list_buckets(self):
        """AccessDenied on list_buckets (no buckets configured) should still auth successfully."""
        connector = self._make_connector()  # no bucket_names

        # verify_s3_credentials absorbs AccessDenied and returns None (no raise)
        with patch("connectors.aws_s3.connector.verify_s3_credentials", return_value=None):
            result = await connector.authenticate()

        assert result is True
