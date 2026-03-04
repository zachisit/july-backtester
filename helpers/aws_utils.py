# helpers/aws_utils.py

import os
import boto3
import logging

logger = logging.getLogger(__name__)

def upload_file_to_s3(local_filepath, s3_bucket, s3_key):
    """
    Uploads a local file to a specified S3 bucket and key.

    Args:
        local_filepath (str): Path to the file on the local machine.
        s3_bucket (str): Name of the target S3 bucket.
        s3_key (str): The desired key (path/filename) in the S3 bucket.

    Returns:
        bool: True if upload was successful, False otherwise.
    """
    s3_client = boto3.client('s3')
    try:
        s3_client.upload_file(local_filepath, s3_bucket, s3_key)
        return True
    except boto3.exceptions.S3UploadFailedError as e:
        logger.error(f"S3 upload failed for {local_filepath}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during S3 upload for {local_filepath}: {e}")
        return False

def get_secret(key_name: str) -> str:
    """Reads a secret from environment variables or a .env file."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    value = os.environ.get(key_name)
    if not value:
        raise RuntimeError(
            f"Could not find '{key_name}'. "
            f"Set it as an environment variable or add it to a .env file in the project root."
        )
    return value
