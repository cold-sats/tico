"""S3 settings shared by attachments and desktop downloads."""

import os


def region(settings, env=None):
    env = os.environ if env is None else env
    return (settings.blob_region or
            (env.get("TICO_BACKUP_REGION") if not settings.blob_endpoint and not env.get("TICO_BACKUP_ENDPOINT") else None) or
            env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or None)


def client(settings, config=None):
    import boto3
    options = {"region_name": region(settings), "endpoint_url": settings.blob_endpoint or None}
    if config is not None:
        options["config"] = config
    # Keep explicit AWS credentials, profiles and role providers on boto3's default chain.
    aws_credentials = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_SECURITY_TOKEN",
                       "AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE",
                       "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_CREDENTIALS_FULL_URI")
    key, secret = os.environ.get("TICO_BLOB_ACCESS_KEY_ID"), os.environ.get("TICO_BLOB_SECRET_ACCESS_KEY")
    if key and secret:
        options.update(aws_access_key_id=key, aws_secret_access_key=secret)
    elif settings.blob_bucket and not any(os.environ.get(key) for key in aws_credentials):
        key, secret = os.environ.get("LITESTREAM_ACCESS_KEY_ID"), os.environ.get("LITESTREAM_SECRET_ACCESS_KEY")
        if key and secret:
            options.update(aws_access_key_id=key, aws_secret_access_key=secret)
    return boto3.client("s3", **options)


def write_error(exc, bucket, cleanup=False):
    # Only known error codes or the exception type: SDK messages can contain credential material.
    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    known = {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch", "ExpiredToken", "InvalidToken",
             "NoSuchBucket", "AuthorizationHeaderMalformed", "RequestTimeTooSkewed", "SlowDown", "ServiceUnavailable"}
    reason = code if code in known else type(exc).__name__
    if cleanup and code == "AccessDenied":
        return f"S3 storage cleanup permission missing: s3:AbortMultipartUpload on {bucket}"
    if cleanup:
        return f"S3 storage can't clean up its write check: {reason} on {bucket}"
    return f"S3 storage can't write: {reason} on {bucket}"
