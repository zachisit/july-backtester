"""
Tests for helpers/aws_utils.py.

upload_file_to_s3: mocks boto3 to avoid real network calls.
get_secret: exercises env-var lookup and the missing-key error path.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.aws_utils import upload_file_to_s3, get_secret


# ---------------------------------------------------------------------------
# upload_file_to_s3
# ---------------------------------------------------------------------------

class TestUploadFileToS3:

    def _mock_s3_client(self):
        """Returns a mock boto3 S3 client."""
        mock_client = MagicMock()
        return mock_client

    @patch("helpers.aws_utils.boto3.client")
    def test_successful_upload_returns_true(self, mock_boto_client):
        """Happy path: upload_file does not raise → function returns True."""
        mock_client = self._mock_s3_client()
        mock_boto_client.return_value = mock_client
        mock_client.upload_file.return_value = None  # success

        result = upload_file_to_s3("/tmp/report.csv", "my-bucket", "reports/report.csv")

        assert result is True
        mock_client.upload_file.assert_called_once_with(
            "/tmp/report.csv", "my-bucket", "reports/report.csv"
        )

    @patch("helpers.aws_utils.boto3.client")
    def test_s3_upload_failed_error_returns_false(self, mock_boto_client):
        """boto3 S3UploadFailedError must be caught and return False."""
        import boto3.exceptions
        mock_client = self._mock_s3_client()
        mock_boto_client.return_value = mock_client
        mock_client.upload_file.side_effect = boto3.exceptions.S3UploadFailedError(
            "Upload failed"
        )

        result = upload_file_to_s3("/tmp/file.csv", "my-bucket", "key.csv")

        assert result is False

    @patch("helpers.aws_utils.boto3.client")
    def test_generic_exception_returns_false(self, mock_boto_client):
        """Any unexpected exception must be caught and return False."""
        mock_client = self._mock_s3_client()
        mock_boto_client.return_value = mock_client
        mock_client.upload_file.side_effect = RuntimeError("Connection reset")

        result = upload_file_to_s3("/tmp/file.csv", "my-bucket", "key.csv")

        assert result is False

    @patch("helpers.aws_utils.boto3.client")
    def test_correct_bucket_and_key_forwarded(self, mock_boto_client):
        """The bucket name and S3 key must be forwarded verbatim to boto3."""
        mock_client = self._mock_s3_client()
        mock_boto_client.return_value = mock_client

        upload_file_to_s3("/path/to/file.txt", "prod-reports", "2025/Q1/report.txt")

        args = mock_client.upload_file.call_args[0]
        assert args[1] == "prod-reports"
        assert args[2] == "2025/Q1/report.txt"


# ---------------------------------------------------------------------------
# get_secret
# ---------------------------------------------------------------------------

class TestGetSecret:

    def test_reads_value_from_environment(self, monkeypatch):
        """If the env var is set, get_secret returns it."""
        monkeypatch.setenv("MY_TEST_KEY", "super-secret-value")
        result = get_secret("MY_TEST_KEY")
        assert result == "super-secret-value"

    def test_raises_runtime_error_when_key_missing(self, monkeypatch):
        """If the env var is absent and .env has no entry, raise RuntimeError."""
        monkeypatch.delenv("NONEXISTENT_SECRET_KEY_XYZ", raising=False)
        # Patch load_dotenv to be a no-op so .env on disk doesn't interfere
        with patch("helpers.aws_utils.os.environ.get", return_value=None):
            with pytest.raises(RuntimeError, match="NONEXISTENT_SECRET_KEY_XYZ"):
                get_secret("NONEXISTENT_SECRET_KEY_XYZ")

    def test_returns_string_type(self, monkeypatch):
        monkeypatch.setenv("MY_API_KEY", "abc123")
        result = get_secret("MY_API_KEY")
        assert isinstance(result, str)
