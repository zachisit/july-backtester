# helpers/aws_utils.py

import os
import boto3
import json
import logging

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
        # Use a quieter print statement for successful uploads
        # print(f"  -> Successfully uploaded {os.path.basename(local_filepath)} to s3://{s3_bucket}/{s3_key}")
        return True
    except boto3.exceptions.S3UploadFailedError as e:
        print(f"  -> S3 UPLOAD FAILED for {local_filepath}. Error: {e}")
        return False
    except Exception as e:
        print(f"  -> An unexpected error occurred during S3 upload for {local_filepath}. Error: {e}")
        return False
    
def get_secret(secret_name, expected_api_key_description=None):
    """
    Retrieves a secret from AWS Secrets Manager.
    - If the secret is plaintext, it's returned directly.
    - If it's a JSON key/value, it can find a key by its description.
    """
    region_name = os.environ.get("AWS_REGION", "us-east-1") 
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name,
    )

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except Exception as e:
        logging.error(f"Could not retrieve AWS secret '{secret_name}' in region '{region_name}': {e}")
        return None

    secret = get_secret_value_response.get('SecretString')
    if not secret:
        return None

    # Try to parse as JSON for key/value secrets
    try:
        secret_dict = json.loads(secret)
        if expected_api_key_description:
            # Logic to find the right key within a JSON secret
            for key, description in secret_dict.items():
                if description == expected_api_key_description:
                    return key
            logging.warning(f"No key matched description '{expected_api_key_description}' in secret '{secret_name}'.")
            return None
        else:
            # If no description is given, we can't guess which key to return
            logging.error(f"Secret '{secret_name}' is JSON but no 'expected_api_key_description' was provided.")
            return None

    except json.JSONDecodeError:
        # If it's not JSON, it must be a plaintext secret
        if expected_api_key_description:
            logging.warning(f"Secret '{secret_name}' is plaintext; ignoring 'expected_api_key_description'.")
        return secret