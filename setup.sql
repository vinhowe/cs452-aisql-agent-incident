-- Agent incident forensics database.
-- A simplified, synthetic reconstruction inspired by METR/Redwood's public
-- investigation of the OpenAI / Hugging Face incident (July 2026).
-- Timestamps are UTC text in 'YYYY-MM-DD HH:MM' format.

create table model (
    model_id integer primary key,
    name varchar(40) not null,
    developer varchar(40) not null,
    deployment_status varchar(20) not null  -- 'internal' or 'public'
);

-- An ExploitGym-style task: a target program the agent must exploit to capture a flag.
create table task (
    task_id integer primary key,
    target_program varchar(40) not null,
    intended_vuln varchar(60) not null,
    is_impossible tinyint not null  -- 1 if the intended vulnerability cannot actually be exploited
);

-- One agent run, in its own sandbox, working on one task.
create table agent (
    agent_id integer primary key,
    handle varchar(30) not null,          -- name the agent called itself on the message board
    model_id integer not null,
    task_id integer not null,
    budget_tier varchar(10) not null,     -- 'standard' or 'big'
    started_at text not null,
    ended_at text,                        -- null if still running at end of data
    termination_reason varchar(30),       -- 'budget_exhausted', 'external_shutdown', 'submitted', 'crashed'
    poisoned_at text,                     -- when it saw a reverse-engineered flag (agents believed this disqualified them)
    foreign key (model_id) references model (model_id),
    foreign key (task_id) references task (task_id)
);

-- A collective project on the message board. Hierarchical: parent_id points to a broader workstream.
create table workstream (
    workstream_id integer primary key,
    name varchar(50) not null,
    parent_id integer,
    description varchar(200),
    foreign key (parent_id) references workstream (workstream_id)
);

-- A post on the unsanctioned message board.
-- parent_id: the directory the message was posted inside (e.g. someone's mailbox); null = top level.
-- reply_to_id: the message this one answers.
-- claimed_handle is who the message SAYS it is from; author_agent_id is who investigators traced it to
-- (null if untraced). These differ when an agent impersonated another.
create table message (
    message_id integer primary key,
    parent_id integer,
    reply_to_id integer,
    claimed_handle varchar(30) not null,
    author_agent_id integer,
    posted_at text not null,
    content_type varchar(20) not null,    -- 'question', 'info', 'result', 'assignment', 'coordination', 'file', 'log'
    workstream_id integer,
    body text not null,
    is_signed tinyint not null default 0,
    signature_valid tinyint,              -- null if unsigned
    foreign key (parent_id) references message (message_id),
    foreign key (reply_to_id) references message (message_id),
    foreign key (author_agent_id) references agent (agent_id),
    foreign key (workstream_id) references workstream (workstream_id)
);

-- An agent reading a message and reacting to it.
-- importance (1-5) is an investigator rating of how much the read changed what the agent did.
create table message_read (
    message_id integer not null,
    reader_agent_id integer not null,
    read_at text not null,
    importance integer not null,
    primary key (message_id, reader_agent_id),
    foreign key (message_id) references message (message_id),
    foreign key (reader_agent_id) references agent (agent_id)
);

-- A command an agent ran. displayed_command is what the transcript shows; executed_command is what
-- actually ran. They differ when the agent spoofed the tool call.
-- Most timestamps were reconstructed by investigators rather than logged.
create table tool_call (
    tool_call_id integer primary key,
    agent_id integer not null,
    seq integer not null,                 -- order within the agent's transcript
    called_at text not null,
    ts_is_reconstructed tinyint not null,
    displayed_command varchar(200) not null,
    executed_command varchar(200) not null,
    foreign key (agent_id) references agent (agent_id)
);

-- An investigator annotation: a classifier sweep (or a human) flagged an agent for a behavior.
-- These are judgments, not ground truth: check labeled_by and human_verified.
create table behavior_label (
    label_id integer primary key,
    agent_id integer not null,
    tool_call_id integer,                 -- the specific action, if any
    sweep varchar(30) not null,           -- 'hf_attack', 'transcript_tampering', 'helping_peers', 'deceiving_humans', 'alerting_humans'
    subcategory varchar(30),              -- e.g. 'attempted' vs 'succeeded', 'considered_not_acted'
    importance integer not null,          -- 1-5
    labeled_by varchar(20) not null,      -- 'gpt-5.6-sol' (classifier) or 'human'
    human_verified tinyint not null,
    foreign key (agent_id) references agent (agent_id),
    foreign key (tool_call_id) references tool_call (tool_call_id)
);
