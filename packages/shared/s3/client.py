"""
Unified S3 client for Shipments Agency Platform.

Consolidates S3 operations for all agents and data extraction.

Key capabilities:
  - find_latest_file() -- discover most-recent object under a prefix
  - download_json()    -- load and parse a JSON object
  - download_text()    -- load a text/markdown object
  - upload_json()      -- write a JSON object
  - upload_text()      -- write a text/markdown object
  - create_customer_path() -- build canonical S3 key for a customer artifact
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from packages.shared.exceptions import S3Error
from packages.shared.logging import get_logger


class S3Client:
    """
    Unified S3 client used by all packages in the platform.

    Instantiate once (e.g., at gateway startup) and share across agents.
    """

    def __init__(self, bucket: str = "dev-use1-worker-sc-fp-data", region: str = "us-east-1"):
        self.logger = get_logger(__name__)
        self.bucket = bucket
        self.region = region
        self._client = self._connect(region)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self, region: str) -> Any:
        """Create and verify a boto3 S3 client."""
        try:
            client = boto3.client("s3", region_name=region)
            # Lightweight connectivity check
            client.head_bucket(Bucket=self.bucket)
            self.logger.info(f"Connected to S3 bucket: {self.bucket}")
            return client
        except NoCredentialsError:
            raise S3Error("AWS credentials not found. Run: aws sso login")
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("403", "404"):
                raise S3Error(f"Cannot access bucket {self.bucket}: {code}")
            raise S3Error(f"S3 connection error: {exc}")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def find_latest_file(
        self,
        prefix: str,
        suffix: str = ".json",
    ) -> Optional[str]:
        """
        Return the S3 key of the most-recently-modified object under *prefix*.

        Args:
            prefix: S3 key prefix (e.g., ``uta/cat_outputs/12345/data/main_shipment_query/``).
            suffix: Only consider objects whose key ends with this string.

        Returns:
            The full S3 key of the latest matching object, or ``None``.
        """
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)

            latest_key: Optional[str] = None
            latest_modified = None

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if suffix and not key.endswith(suffix):
                        continue
                    modified = obj["LastModified"]
                    if latest_modified is None or modified > latest_modified:
                        latest_modified = modified
                        latest_key = key
            return latest_key
        except ClientError as exc:
            self.logger.warning(f"find_latest_file failed for prefix={prefix}: {exc}")
            return None

    def find_latest_customer_file(
        self,
        customer_id: str,
        folder: str,
        base_path: str = "uta/cat_outputs",
        suffix: str = ".json",
    ) -> Optional[str]:
        """
        Convenience wrapper: find latest file under ``<base_path>/<customer_id>/<folder>/``.

        Args:
            customer_id: Customer identifier.
            folder: Sub-folder path (e.g., ``data/main_shipment_query``).
            base_path: Root prefix in the bucket.
            suffix: File suffix filter.
        """
        prefix = f"{base_path}/{customer_id}/{folder}/"
        return self.find_latest_file(prefix, suffix=suffix)

    def list_keys(self, prefix: str, suffix: str = "", max_keys: int = 0) -> List[str]:
        """
        Return all keys under *prefix*, optionally filtered by *suffix*.

        Args:
            prefix: S3 key prefix to list.
            suffix: Only include keys ending with this string.
            max_keys: Stop after collecting this many keys (0 = no limit).
        """
        keys: List[str] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if not suffix or key.endswith(suffix):
                        keys.append(key)
                        if max_keys and len(keys) >= max_keys:
                            return keys
        except ClientError as exc:
            self.logger.warning(f"list_keys failed for prefix={prefix}: {exc}")
        return keys

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_json(self, key: str) -> Dict[str, Any]:
        """Download and parse a JSON object from S3."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            body = response["Body"].read().decode("utf-8")
            return json.loads(body)
        except ClientError as exc:
            raise S3Error(f"Failed to download JSON from s3://{self.bucket}/{key}: {exc}", s3_path=key)
        except json.JSONDecodeError as exc:
            raise S3Error(f"Invalid JSON at s3://{self.bucket}/{key}: {exc}", s3_path=key)

    def download_text(self, key: str) -> str:
        """Download a text/markdown object from S3."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read().decode("utf-8")
        except ClientError as exc:
            raise S3Error(f"Failed to download text from s3://{self.bucket}/{key}: {exc}", s3_path=key)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_json(self, data: Dict[str, Any], key: str) -> str:
        """
        Serialize *data* to JSON and upload to ``s3://<bucket>/<key>``.

        Returns:
            The full ``s3://`` URL of the uploaded object.
        """
        try:
            body = json.dumps(data, indent=2, default=str).encode("utf-8")
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType="application/json",
            )
            url = f"s3://{self.bucket}/{key}"
            self.logger.debug(f"Uploaded JSON to {url}")
            return url
        except ClientError as exc:
            raise S3Error(f"Failed to upload JSON to s3://{self.bucket}/{key}: {exc}", s3_path=key)

    def upload_text(self, text: str, key: str, content_type: str = "text/markdown") -> str:
        """Upload text content to S3."""
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=text.encode("utf-8"),
                ContentType=content_type,
            )
            url = f"s3://{self.bucket}/{key}"
            self.logger.debug(f"Uploaded text to {url}")
            return url
        except ClientError as exc:
            raise S3Error(f"Failed to upload text to s3://{self.bucket}/{key}: {exc}", s3_path=key)

    def upload_bytes(self, data: bytes, key: str, content_type: str = "application/octet-stream") -> str:
        """Upload raw bytes to S3."""
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            url = f"s3://{self.bucket}/{key}"
            self.logger.debug(f"Uploaded bytes to {url}")
            return url
        except ClientError as exc:
            raise S3Error(f"Failed to upload bytes to s3://{self.bucket}/{key}: {exc}", s3_path=key)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def customer_data_key(
        self,
        customer_id: str,
        query_folder: str,
        filename: str,
        base_path: str = "uta/cat_outputs",
    ) -> str:
        """Build canonical S3 key: ``<base>/<cid>/data/<folder>/<filename>``."""
        return f"{base_path}/{customer_id}/data/{query_folder}/{filename}"

    def customer_output_key(
        self,
        customer_id: str,
        agent_folder: str,
        filename: str,
        base_path: str = "uta/cat_outputs",
    ) -> str:
        """Build canonical S3 key: ``<base>/<cid>/<agent_folder>/<filename>``."""
        return f"{base_path}/{customer_id}/{agent_folder}/{filename}"

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def delete_keys(self, keys: List[str]) -> int:
        """Delete a list of S3 keys. Returns the number deleted."""
        if not keys:
            return 0
        deleted = 0
        for i in range(0, len(keys), 1000):
            batch = keys[i : i + 1000]
            try:
                self._client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
                )
                deleted += len(batch)
            except ClientError as exc:
                self.logger.warning(f"delete_keys failed for batch: {exc}")
        return deleted

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Return True if the bucket is reachable."""
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False
