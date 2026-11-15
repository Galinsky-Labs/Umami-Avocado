"""Content-addressed artifact storage (UA-015).

The default store keeps bytes in PostgreSQL (``artifact_blobs``, immutable). An
S3-compatible store is selected only when ARTIFACT_STORE=s3 *and* S3_ENDPOINT,
S3_BUCKET, S3_ACCESS_KEY and S3_SECRET_KEY are all set; otherwise the platform falls
back to PostgreSQL. Reads always re-verify the SHA-256 digest.
"""
import hashlib
from typing import Protocol

from sqlalchemy.orm import Session

from umami_api.models import ArtifactBlob


class IntegrityFailure(RuntimeError):
    pass


class ArtifactStore(Protocol):
    name: str

    def put(self, session: Session, content: bytes) -> str: ...

    def get(self, session: Session, sha256: str) -> bytes: ...


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class PostgresStore:
    name = "postgres"

    def put(self, session: Session, content: bytes) -> str:
        sha = digest(content)
        if session.get(ArtifactBlob, sha) is None:
            session.add(ArtifactBlob(sha256=sha, size=len(content), content=content))
            session.flush()
        return sha

    def get(self, session: Session, sha256: str) -> bytes:
        blob = session.get(ArtifactBlob, sha256)
        if blob is None:
            raise IntegrityFailure("Artifact content is missing.")
        if digest(blob.content) != sha256:
            raise IntegrityFailure("Artifact content does not match its digest.")
        return blob.content


class S3Store:
    """S3-compatible object storage, keyed by digest. Requires boto3 (not bundled) and
    credentials; disabled unless explicitly configured."""
    name = "s3"

    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str):
        try:
            import boto3
        except ImportError as error:
            raise RuntimeError("ARTIFACT_STORE=s3 requires the boto3 package.") from error
        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=access_key,
                                   aws_secret_access_key=secret_key)

    def put(self, session: Session, content: bytes) -> str:
        sha = digest(content)
        self.client.put_object(Bucket=self.bucket, Key=f"sha256/{sha}", Body=content)
        return sha

    def get(self, session: Session, sha256: str) -> bytes:
        content = self.client.get_object(Bucket=self.bucket, Key=f"sha256/{sha256}")["Body"].read()
        if digest(content) != sha256:
            raise IntegrityFailure("Artifact content does not match its digest.")
        return content


def get_store(name: str) -> ArtifactStore:
    if name == "s3":
        import os
        return S3Store(os.environ["S3_ENDPOINT"], os.environ["S3_BUCKET"],
                       os.environ["S3_ACCESS_KEY"], os.environ["S3_SECRET_KEY"])
    return PostgresStore()
