"""Object storage (Cloudflare R2, S3-compatible). boto3 is sync — call these
via asyncio.to_thread from async code paths."""

from functools import lru_cache

import boto3

from kasauti_api.settings import get_settings


@lru_cache
def r2_client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.r2_endpoint_url,
        aws_access_key_id=s.r2_access_key_id,
        aws_secret_access_key=s.r2_secret_access_key,
        region_name="auto",
    )


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str) -> str:
    r2_client().put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    return key


def download_bytes(bucket: str, key: str) -> bytes:
    return r2_client().get_object(Bucket=bucket, Key=key)["Body"].read()


def presigned_get_url(bucket: str, key: str, expires_seconds: int = 3600) -> str:
    return r2_client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_seconds
    )
