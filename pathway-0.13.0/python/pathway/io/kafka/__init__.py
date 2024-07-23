# Copyright © 2024 Pathway

from __future__ import annotations

import functools
import uuid
import warnings
from typing import Any, Iterable

import pathway.internals.dtype as dt
from pathway.internals import api, datasink, datasource
from pathway.internals._io_helpers import _format_output_value_fields
from pathway.internals.api import PathwayType
from pathway.internals.expression import ColumnReference
from pathway.internals.runtime_type_check import check_arg_types
from pathway.internals.schema import Schema
from pathway.internals.table import Table
from pathway.internals.table_io import table_from_datasource
from pathway.internals.trace import trace_user_frame
from pathway.io._utils import check_deprecated_kwargs, construct_schema_and_data_format

SUPPORTED_INPUT_FORMATS: set[str] = {
    "json",
    "raw",
    "plaintext",
}


@check_arg_types
@trace_user_frame
def read(
    rdkafka_settings: dict,
    topic: str | list[str] | None = None,
    *,
    schema: type[Schema] | None = None,
    format="raw",
    debug_data=None,
    autocommit_duration_ms: int | None = 1500,
    json_field_paths: dict[str, str] | None = None,
    parallel_readers: int | None = None,
    persistent_id: str | None = None,
    value_columns: list[str] | None = None,
    primary_key: list[str] | None = None,
    types: dict[str, PathwayType] | None = None,
    default_values: dict[str, Any] | None = None,
    _stacklevel: int = 1,
    **kwargs,
) -> Table:
    """Generalized method to read the data from the given topic in Kafka.

    There are three formats currently supported: "plaintext", "raw", and "json".
    If the "raw" format is chosen, the key and the payload are read from the topic as raw
    bytes and used in the table "as is". If you choose the "plaintext" option, however,
    they are parsed from the UTF-8 into the plaintext entries. In both cases, the
    table consists of a primary key and a single column "data", denoting the payload read.

    If "json" is chosen, the connector first parses the payload of the message
    according to the JSON format and then creates the columns corresponding to the
    schema defined by the ``schema`` parameter. The values of these columns are
    taken from the respective parsed JSON fields.

    Args:
        rdkafka_settings: Connection settings in the format of `librdkafka
            <https://github.com/edenhill/librdkafka/blob/master/CONFIGURATION.md>`_.
        topic: Name of topic in Kafka from which the data should be read.
        schema: Schema of the resulting table.
        format: format of the input data, "raw", "plaintext", or "json".
        debug_data: Static data replacing original one when debug mode is active.
        autocommit_duration_ms:the maximum time between two commits. Every
            autocommit_duration_ms milliseconds, the updates received by the connector are
            committed and pushed into Pathway's computation graph.
        json_field_paths: If the format is JSON, this field allows to map field names
            into path in the field. For the field which require such mapping, it should be
            given in the format ``<field_name>: <path to be mapped>``, where the path to
            be mapped needs to be a
            `JSON Pointer (RFC 6901) <https://www.rfc-editor.org/rfc/rfc6901>`_.
        parallel_readers: number of copies of the reader to work in parallel. In case
            the number is not specified, min{pathway_threads, total number of partitions}
            will be taken. This number also can't be greater than the number of Pathway
            engine threads, and will be reduced to the number of engine threads, if it
            exceeds.
        persistent_id: (unstable) An identifier, under which the state of the table will
            be persisted or ``None``, if there is no need to persist the state of this table.
            When a program restarts, it restores the state for all input tables according to what
            was saved for their ``persistent_id``. This way it's possible to configure the start of
            computations from the moment they were terminated last time.
        value_columns: Columns to extract for a table, required for format other than
            "raw". [will be deprecated soon]
        primary_key: In case the table should have a primary key generated according to
            a subset of its columns, the set of columns should be specified in this field.
            Otherwise, the primary key will be generated randomly. [will be deprecated soon]
        types: Dictionary containing the mapping between the columns and the data
            types (``pw.Type``) of the values of those columns. This parameter is optional, and if not
            Otherwise, the primary key will be generated randomly.
            provided the default type is ``pw.Type.ANY``. [will be deprecated soon]
        default_values: dictionary containing default values for columns replacing
            blank entries. The default value of the column must be specified explicitly,
            Otherwise, the primary key will be generated randomly.
            otherwise there will be no default value. [will be deprecated soon]

    Returns:
        Table: The table read.

    When using the format "raw", the connector will produce a single-column table:
    all the data is saved into a column named ``data``.
    For other formats, the argument value_column is required and defines the columns.

    Example:

    Consider there is a queue in Kafka, running locally on port 9092. Our queue can
    use SASL-SSL authentication over a SCRAM-SHA-256 mechanism. You can set up a queue
    with similar parameters in `Upstash <https://upstash.com/>`_. Settings for rdkafka
    will look as follows:

    >>> import os
    >>> rdkafka_settings = {
    ...    "bootstrap.servers": "localhost:9092",
    ...    "security.protocol": "sasl_ssl",
    ...    "sasl.mechanism": "SCRAM-SHA-256",
    ...    "group.id": "$GROUP_NAME",
    ...    "session.timeout.ms": "60000",
    ...    "sasl.username": os.environ["KAFKA_USERNAME"],
    ...    "sasl.password": os.environ["KAFKA_PASSWORD"]
    ... }

    To connect to the topic "animals" and accept messages, the connector must be used \
        as follows, depending on the format:

    Raw version:

    >>> import pathway as pw
    >>> t = pw.io.kafka.read(
    ...   rdkafka_settings,
    ...    topic="animals",
    ...    format="raw",
    ... )

    All the data will be accessible in the column data.

    CSV version:

    >>> import pathway as pw
    >>> class InputSchema(pw.Schema):
    ...   owner: str
    ...   pet: str
    >>> t = pw.io.kafka.read(
    ...    rdkafka_settings,
    ...    topic="animals",
    ...    format="csv",
    ...    schema=InputSchema
    ... )

    In case of CSV format, the first message must be the header:

    .. code-block:: csv

        owner,pet

    Then, simple data rows are expected. For example:

    .. code-block:: csv

        Alice,cat
        Bob,dog

    This way, you get a table which looks as follows:

    >>> pw.debug.compute_and_print(t, include_id=False)  # doctest: +SKIP
    owner pet
    Alice cat
      Bob dog


    JSON version:

    >>> import pathway as pw
    >>> t = pw.io.kafka.read(
    ...     rdkafka_settings,
    ...     topic="animals",
    ...     format="json",
    ...     schema=InputSchema,
    ... )

    For the JSON connector, you can send these two messages:

    .. code-block:: json

        {"owner": "Alice", "pet": "cat"}
        {"owner": "Bob", "pet": "dog"}

    This way, you get a table which looks as follows:

    >>> pw.debug.compute_and_print(t, include_id=False)  # doctest: +SKIP
    owner pet
    Alice cat
      Bob dog

    Now consider that the data about pets come in a more sophisticated way. For instance
    you have an owner, kind and name of an animal, along with some physical measurements.

    The JSON payload in this case may look as follows:

    .. code-block:: json

        {
            "name": "Jack",
            "pet": {
                "animal": "cat",
                "name": "Bob",
                "measurements": [100, 200, 300]
            }
        }

    Suppose you need to extract a name of the pet and the height, which is the 2nd
    (1-based) or the 1st (0-based) element in the array of measurements. Then, you
    use JSON Pointer and do a connector, which gets the data as follows:

    >>> import pathway as pw
    >>> class InputSchema(pw.Schema):
    ...   pet_name: str
    ...   pet_height: int
    >>> t = pw.io.kafka.read(
    ...    rdkafka_settings,
    ...    topic="animals",
    ...    format="json",
    ...    schema=InputSchema,
    ...    json_field_paths={
    ...        "pet_name": "/pet/name",
    ...        "pet_height": "/pet/measurements/1"
    ...    },
    ... )
    """
    # The data_storage is common to all kafka connectors

    if not topic:
        topic_names = kwargs.get("topic_names")
        if not topic_names:
            raise ValueError("Missing topic name specification")
        topic = topic_names[0]
    if isinstance(topic, list):
        warnings.warn(
            "'topic' should be a str, not list. First element will be used.",
            SyntaxWarning,
            stacklevel=_stacklevel + 4,
        )
        topic = topic[0]

    check_deprecated_kwargs(kwargs, ["topic_names"], stacklevel=_stacklevel + 4)

    data_storage = api.DataStorage(
        storage_type="kafka",
        rdkafka_settings=rdkafka_settings,
        topic=topic,
        parallel_readers=parallel_readers,
        persistent_id=persistent_id,
        mode=api.ConnectorMode.STREAMING,
    )
    schema, data_format = construct_schema_and_data_format(
        "binary" if format == "raw" else format,
        schema=schema,
        csv_settings=None,
        json_field_paths=json_field_paths,
        value_columns=value_columns,
        primary_key=primary_key,
        types=types,
        default_values=default_values,
        _stacklevel=5,
    )
    data_source_options = datasource.DataSourceOptions(
        commit_duration_ms=autocommit_duration_ms
    )
    return table_from_datasource(
        datasource.GenericDataSource(
            datastorage=data_storage,
            dataformat=data_format,
            data_source_options=data_source_options,
            schema=schema,
            datasource_name="kafka",
        ),
        debug_datasource=datasource.debug_datasource(debug_data),
    )


@check_arg_types
@trace_user_frame
def simple_read(
    server: str,
    topic: str,
    *,
    read_only_new: bool = False,
    schema: type[Schema] | None = None,
    format="raw",
    debug_data=None,
    autocommit_duration_ms: int | None = 1500,
    json_field_paths: dict[str, str] | None = None,
    parallel_readers: int | None = None,
    persistent_id: str | None = None,
) -> Table:
    """Simplified method to read data from Kafka. Only requires the server address and
    the topic name. If you have any kind of authentication or require fine-tuning of the
    parameters, please use `read` method.

    Read starts from the beginning of the topic, unless the `read_only_new` parameter is
    set to True.

    There are three formats currently supported: "plaintext", "raw", and "json".
    If the "raw" format is chosen, the key and the payload are read from the topic as raw
    bytes and used in the table "as is". If you choose the "plaintext" option, however,
    they are parsed from the UTF-8 into the plaintext entries. In both cases, the
    table consists of a primary key and a single column "data", denoting the payload read.

    If "json" is chosen, the connector first parses the payload of the message
    according to the JSON format and then creates the columns corresponding to the
    schema defined by the ``schema`` parameter. The values of these columns are
    taken from the respective parsed JSON fields.

    Args:
        server: Address of the server.
        topic: Name of topic in Kafka from which the data should be read.
        read_only_new: If set to `True` only the entries which appear after the start \
of the program will be read. Otherwise, the read will be done from the beginning of the\
topic.
        schema: Schema of the resulting table.
        format: format of the input data, "raw", "plaintext", or "json".
        debug_data: Static data replacing original one when debug mode is active.
        autocommit_duration_ms: The maximum time between two commits. Every
            autocommit_duration_ms milliseconds, the updates received by the connector are
            committed and pushed into Pathway's computation graph.
        json_field_paths: If the format is JSON, this field allows to map field names
            into path in the field. For the fields which require such mapping, it should be
            given in the format ``<field_name>: <path to be mapped>``, where the path to
            be mapped needs to be a
            `JSON Pointer (RFC 6901) <https://www.rfc-editor.org/rfc/rfc6901>`_.
        parallel_readers: number of copies of the reader to work in parallel. In case
            the number is not specified, min{pathway_threads, total number of partitions}
            will be taken. This number also can't be greater than the number of Pathway
            engine threads, and will be reduced to the number of engine threads, if it
            exceeds.
        persistent_id: (unstable) An identifier, under which the state of the table will
            be persisted or ``None``, if there is no need to persist the state of this table.
            When a program restarts, it restores the state for all input tables according to what
            was saved for their ``persistent_id``. This way it's possible to configure the start of
            computations from the moment they were terminated last time.

    Returns:
        Table: The table read.

    When using the format "raw", the connector will produce a single-column table:
    all the data is saved into a column named ``data``.

    For other formats, the argument value_column is required and defines the columns.

    Example:

    Consider that there's a Kafka queue running locally on the port 9092 and we need
    to read raw messages from the topic "test-topic". Then, it can be done in the
    following way:

    >>> import pathway as pw
    >>> t = pw.io.kafka.simple_read("localhost:9092", "test-topic")
    """

    rdkafka_settings = {
        "bootstrap.servers": server,
        "group.id": str(uuid.uuid4()),
        "auto.offset.reset": "end" if read_only_new else "beginning",
    }
    return read(
        rdkafka_settings=rdkafka_settings,
        topic=topic,
        schema=schema,
        format=format,
        debug_data=debug_data,
        autocommit_duration_ms=autocommit_duration_ms,
        json_field_paths=json_field_paths,
        parallel_readers=parallel_readers,
        persistent_id=persistent_id,
    )


@check_arg_types
@trace_user_frame
def read_from_upstash(
    endpoint: str,
    username: str,
    password: str,
    topic: str,
    *,
    read_only_new: bool = False,
    schema: type[Schema] | None = None,
    format="raw",
    debug_data=None,
    autocommit_duration_ms: int | None = 1500,
    json_field_paths: dict[str, str] | None = None,
    parallel_readers: int | None = None,
    persistent_id: str | None = None,
) -> Table:
    """Simplified method to read data from Kafka instance hosted in Upstash. It requires
    endpoint address and topic along with credentials.

    Read starts from the beginning of the topic, unless the `read_only_new` parameter is
    set to True.

    There are three formats currently supported: "plaintext", "raw", and "json".
    If the "raw" format is chosen, the key and the payload are read from the topic as raw
    bytes and used in the table "as is". If you choose the "plaintext" option, however,
    they are parsed from the UTF-8 into the plaintext entries. In both cases, the
    table consists of a primary key and a single column "data", denoting the payload read.

    If "json" is chosen, the connector first parses the payload of the message
    according to the JSON format and then creates the columns corresponding to the
    schema defined by the ``schema`` parameter. The values of these columns are
    taken from the respective parsed JSON fields.

    Args:
        endpoint: Upstash endpoint for the sought queue, which can be found on \
"Details" page.
        username: Username generated for this queue.
        password: Password generated for this queue. These credentials are also \
available on "Details" page.
        topic: Name of topic in Kafka from which the data should be read.
        read_only_new: If set to `True` only the entries which appear after the start \
of the program will be read. Otherwise, the read will be done from the beginning of the\
topic.
        schema: Schema of the resulting table.
        format: format of the input data, "raw", "plaintext", or "json".
        debug_data: Static data replacing original one when debug mode is active.
        autocommit_duration_ms: The maximum time between two commits. Every
            autocommit_duration_ms milliseconds, the updates received by the connector are
            committed and pushed into Pathway's computation graph.
        json_field_paths: If the format is JSON, this field allows to map field names
            into path in the field. For the fields which require such mapping, it should be
            given in the format ``<field_name>: <path to be mapped>``, where the path to
            be mapped needs to be a
            `JSON Pointer (RFC 6901) <https://www.rfc-editor.org/rfc/rfc6901>`_.
        parallel_readers: number of copies of the reader to work in parallel. In case
            the number is not specified, min{pathway_threads, total number of partitions}
            will be taken. This number also can't be greater than the number of Pathway
            engine threads, and will be reduced to the number of engine threads, if it
            exceeds.
        persistent_id: (unstable) An identifier, under which the state of the table will
            be persisted or ``None``, if there is no need to persist the state of this table.
            When a program restarts, it restores the state for all input tables according to what
            was saved for their ``persistent_id``. This way it's possible to configure the start of
            computations from the moment they were terminated last time.

    Returns:
        Table: The table read.

    When using the format "raw", the connector will produce a single-column table:
    all the data is saved into a column named ``data``.

    Example:

    Consider that there is a queue running in Upstash. Let's say the endpoint name is
    "https://example-endpoint.com:19092", topic is "test-topic" and the credentials are
    stored in environment variables.

    Suppose that we need just to read the raw messages for the further processing. Then
    it can be done in the following way:

    >>> import os
    >>> import pathway as pw
    >>> t = pw.io.kafka.read_from_upstash(
    ...     endpoint="https://example-endpoint.com:19092",
    ...     topic="test-topic",
    ...     username=os.environ["KAFKA_USERNAME"],
    ...     password=os.environ["KAFKA_PASSWORD"],
    ... )
    """

    rdkafka_settings = {
        "bootstrap.servers": endpoint,
        "group.id": str(uuid.uuid4()),
        "auto.offset.reset": "end" if read_only_new else "beginning",
        "security.protocol": "sasl_ssl",
        "sasl.mechanism": "SCRAM-SHA-256",
        "sasl.username": username,
        "sasl.password": password,
    }
    return read(
        rdkafka_settings=rdkafka_settings,
        topic=topic,
        schema=schema,
        format=format,
        debug_data=debug_data,
        autocommit_duration_ms=autocommit_duration_ms,
        json_field_paths=json_field_paths,
        parallel_readers=parallel_readers,
        persistent_id=persistent_id,
    )


def check_raw_and_plaintext_only_kwargs(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if kwargs.get("format") not in ("raw", "plaintext"):
            unexpected_params = [
                "key",
                "value",
                "headers",
            ]
            for param in unexpected_params:
                if param in kwargs and kwargs[param] is not None:
                    raise ValueError(
                        f"Unsupported argument for {format} format: {param}"
                    )

        return f(*args, **kwargs)

    return wrapper


@check_raw_and_plaintext_only_kwargs
@check_arg_types
@trace_user_frame
def write(
    table: Table,
    rdkafka_settings: dict,
    topic_name: str,
    *,
    format: str = "json",
    delimiter: str = ",",
    key: ColumnReference | None = None,
    value: ColumnReference | None = None,
    headers: Iterable[ColumnReference] | None = None,
) -> None:
    """Write a table to a given topic on a Kafka instance.

    The produced messages consist of the key, corresponding to row's key, the value,
    corresponding to the values of the table that are serialized according to the chosen
    format and two headers: ``pathway_time``, corresponding to the logical time of the entry
    and ``pathway_diff`` that is either 1 or -1. Both header values are provided as UTF-8
    encoded strings.

    There are several serialization formats supported: 'json', 'dsv', 'plaintext' and 'raw'.
    The format defines how the message is formed. In case of JSON and DSV (delimiter
    separated values), the message is formed in accordance with the respective data format.

    If the selected format is either 'plaintext' or 'raw', you also need to specify, which
    columns of the table correspond to the key and the value of the produced Kafka
    message. It can be done by providing ``key`` and ``value`` parameters. In order to
    output extra values from the table in these formats, Kafka headers can be used. You
    can specify the column references in the ``headers`` parameter, which leads to
    serializing the extracted fields into UTF-8 strings and passing them as additional
    Kafka headers.

    Args:
        table: the table to output.
        rdkafka_settings: Connection settings in the format of
            `librdkafka <https://github.com/edenhill/librdkafka/blob/master/CONFIGURATION.md>`_.
        topic_name: name of topic in Kafka to which the data should be sent.
        format: format in which the data is put into Kafka. Currently "json",
            "plaintext", "raw" and "dsv" are supported. If the "raw" format is selected,
            ``table`` must either contain exactly one binary column that will be dumped as it is into the
            Kafka message, or the reference to the target binary column must be specified explicitly
            in the ``value`` parameter. Similarly, if "plaintext" is chosen, the table should consist
            of a single column of the string type.
        delimiter: field delimiter to be used in case of delimiter-separated values
            format.
        key: reference to the column that should be used as a key in the
            produced message in 'plaintext' or 'raw' format. If left empty, an internal primary key will
            be used.
        value: reference to the column that should be used as a value in
            the produced message in 'plaintext' or 'raw' format. It can be deduced automatically if the
            table has exactly one column. Otherwise it must be specified directly. It also has to be
            explicitly specified, if ``key`` is set.
        headers: references to the table fields that must be provided as message
            headers. These headers are named in the same way as fields that are forwarded and correspond
            to the string representations of the respective values encoded in UTF-8. If a binary
            column is requested, it will be produced "as is" in the respective header.


    Returns:
        None

    Examples:

    Consider there is a queue in Kafka, running locally on port 9092. Our queue can
    use SASL-SSL authentication over a SCRAM-SHA-256 mechanism. You can set up a queue
    with similar parameters in `Upstash <https://upstash.com/>`_. Settings for rdkafka
    will look as follows:

    >>> import os
    >>> rdkafka_settings = {
    ...    "bootstrap.servers": "localhost:9092",
    ...    "security.protocol": "sasl_ssl",
    ...    "sasl.mechanism": "SCRAM-SHA-256",
    ...    "sasl.username": os.environ["KAFKA_USERNAME"],
    ...    "sasl.password": os.environ["KAFKA_PASSWORD"]
    ... }

    You want to send a Pathway table ``t`` to the Kafka instance.

    >>> import pathway as pw
    >>> t = pw.debug.table_from_markdown("age owner pet \\n 1 10 Alice dog \\n 2 9 Bob cat \\n 3 8 Alice cat")

    To connect to the topic "animals" and send messages, the connector must be used as
    follows, depending on the format:

    JSON version:

    >>> pw.io.kafka.write(
    ...    t,
    ...    rdkafka_settings,
    ...    "animals",
    ...    format="json",
    ... )

    All the updates of table ``t`` will be sent to the Kafka instance.

    Another thing to be demonstated is the usage of 'raw' format in the output. Please
    note that the same rules will be applicable for the 'plaintext' with the only difference
    being the requirement for the columns to have the ``string`` type.

    Now consider that a table ``t2`` contains two binary columns ``foo`` and ``bar``, and
    a numerical column ``baz``. That is, the schema of this table looks as follows:

    >>> class T2Schema(pw.Schema):
    ...     foo: bytes
    ...     bar: bytes
    ...     baz: int

    This table can be generated with a Python input connector as follows:

    >>> class T2GenerationSubject(pw.python.ConnectorSubject):
    ...     def run(self) -> None:
    ...         # TODO: define generation logic
    ...         pass
    >>> t2 = pw.io.python.read(T2GenerationSubject(), schema=T2Schema)

    Since is more than one column, you need to specify which one you want to use in the
    output, when using the 'raw' format. If this is the column ``foo``, you may output this
    table as follows:

    >>> pw.io.kafka.write(
    ...    t2,
    ...    rdkafka_settings,
    ...    "test",
    ...    format="raw",
    ...    value=t2.foo,
    ... )

    If at the same time you would prefer to have the key of the produced messages to be
    defined by the value of another binary column ``bar``, you can use the ``key`` parameter as
    follows:

    >>> pw.io.kafka.write(
    ...    t2,
    ...    rdkafka_settings,
    ...    "test",
    ...    format="raw",
    ...    key=t2.bar,
    ...    value=t2.foo,
    ... )

    Still, the table has three fields and the field ``baz`` is not produced. You can do it
    with the usage of headers. To pass it to the header with the same name ``baz``, you need to
    specify it:

    >>> pw.io.kafka.write(
    ...    t2,
    ...    rdkafka_settings,
    ...    "test",
    ...    format="raw",
    ...    key=t2.bar,
    ...    value=t2.foo,
    ...    headers=[t2.baz],
    ... )
    """

    key_field_index = None
    header_fields: dict[str, int] = {}
    if format == "json":
        data_format = api.DataFormat(
            format_type="jsonlines",
            key_field_names=[],
            value_fields=_format_output_value_fields(table),
        )
    elif format == "dsv":
        data_format = api.DataFormat(
            format_type="dsv",
            key_field_names=[],
            value_fields=_format_output_value_fields(table),
            delimiter=delimiter,
        )
    elif format == "raw" or format == "plaintext":
        value_field_index = None
        extracted_field_indices: dict[str, int] = {}
        columns_to_extract: list[ColumnReference] = []
        allowed_column_types = (dt.BYTES if format == "raw" else dt.STR, dt.ANY)

        if key is not None:
            if value is None:
                raise ValueError("'value' must be specified if 'key' is not None")
            key_field_index = _add_column_reference_to_extract(
                key, columns_to_extract, extracted_field_indices
            )
        if value is not None:
            value_field_index = _add_column_reference_to_extract(
                value, columns_to_extract, extracted_field_indices
            )
        else:
            column_names = list(table._columns.keys())
            if len(column_names) != 1:
                raise ValueError(
                    f"'{format}' format without explicit 'value' specification "
                    "can only be used with single-column tables"
                )
            value = table[column_names[0]]
            value_field_index = _add_column_reference_to_extract(
                value, columns_to_extract, extracted_field_indices
            )

        if headers is not None:
            for header in headers:
                header_fields[header.name] = _add_column_reference_to_extract(
                    header, columns_to_extract, extracted_field_indices
                )

        table = table.select(*columns_to_extract)

        if (
            key is not None
            and table[key._name]._column.dtype not in allowed_column_types
        ):
            raise ValueError(
                f"The key column should be of the type '{allowed_column_types[0]}'"
            )
        if table[value._name]._column.dtype not in allowed_column_types:
            raise ValueError(
                f"The value column should be of the type '{allowed_column_types[0]}'"
            )

        data_format = api.DataFormat(
            format_type="single_column",
            key_field_names=[],
            value_fields=_format_output_value_fields(table),
            value_field_index=value_field_index,
        )
    else:
        raise ValueError(f"Unsupported format: {format}")

    data_storage = api.DataStorage(
        storage_type="kafka",
        rdkafka_settings=rdkafka_settings,
        topic=topic_name,
        key_field_index=key_field_index,
        header_fields=[item for item in header_fields.items()],
    )

    table.to(datasink.GenericDataSink(data_storage, data_format, datasink_name="kafka"))


def _add_column_reference_to_extract(
    column_reference: ColumnReference,
    selection_list: list[ColumnReference],
    field_indices: dict[str, int],
):
    column_name = column_reference.name

    index_in_new_table = field_indices.get(column_name)
    if index_in_new_table is not None:
        # This column will already be selected, no need to do anything
        return index_in_new_table

    index_in_new_table = len(selection_list)
    field_indices[column_name] = index_in_new_table
    selection_list.append(column_reference)
    return index_in_new_table
