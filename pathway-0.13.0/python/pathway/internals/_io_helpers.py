# Copyright © 2024 Pathway

from __future__ import annotations

import boto3
import boto3.session

from pathway.internals import api, dtype as dt, schema
from pathway.internals.table import Table
from pathway.internals.trace import trace_user_frame

S3_PATH_PREFIX = "s3://"
S3_DEFAULT_REGION = "us-east-1"
S3_LOCATION_FIELD = "LocationConstraint"


class AwsS3Settings:
    """Stores Amazon S3 connection settings. You may also use this class to store
    configuration settings for any custom S3 installation, however you will need to
    specify the region and the endpoint.

    Args:
        bucket_name: Name of S3 bucket.
        access_key: Access key for the bucket.
        secret_access_key: Secret access key for the bucket.
        with_path_style: Whether to use path-style requests.
        region: Region of the bucket.
        endpoint: Custom endpoint in case of self-hosted storage.
    """

    @trace_user_frame
    def __init__(
        self,
        *,
        bucket_name=None,
        access_key=None,
        secret_access_key=None,
        with_path_style=False,
        region=None,
        endpoint=None,
    ):
        self._bucket_name = bucket_name
        self._access_key = access_key
        self._secret_access_key = secret_access_key
        self._with_path_style = with_path_style
        self._region = region
        self._endpoint = endpoint

    @property
    def settings(self):
        return api.AwsS3Settings(
            self._bucket_name,
            self._access_key,
            self._secret_access_key,
            self._with_path_style,
            self._region,
            self._endpoint,
        )

    @classmethod
    def new_from_path(cls, s3_path: str):
        """
        Constructs settings from S3 path. The engine will look for the credentials in
        environment variables and in local AWS profiles. It will also automatically
        detect the region of the bucket.

        This method may fail if there are no credentials or they are incorrect. It may
        also fail if the bucket does not exist.

        Args:
            s3_path: full path to the object in the form ``s3://<bucket_name>/<path>``.

        Returns:
            Configuration object.
        """
        starts_with_prefix = s3_path.startswith(S3_PATH_PREFIX)
        has_extra_chars = len(s3_path) > len(S3_PATH_PREFIX)
        if not starts_with_prefix or not has_extra_chars:
            raise ValueError(f"Incorrect S3 path: {s3_path}")
        bucket = s3_path[len(S3_PATH_PREFIX) :].split("/")[0]

        # the crate we use on the Rust-engine side can't detect the location
        # of a bucket, so it's done on the Python side
        s3_client = boto3.client("s3")
        location_response = s3_client.get_bucket_location(Bucket=bucket)

        # Buckets in Region us-east-1 have a LocationConstraint of None
        location_constraint = location_response[S3_LOCATION_FIELD]
        if location_constraint is None:
            region = S3_DEFAULT_REGION
        else:
            region = location_constraint.split("|")[0]

        return cls(
            bucket_name=bucket,
            region=region,
        )

    def as_deltalake_storage_options(self):
        options = {
            "AWS_S3_ALLOW_UNSAFE_RENAME": "True",
            "AWS_REGION": self._region,
            "AWS_VIRTUAL_HOSTED_STYLE_REQUEST": str(not self._with_path_style),
        }
        if self._access_key is not None and self._secret_access_key is not None:
            options["AWS_ACCESS_KEY_ID"] = self._access_key
            options["AWS_SECRET_ACCESS_KEY"] = self._secret_access_key
        else:
            # DeltaLake underlying AWS S3 library may fail to deduce the credentials, so
            # we use boto3 to do that, which is more reliable
            # Related github issue: https://github.com/delta-io/delta-rs/issues/854
            session = boto3.session.Session()
            creds = session.get_credentials()
            if creds.access_key is not None and creds.secret_key is not None:
                options["AWS_ACCESS_KEY_ID"] = creds.access_key
                options["AWS_SECRET_ACCESS_KEY"] = creds.secret_key
            elif creds.token is not None:
                options["AWS_SESSION_TOKEN"] = creds.token
        if self._bucket_name is not None:
            options["AWS_BUCKET_NAME"] = self._bucket_name
        if self._endpoint is not None:
            options["AWS_ENDPOINT_NAME"] = self._endpoint
        return options


def _format_output_value_fields(table: Table) -> list[api.ValueField]:
    value_fields = []
    for column_name, column_data in table._columns.items():
        value_fields.append(
            api.ValueField(
                column_name,
                column_data.dtype.map_to_engine(),
                is_optional=isinstance(column_data.dtype, dt.Optional),
            )
        )

    return value_fields


def _form_value_fields(schema: type[schema.Schema]) -> list[api.ValueField]:
    schema.default_values()
    default_values = schema.default_values()
    result = []

    # XXX fix mapping schema types to PathwayType
    types = {
        name: (dt.unoptionalize(dtype).to_engine(), isinstance(dtype, dt.Optional))
        for name, dtype in schema._dtypes().items()
    }

    for f in schema.column_names():
        simple_type, is_optional = types.get(f, (None, False))
        if (
            simple_type is None
        ):  # types can contain None if there is field of type None in the schema
            simple_type = api.PathwayType.ANY
        value_field = api.ValueField(f, simple_type, is_optional=is_optional)
        if f in default_values:
            value_field.set_default(default_values[f])
        result.append(value_field)

    return result
