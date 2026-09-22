-- Engine procedures required by workflow_engine/contract/db_objects.yaml.
-- Definitions live in the wf schema. The MethylPipeline.sql dump is a GoliathOmics artifact
-- and is not the platform source for these objects.
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

CREATE OR ALTER FUNCTION wf.wf_json_fragment_from_string(@s NVARCHAR(MAX))
RETURNS NVARCHAR(MAX)
AS
BEGIN
    RETURN N'"' + REPLACE(REPLACE(REPLACE(@s, N'\', N'\\'), N'"', N'\"'), CHAR(10), N'\n') + N'"';
END;
GO

CREATE OR ALTER FUNCTION wf.wf_try_task_result_code(@workflow_instance_id BIGINT, @node_key NVARCHAR(128))
RETURNS INT
AS
BEGIN
    DECLARE @r INT;
    SELECT TOP (1) @r = ne.result_code
    FROM wf.node_execution AS ne
    INNER JOIN wf.workflow_node AS wn ON wn.id = ne.workflow_node_id
    WHERE ne.workflow_instance_id = @workflow_instance_id
      AND wn.node_key = @node_key
      AND ne.status = N'SUCCEEDED'
    ORDER BY ne.ended_at_utc DESC, ne.id DESC;
    RETURN @r;
END;
GO

CREATE OR ALTER FUNCTION wf.wf_try_task_output_json(@workflow_instance_id BIGINT, @node_key NVARCHAR(128), @jsonPath NVARCHAR(4000))
RETURNS NVARCHAR(MAX)
AS
BEGIN
    DECLARE @out NVARCHAR(MAX);
    SELECT TOP (1) @out = CAST(ne.output_json AS NVARCHAR(MAX))
    FROM wf.node_execution AS ne
    INNER JOIN wf.workflow_node AS wn ON wn.id = ne.workflow_node_id
    WHERE ne.workflow_instance_id = @workflow_instance_id
      AND wn.node_key = @node_key
      AND ne.status = N'SUCCEEDED'
    ORDER BY ne.ended_at_utc DESC, ne.id DESC;

    IF @out IS NULL RETURN NULL;

    IF @jsonPath IS NULL OR LTRIM(RTRIM(@jsonPath)) = N'' RETURN @out;

    IF LEFT(@jsonPath, 1) <> N'$' SET @jsonPath = N'$.' + @jsonPath;

    DECLARE @jq NVARCHAR(MAX) = JSON_QUERY(@out, @jsonPath);
    IF @jq IS NOT NULL RETURN @jq;

    DECLARE @jv NVARCHAR(MAX) = JSON_VALUE(@out, @jsonPath);
    IF @jv IS NULL RETURN NULL;

    DECLARE @bi BIGINT = TRY_CONVERT(BIGINT, @jv);
    IF @bi IS NOT NULL AND CAST(@bi AS NVARCHAR(50)) = LTRIM(RTRIM(@jv))
        RETURN CAST(@bi AS NVARCHAR(50));

    RETURN wf.wf_json_fragment_from_string(@jv);
END;
GO

CREATE OR ALTER PROCEDURE wf.wf_parallel_continue
    @parallel_execution_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @inst BIGINT;
    DECLARE @pnode BIGINT;
    SELECT @inst = workflow_instance_id, @pnode = workflow_node_id FROM wf.node_execution WHERE id = @parallel_execution_id;

    IF NOT EXISTS (
        SELECT 1 FROM wf.workflow_instance
        WHERE id = @inst AND status = N'RUNNING'
    )
        RETURN;

    DECLARE @total INT = (SELECT COUNT(*) FROM wf.workflow_edge WHERE parent_node_id = @pnode);

    DECLARE @finished INT = (
        SELECT COUNT(*)
        FROM wf.node_execution AS ne
        WHERE ne.parent_node_execution_id = @parallel_execution_id
          AND ne.status IN (N'SUCCEEDED', N'FAILED', N'SKIPPED', N'CANCELLED')
    );

    IF @finished < @total RETURN;

    IF EXISTS (
        SELECT 1 FROM wf.node_execution
        WHERE parent_node_execution_id = @parallel_execution_id AND status = N'FAILED'
    )
    BEGIN
        UPDATE wf.node_execution SET status = N'FAILED', ended_at_utc = SYSUTCDATETIME() WHERE id = @parallel_execution_id;
        UPDATE wf.workflow_instance SET status = N'FAILED', completed_at_utc = SYSUTCDATETIME() WHERE id = @inst AND status = N'RUNNING';
        RETURN;
    END

    UPDATE wf.node_execution SET status = N'SUCCEEDED', ended_at_utc = SYSUTCDATETIME() WHERE id = @parallel_execution_id;
    EXEC wf.wf_engine_on_composite_complete @node_execution_id = @parallel_execution_id;
END;
GO

CREATE OR ALTER PROCEDURE wf.wf_repeat_continue
    @repeat_execution_id BIGINT
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @inst BIGINT;
    DECLARE @ctl BIGINT;
    DECLARE @ls BIGINT;
    DECLARE @cur INT;
    DECLARE @max INT;

    SELECT @inst = workflow_instance_id, @ctl = workflow_node_id FROM wf.node_execution WHERE id = @repeat_execution_id;
    SELECT TOP (1)
        @ls = id,
        @cur = current_iteration,
        @max = repeat_target_count
    FROM wf.loop_state
    WHERE scope_node_execution_id = @repeat_execution_id;

    IF @ls IS NULL
    BEGIN
        UPDATE wf.node_execution SET status = N'FAILED', engine_error_code = 10007, ended_at_utc = SYSUTCDATETIME() WHERE id = @repeat_execution_id;
        UPDATE wf.workflow_instance SET status = N'FAILED', completed_at_utc = SYSUTCDATETIME() WHERE id = @inst;
        RETURN;
    END

    SET @cur += 1;
    UPDATE wf.loop_state SET current_iteration = @cur WHERE id = @ls;

    IF @cur >= @max
    BEGIN
        UPDATE wf.node_execution SET status = N'SUCCEEDED', ended_at_utc = SYSUTCDATETIME() WHERE id = @repeat_execution_id;
        EXEC wf.wf_engine_on_composite_complete @node_execution_id = @repeat_execution_id;
        RETURN;
    END

    DECLARE @body BIGINT;
    SELECT TOP (1) @body = child_node_id FROM wf.workflow_edge WHERE parent_node_id = @ctl AND branch_kind = N'BODY' ORDER BY child_order ASC;

    DECLARE @cur1 INT = @cur + 1;
    EXEC wf.wf_engine_activate
        @workflow_instance_id = @inst,
        @workflow_node_id = @body,
        @parent_node_execution_id = @repeat_execution_id,
        @iteration_no = @cur1,
        @sequence_index = NULL,
        @parallel_index = NULL;
END;
GO

CREATE OR ALTER PROCEDURE wf.wf_worker_authenticate
    @worker_id BIGINT,
    @worker_token NVARCHAR(4000)
AS
BEGIN
    SET NOCOUNT ON;

    IF @worker_id IS NULL
        THROW 50002, N'worker_id is required.', 1;

    DECLARE @tok NVARCHAR(4000) = NULLIF(LTRIM(RTRIM(@worker_token)), N'');
    IF @tok IS NULL
        THROW 50002, N'worker_token is required.', 1;

    DECLARE @hash VARBINARY(32) = HASHBYTES(N'SHA2_256', @tok);

    IF NOT EXISTS (
        SELECT 1
        FROM wf.worker_token AS wt
        INNER JOIN wf.worker AS w ON w.id = wt.worker_id
        INNER JOIN wf.cluster AS c ON c.id = w.cluster_id
        WHERE wt.worker_id = @worker_id
          AND wt.token_hash = @hash
          AND wt.status = N'ACTIVE'
          AND (wt.expires_at_utc IS NULL OR wt.expires_at_utc > SYSUTCDATETIME())
          AND w.status = N'REGISTERED'
          AND c.status = N'ACTIVE'
    )
        THROW 50003, N'Invalid or unauthorized worker credentials.', 1;

    UPDATE wf.worker
    SET last_seen_at_utc = SYSUTCDATETIME()
    WHERE id = @worker_id;
END;
GO

CREATE OR ALTER PROCEDURE wf.sp_worker_fail_task
    @node_execution_id BIGINT,
    @worker_id BIGINT,
    @worker_token NVARCHAR(4000),
    @error_code INT,
    @error_message NVARCHAR(1024) NULL
AS
BEGIN
    SET NOCOUNT ON;

    EXEC wf.wf_worker_authenticate @worker_id = @worker_id, @worker_token = @worker_token;

    IF NOT EXISTS (
        SELECT 1 FROM wf.task_lease WHERE node_execution_id = @node_execution_id AND worker_id = @worker_id
    )
        RETURN;

    UPDATE wf.node_execution
    SET status = N'FAILED',
        engine_error_code = @error_code,
        engine_error_message = @error_message,
        ended_at_utc = SYSUTCDATETIME()
    WHERE id = @node_execution_id AND status = N'RUNNING';

    DELETE FROM wf.task_lease WHERE node_execution_id = @node_execution_id;

    -- Do not mark workflow_instance FAILED here: one sample action failure must not
    -- strand sibling READY tasks in a FOREACH (SamplePrep Align fan-out).
END;
GO

