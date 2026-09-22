/*
  Action-agnostic event plane (Azure SQL twin of sql_pg/wf_event_plane.sql).
*/

SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF COL_LENGTH('wf.workflow_node', 'wait_event_type') IS NULL
    ALTER TABLE wf.workflow_node ADD wait_event_type NVARCHAR(256) NULL;
GO
IF COL_LENGTH('wf.workflow_node', 'wait_correlation_var') IS NULL
    ALTER TABLE wf.workflow_node ADD wait_correlation_var NVARCHAR(256) NULL;
GO

IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = N'CK_wn_node_type' AND parent_object_id = OBJECT_ID(N'wf.workflow_node')
)
    ALTER TABLE wf.workflow_node DROP CONSTRAINT CK_wn_node_type;
GO

ALTER TABLE wf.workflow_node ADD CONSTRAINT CK_wn_node_type CHECK (
    [node_type] IN (
        N'ACTION', N'SEQUENCE', N'PARALLEL', N'IF', N'SWITCH',
        N'REPEAT', N'WHILE', N'FOREACH', N'WAIT_EVENT'
    )
);
GO

IF OBJECT_ID(N'wf.event_delivery', N'U') IS NULL
AND OBJECT_ID(N'wf.event_subscription', N'U') IS NULL
AND OBJECT_ID(N'wf.event', N'U') IS NULL
AND OBJECT_ID(N'wf.event_type', N'U') IS NULL
BEGIN
    CREATE TABLE wf.event_type (
        id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        name NVARCHAR(256) NOT NULL,
        payload_data_type_id BIGINT NULL,
        created_at_utc DATETIME2(7) NOT NULL CONSTRAINT DF_event_type_created DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT UQ_event_type_name UNIQUE (name)
    );

    CREATE TABLE wf.event (
        id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        event_type_id BIGINT NOT NULL,
        occurred_at_utc DATETIME2(7) NOT NULL CONSTRAINT DF_event_occurred DEFAULT (SYSUTCDATETIME()),
        ingested_at_utc DATETIME2(7) NOT NULL CONSTRAINT DF_event_ingested DEFAULT (SYSUTCDATETIME()),
        source NVARCHAR(128) NOT NULL,
        idempotency_key NVARCHAR(256) NOT NULL,
        payload_json json NOT NULL CONSTRAINT DF_event_payload DEFAULT (CAST(N'{}' AS json)),
        correlation_key NVARCHAR(256) NULL,
        CONSTRAINT FK_event_type FOREIGN KEY (event_type_id) REFERENCES wf.event_type(id),
        CONSTRAINT UQ_event_source_idempotency UNIQUE (source, idempotency_key)
    );

    CREATE TABLE wf.event_subscription (
        id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        event_type_id BIGINT NOT NULL,
        workflow_version_id BIGINT NOT NULL,
        mode VARCHAR(32) NOT NULL,
        filter_json json NULL,
        enabled BIT NOT NULL CONSTRAINT DF_event_sub_enabled DEFAULT (1),
        created_at_utc DATETIME2(7) NOT NULL CONSTRAINT DF_event_sub_created DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_event_sub_type FOREIGN KEY (event_type_id) REFERENCES wf.event_type(id),
        CONSTRAINT FK_event_sub_version FOREIGN KEY (workflow_version_id) REFERENCES wf.workflow_version(id) ON DELETE CASCADE,
        CONSTRAINT CK_event_sub_mode CHECK (mode IN (N'start_instance', N'signal_wait', N'start_or_signal'))
    );

    CREATE TABLE wf.event_delivery (
        id BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        event_id BIGINT NOT NULL,
        subscription_id BIGINT NULL,
        workflow_instance_id BIGINT NULL,
        node_execution_id BIGINT NULL,
        status VARCHAR(32) NOT NULL,
        detail NVARCHAR(256) NULL,
        delivered_at_utc DATETIME2(7) NOT NULL CONSTRAINT DF_event_delivery_at DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT FK_event_delivery_event FOREIGN KEY (event_id) REFERENCES wf.event(id) ON DELETE CASCADE,
        CONSTRAINT CK_event_delivery_status CHECK (status IN (N'applied', N'ignored', N'duplicate'))
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'ix_event_type_ingested' AND object_id = OBJECT_ID(N'wf.event'))
    CREATE INDEX ix_event_type_ingested ON wf.event (event_type_id, ingested_at_utc DESC);
GO

CREATE OR ALTER PROCEDURE wf.wf_ensure_event_type
    @name NVARCHAR(256),
    @id BIGINT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @n NVARCHAR(256) = LTRIM(RTRIM(@name));
    IF @n IS NULL OR @n = N''
        THROW 50400, N'event type name is required', 1;

    SELECT @id = id FROM wf.event_type WHERE name = @n;
    IF @id IS NULL
    BEGIN
        INSERT INTO wf.event_type (name) VALUES (@n);
        SET @id = SCOPE_IDENTITY();
    END
END;
GO

CREATE OR ALTER FUNCTION wf.wf_event_filter_matches(@filter json, @payload json)
RETURNS BIT
AS
BEGIN
    IF @filter IS NULL
        RETURN 1;
    IF NOT EXISTS (SELECT 1 FROM OPENJSON(@filter))
        RETURN 1;
    IF EXISTS (
        SELECT 1
        FROM OPENJSON(@filter) f
        WHERE JSON_QUERY(@payload, CONCAT(N'$.', f.[key])) IS NULL
          AND ISNULL(JSON_VALUE(@payload, CONCAT(N'$.', f.[key])), NCHAR(1))
              <> ISNULL(f.value, NCHAR(1))
    )
        RETURN 0;
    RETURN 1;
END;
GO

CREATE OR ALTER PROCEDURE wf.wf_record_event_delivery
    @event_id BIGINT,
    @subscription_id BIGINT = NULL,
    @workflow_instance_id BIGINT = NULL,
    @node_execution_id BIGINT = NULL,
    @status VARCHAR(32),
    @detail NVARCHAR(256) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO wf.event_delivery (
        event_id, subscription_id, workflow_instance_id, node_execution_id, status, detail
    )
    VALUES (
        @event_id, @subscription_id, @workflow_instance_id, @node_execution_id, @status, @detail
    );
END;
GO

CREATE OR ALTER PROCEDURE wf.wf_signal_wait_event
    @event_id BIGINT,
    @event_type NVARCHAR(256),
    @payload json,
    @correlation_key NVARCHAR(256) = NULL,
    @subscription_id BIGINT = NULL,
    @workflow_version_id BIGINT = NULL,
    @applied INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET @applied = 0;

    DECLARE @ne_id BIGINT, @inst_id BIGINT, @corr_var NVARCHAR(256);
    DECLARE @expected NVARCHAR(256);
    DECLARE @body json = COALESCE(@payload, CAST(N'{}' AS json));
    DECLARE @envelope json;

    DECLARE wait_cur CURSOR LOCAL FAST_FORWARD FOR
        SELECT ne.id, ne.workflow_instance_id, wn.wait_correlation_var
        FROM wf.node_execution ne
        INNER JOIN wf.workflow_node wn ON wn.id = ne.workflow_node_id
        INNER JOIN wf.workflow_instance wi ON wi.id = ne.workflow_instance_id
        WHERE wn.node_type = N'WAIT_EVENT'
          AND wn.wait_event_type = @event_type
          AND ne.status = N'READY'
          AND wi.status = N'RUNNING'
          AND (@workflow_version_id IS NULL OR wi.workflow_version_id = @workflow_version_id)
        ORDER BY ne.id;

    OPEN wait_cur;
    FETCH NEXT FROM wait_cur INTO @ne_id, @inst_id, @corr_var;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        IF NULLIF(LTRIM(RTRIM(@corr_var)), N'') IS NOT NULL
        BEGIN
            SET @expected = LEFT(wf.wf_get_scope_variable_json(@inst_id, @ne_id, @corr_var), 256);
            IF @expected IS NOT NULL AND LEFT(LTRIM(@expected), 1) = N'"'
                SET @expected = JSON_VALUE(@expected, N'$');
            IF ISNULL(@expected, N'') <> ISNULL(@correlation_key, N'')
               AND ISNULL(@expected, N'') <> ISNULL(JSON_VALUE(@body, CONCAT(N'$.', @corr_var)), N'')
            BEGIN
                FETCH NEXT FROM wait_cur INTO @ne_id, @inst_id, @corr_var;
                CONTINUE;
            END
        END

        UPDATE wf.node_execution
        SET status = N'SUCCEEDED',
            result_code = 0,
            output_json = @body,
            ended_at_utc = SYSUTCDATETIME()
        WHERE id = @ne_id AND status = N'READY';

        IF @@ROWCOUNT > 0
        BEGIN
            SET @envelope = JSON_OBJECT(
                'id': @event_id,
                'type': @event_type,
                'correlationKey': @correlation_key,
                'payload': @body
            );
            EXEC wf.wf_set_scope_variable
                @workflow_instance_id = @inst_id,
                @scope_node_execution_id = @ne_id,
                @var_name = N'event',
                @value_json = @envelope;
            EXEC wf.wf_engine_on_action_complete
                @action_execution_id = @ne_id,
                @result_code = 0,
                @output_json = @body;
            EXEC wf.wf_record_event_delivery
                @event_id = @event_id,
                @subscription_id = @subscription_id,
                @workflow_instance_id = @inst_id,
                @node_execution_id = @ne_id,
                @status = N'applied',
                @detail = N'signal_wait';
            SET @applied = @applied + 1;
        END

        FETCH NEXT FROM wait_cur INTO @ne_id, @inst_id, @corr_var;
    END
    CLOSE wait_cur;
    DEALLOCATE wait_cur;
END;
GO

CREATE OR ALTER PROCEDURE wf.wf_start_instance_from_event
    @event_id BIGINT,
    @event_type NVARCHAR(256),
    @source NVARCHAR(128),
    @payload json,
    @correlation_key NVARCHAR(256),
    @subscription_id BIGINT,
    @workflow_version_id BIGINT,
    @instance_id BIGINT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @body json = COALESCE(@payload, CAST(N'{}' AS json));
    DECLARE @event_obj json = JSON_OBJECT(
        'id': @event_id,
        'type': @event_type,
        'source': @source,
        'correlationKey': @correlation_key,
        'payload': @body
    );
    DECLARE @project_path NVARCHAR(512) = JSON_VALUE(@body, N'$.projectPath');
    DECLARE @ctx json;
    IF @project_path IS NOT NULL AND @correlation_key IS NOT NULL
        SET @ctx = JSON_OBJECT(
            'event': @event_obj,
            'projectPath': @project_path,
            'correlationKey': @correlation_key
        );
    ELSE IF @project_path IS NOT NULL
        SET @ctx = JSON_OBJECT(
            'event': @event_obj,
            'projectPath': @project_path
        );
    ELSE IF @correlation_key IS NOT NULL
        SET @ctx = JSON_OBJECT(
            'event': @event_obj,
            'correlationKey': @correlation_key
        );
    ELSE
        SET @ctx = JSON_OBJECT('event': @event_obj);

    DECLARE @created TABLE (id BIGINT);
    INSERT INTO @created (id)
    EXEC wf.wf_repo_create_workflow_instance
        @version_id = @workflow_version_id,
        @context_json = @ctx;

    SELECT TOP 1 @instance_id = id FROM @created;
    EXEC wf.sp_start_workflow_instance @workflow_instance_id = @instance_id;
    EXEC wf.wf_record_event_delivery
        @event_id = @event_id,
        @subscription_id = @subscription_id,
        @workflow_instance_id = @instance_id,
        @status = N'applied',
        @detail = N'start_instance';
END;
GO

CREATE OR ALTER PROCEDURE wf.sp_ingest_event
    @event_type NVARCHAR(256),
    @source NVARCHAR(128),
    @idempotency_key NVARCHAR(256),
    @payload_json json = NULL,
    @correlation_key NVARCHAR(256) = NULL,
    @occurred_at_utc DATETIME2(7) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @type NVARCHAR(256) = LTRIM(RTRIM(@event_type));
    DECLARE @src NVARCHAR(128) = LTRIM(RTRIM(@source));
    DECLARE @key NVARCHAR(256) = LTRIM(RTRIM(@idempotency_key));
    DECLARE @payload json = COALESCE(@payload_json, CAST(N'{}' AS json));
    DECLARE @type_id BIGINT;
    DECLARE @event_id BIGINT;
    DECLARE @applied INT = 0;
    DECLARE @ignored INT = 0;
    DECLARE @signaled INT;
    DECLARE @inst BIGINT;
    DECLARE @sub_id BIGINT, @ver_id BIGINT, @mode VARCHAR(32), @filter json;

    IF @type IS NULL OR @type = N'' THROW 50401, N'event_type is required', 1;
    IF @src IS NULL OR @src = N'' THROW 50402, N'source is required', 1;
    IF @key IS NULL OR @key = N'' THROW 50403, N'idempotency_key is required', 1;

    EXEC wf.wf_ensure_event_type @name = @type, @id = @type_id OUTPUT;

    BEGIN TRY
        INSERT INTO wf.event (
            event_type_id, occurred_at_utc, source, idempotency_key, payload_json, correlation_key
        )
        VALUES (
            @type_id,
            COALESCE(@occurred_at_utc, SYSUTCDATETIME()),
            @src,
            @key,
            @payload,
            NULLIF(LTRIM(RTRIM(@correlation_key)), N'')
        );
        SET @event_id = SCOPE_IDENTITY();
    END TRY
    BEGIN CATCH
        IF ERROR_NUMBER() IN (2627, 2601)
        BEGIN
            SELECT @event_id = id FROM wf.event WHERE source = @src AND idempotency_key = @key;
            EXEC wf.wf_record_event_delivery
                @event_id = @event_id, @status = N'duplicate', @detail = N'idempotency';
            SELECT @event_id AS event_id, CAST(1 AS BIT) AS duplicate, 0 AS applied_count, 1 AS ignored_count;
            RETURN;
        END
        THROW;
    END CATCH

    DECLARE sub_cur CURSOR LOCAL FAST_FORWARD FOR
        SELECT s.id, s.workflow_version_id, s.mode, s.filter_json
        FROM wf.event_subscription s
        INNER JOIN wf.workflow_version wv ON wv.id = s.workflow_version_id
        WHERE s.event_type_id = @type_id AND s.enabled = 1 AND wv.is_active = 1
        ORDER BY s.id;

    OPEN sub_cur;
    FETCH NEXT FROM sub_cur INTO @sub_id, @ver_id, @mode, @filter;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        IF wf.wf_event_filter_matches(@filter, @payload) = 0
        BEGIN
            EXEC wf.wf_record_event_delivery
                @event_id = @event_id, @subscription_id = @sub_id,
                @status = N'ignored', @detail = N'filter';
            SET @ignored = @ignored + 1;
            FETCH NEXT FROM sub_cur INTO @sub_id, @ver_id, @mode, @filter;
            CONTINUE;
        END

        IF @mode IN (N'signal_wait', N'start_or_signal')
        BEGIN
            SET @signaled = 0;
            EXEC wf.wf_signal_wait_event
                @event_id = @event_id,
                @event_type = @type,
                @payload = @payload,
                @correlation_key = @correlation_key,
                @subscription_id = @sub_id,
                @workflow_version_id = @ver_id,
                @applied = @signaled OUTPUT;
            SET @applied = @applied + ISNULL(@signaled, 0);
            IF ISNULL(@signaled, 0) > 0
            BEGIN
                FETCH NEXT FROM sub_cur INTO @sub_id, @ver_id, @mode, @filter;
                CONTINUE;
            END
            IF @mode = N'signal_wait'
            BEGIN
                EXEC wf.wf_record_event_delivery
                    @event_id = @event_id, @subscription_id = @sub_id,
                    @status = N'ignored', @detail = N'no_wait';
                SET @ignored = @ignored + 1;
                FETCH NEXT FROM sub_cur INTO @sub_id, @ver_id, @mode, @filter;
                CONTINUE;
            END
        END

        IF @mode IN (N'start_instance', N'start_or_signal')
        BEGIN
            SET @inst = NULL;
            EXEC wf.wf_start_instance_from_event
                @event_id = @event_id,
                @event_type = @type,
                @source = @src,
                @payload = @payload,
                @correlation_key = @correlation_key,
                @subscription_id = @sub_id,
                @workflow_version_id = @ver_id,
                @instance_id = @inst OUTPUT;
            SET @applied = @applied + 1;
        END

        FETCH NEXT FROM sub_cur INTO @sub_id, @ver_id, @mode, @filter;
    END
    CLOSE sub_cur;
    DEALLOCATE sub_cur;

    SELECT @event_id AS event_id, CAST(0 AS BIT) AS duplicate, @applied AS applied_count, @ignored AS ignored_count;
END;
GO

CREATE OR ALTER PROCEDURE wf.sp_signal_wait
    @event_type NVARCHAR(256),
    @correlation_key NVARCHAR(256) = NULL,
    @payload_json json = NULL,
    @workflow_instance_id BIGINT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @type NVARCHAR(256) = LTRIM(RTRIM(@event_type));
    DECLARE @type_id BIGINT;
    DECLARE @event_id BIGINT;
    DECLARE @version BIGINT;
    DECLARE @applied INT = 0;
    DECLARE @payload json = COALESCE(@payload_json, CAST(N'{}' AS json));

    IF @type IS NULL OR @type = N'' THROW 50401, N'event_type is required', 1;
    EXEC wf.wf_ensure_event_type @name = @type, @id = @type_id OUTPUT;

    INSERT INTO wf.event (event_type_id, source, idempotency_key, payload_json, correlation_key)
    VALUES (
        @type_id,
        N'signal',
        CONCAT(N'signal:', @type, N':', ISNULL(@correlation_key, N''), N':', CONVERT(nvarchar(36), NEWID())),
        @payload,
        NULLIF(LTRIM(RTRIM(@correlation_key)), N'')
    );
    SET @event_id = SCOPE_IDENTITY();

    IF @workflow_instance_id IS NOT NULL
        SELECT @version = workflow_version_id FROM wf.workflow_instance WHERE id = @workflow_instance_id;

    EXEC wf.wf_signal_wait_event
        @event_id = @event_id,
        @event_type = @type,
        @payload = @payload,
        @correlation_key = @correlation_key,
        @subscription_id = NULL,
        @workflow_version_id = @version,
        @applied = @applied OUTPUT;

    IF ISNULL(@applied, 0) = 0
        EXEC wf.wf_record_event_delivery
            @event_id = @event_id,
            @workflow_instance_id = @workflow_instance_id,
            @status = N'ignored',
            @detail = N'no_wait';
END;
GO

CREATE OR ALTER PROCEDURE portal.sp_ingest_event
    @event_type NVARCHAR(256),
    @source NVARCHAR(128),
    @idempotency_key NVARCHAR(256),
    @payload_json json = NULL,
    @correlation_key NVARCHAR(256) = NULL,
    @occurred_at_utc DATETIME2(7) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    EXEC wf.sp_ingest_event
        @event_type = @event_type,
        @source = @source,
        @idempotency_key = @idempotency_key,
        @payload_json = @payload_json,
        @correlation_key = @correlation_key,
        @occurred_at_utc = @occurred_at_utc;
END;
GO
