use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum Message {
    Msg { sender: String, text: String },
    Priv { sender: String, target: String, text: String },
    Users { users: Vec<String> },
    Status { actors_json: String },
    Register { name: String, machine_id: String, role: String, secret: String, version: String, platform: String },
    Approved,
    Denied { reason: String },
    Pending { actors_json: String },
    Version { status: String, server_version: String, message: String },
    Update { latest_version: String, download_url: String, sha256: String, release_notes: String },
    Cmd { command: String, args: String },
    Ack { actor: String, command: String, status: String },
    File { sender: String, filename: String, size: u64 },
    Forget { machine_id: String },
    ForgetName { name: String },
    Approve { machine_id: String },
    Deny { machine_id: String },
    OscCue { target: String, parameter: String, value: String },
    FileReq { sender: String, target: String, filename: String, size: u64, checksum: String },
    FileAck { filename: String, accept: bool, save_dir: String },
    FileDeny { filename: String, reason: String },
    FileStart { filename: String, total_chunks: u32, chunk_size: u32 },
    FileChunk { filename: String, chunk_num: u32, data: String },
    FileEnd { filename: String, checksum: String },
    FileOk { filename: String, saved_path: String },
    FileErr { filename: String, error: String },
    BatchStart { target: String, file_count: u32, total_bytes: u64 },
    BatchEnd { target: String, success_count: u32, fail_count: u32 },
    BatchCancel { target: String, reason: String },
    Refresh,
    Ping,
    Pong,
    Unknown { raw: String },
}

pub fn parse(data: &str) -> Message {
    let parts: Vec<&str> = data.split('|').collect();
    if parts.is_empty() {
        return Message::Unknown { raw: data.to_string() };
    }
    let p = |i: usize| parts.get(i).map(|s| s.to_string()).unwrap_or_default();
    let rejoin = |from: usize| parts[from.min(parts.len())..].join("|");

    match parts[0] {
        "MSG" if parts.len() >= 3 => Message::Msg { sender: p(1), text: rejoin(2) },
        "PRIV" if parts.len() >= 4 => Message::Priv { sender: p(1), target: p(2), text: rejoin(3) },
        "USERS" if parts.len() >= 2 => Message::Users {
            users: if parts[1].is_empty() { vec![] } else { parts[1].split(',').map(String::from).collect() },
        },
        "STATUS" if parts.len() >= 2 => Message::Status { actors_json: p(1) },
        "REGISTER" if parts.len() >= 4 => Message::Register {
            name: p(1), machine_id: p(2), role: p(3), secret: p(4), version: p(5), platform: p(6),
        },
        "APPROVED" => Message::Approved,
        "DENIED" if parts.len() >= 2 => Message::Denied { reason: rejoin(1) },
        "PENDING" if parts.len() >= 2 => Message::Pending { actors_json: p(1) },
        "VERSION" if parts.len() >= 2 => Message::Version {
            status: p(1), server_version: p(2), message: rejoin(3),
        },
        "UPDATE" if parts.len() >= 2 => Message::Update {
            latest_version: p(1), download_url: p(2), sha256: p(3), release_notes: rejoin(4),
        },
        "CMD" if parts.len() >= 2 => Message::Cmd { command: p(1), args: rejoin(2) },
        "ACK" if parts.len() >= 4 => Message::Ack { actor: p(1), command: p(2), status: p(3) },
        "FILE" if parts.len() >= 4 => Message::File {
            sender: p(1), filename: p(2), size: parts[3].parse().unwrap_or(0),
        },
        "FORGET" if parts.len() >= 2 => Message::Forget { machine_id: p(1) },
        "FORGET_NAME" if parts.len() >= 2 => Message::ForgetName { name: p(1) },
        "APPROVE" => Message::Approve { machine_id: p(1) },
        "DENY" => Message::Deny { machine_id: p(1) },
        "OSC_CUE" if parts.len() >= 4 => Message::OscCue { target: p(1), parameter: p(2), value: p(3) },
        "FILEREQ" if parts.len() >= 6 => Message::FileReq {
            sender: p(1), target: p(2), filename: p(3), size: parts[4].parse().unwrap_or(0), checksum: p(5),
        },
        "FILEACK" if parts.len() >= 3 => Message::FileAck {
            filename: p(1), accept: parts[2] == "1", save_dir: p(3),
        },
        "FILEDENY" if parts.len() >= 3 => Message::FileDeny { filename: p(1), reason: rejoin(2) },
        "FILESTART" if parts.len() >= 4 => Message::FileStart {
            filename: p(1), total_chunks: parts[2].parse().unwrap_or(0), chunk_size: parts[3].parse().unwrap_or(0),
        },
        "FILECHUNK" if parts.len() >= 4 => Message::FileChunk {
            filename: p(1), chunk_num: parts[2].parse().unwrap_or(0), data: rejoin(3),
        },
        "FILEEND" if parts.len() >= 3 => Message::FileEnd { filename: p(1), checksum: p(2) },
        "FILEOK" if parts.len() >= 3 => Message::FileOk { filename: p(1), saved_path: rejoin(2) },
        "FILEERR" if parts.len() >= 3 => Message::FileErr { filename: p(1), error: rejoin(2) },
        "BATCH_START" if parts.len() >= 4 => Message::BatchStart {
            target: p(1), file_count: parts[2].parse().unwrap_or(0), total_bytes: parts[3].parse().unwrap_or(0),
        },
        "BATCH_END" if parts.len() >= 4 => Message::BatchEnd {
            target: p(1), success_count: parts[2].parse().unwrap_or(0), fail_count: parts[3].parse().unwrap_or(0),
        },
        "BATCH_CANCEL" if parts.len() >= 2 => Message::BatchCancel { target: p(1), reason: rejoin(2) },
        "REFRESH" => Message::Refresh,
        "PING" if parts.len() == 1 => Message::Ping,
        "PONG" if parts.len() == 1 => Message::Pong,
        _ => Message::Unknown { raw: data.to_string() },
    }
}

pub fn format(msg: &Message) -> String {
    match msg {
        Message::Msg { sender, text } => format!("MSG|{}|{}", sender, text),
        Message::Priv { sender, target, text } => format!("PRIV|{}|{}|{}", sender, target, text),
        Message::Users { users } => format!("USERS|{}", users.join(",")),
        Message::Status { actors_json } => format!("STATUS|{}", actors_json),
        Message::Register { name, machine_id, role, secret, version, platform } =>
            format!("REGISTER|{}|{}|{}|{}|{}|{}", name, machine_id, role, secret, version, platform),
        Message::Approved => "APPROVED".to_string(),
        Message::Denied { reason } => format!("DENIED|{}", reason),
        Message::Pending { actors_json } => format!("PENDING|{}", actors_json),
        Message::Version { status, server_version, message } => format!("VERSION|{}|{}|{}", status, server_version, message),
        Message::Update { latest_version, download_url, sha256, release_notes } =>
            format!("UPDATE|{}|{}|{}|{}", latest_version, download_url, sha256, release_notes),
        Message::Cmd { command, args } => if args.is_empty() { format!("CMD|{}", command) } else { format!("CMD|{}|{}", command, args) },
        Message::Ack { actor, command, status } => format!("ACK|{}|{}|{}", actor, command, status),
        Message::File { sender, filename, size } => format!("FILE|{}|{}|{}", sender, filename, size),
        Message::Forget { machine_id } => format!("FORGET|{}", machine_id),
        Message::ForgetName { name } => format!("FORGET_NAME|{}", name),
        Message::Approve { machine_id } => format!("APPROVE|{}", machine_id),
        Message::Deny { machine_id } => format!("DENY|{}", machine_id),
        Message::OscCue { target, parameter, value } => format!("OSC_CUE|{}|{}|{}", target, parameter, value),
        Message::FileReq { sender, target, filename, size, checksum } =>
            format!("FILEREQ|{}|{}|{}|{}|{}", sender, target, filename, size, checksum),
        Message::FileAck { filename, accept, save_dir } =>
            format!("FILEACK|{}|{}|{}", filename, if *accept { "1" } else { "0" }, save_dir),
        Message::FileDeny { filename, reason } => format!("FILEDENY|{}|{}", filename, reason),
        Message::FileStart { filename, total_chunks, chunk_size } => format!("FILESTART|{}|{}|{}", filename, total_chunks, chunk_size),
        Message::FileChunk { filename, chunk_num, data } => format!("FILECHUNK|{}|{}|{}", filename, chunk_num, data),
        Message::FileEnd { filename, checksum } => format!("FILEEND|{}|{}", filename, checksum),
        Message::FileOk { filename, saved_path } => format!("FILEOK|{}|{}", filename, saved_path),
        Message::FileErr { filename, error } => format!("FILEERR|{}|{}", filename, error),
        Message::BatchStart { target, file_count, total_bytes } => format!("BATCH_START|{}|{}|{}", target, file_count, total_bytes),
        Message::BatchEnd { target, success_count, fail_count } => format!("BATCH_END|{}|{}|{}", target, success_count, fail_count),
        Message::BatchCancel { target, reason } => format!("BATCH_CANCEL|{}|{}", target, reason),
        Message::Refresh => "REFRESH".to_string(),
        Message::Ping => "PING".to_string(),
        Message::Pong => "PONG".to_string(),
        Message::Unknown { raw } => raw.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_msg() {
        let m = parse("MSG|Director|Hello everyone");
        assert_eq!(m, Message::Msg { sender: "Director".into(), text: "Hello everyone".into() });
    }

    #[test]
    fn parses_msg_with_pipe_in_text() {
        // Text may legitimately contain '|' — must rejoin remaining parts
        let m = parse("MSG|Director|a|b|c");
        assert_eq!(m, Message::Msg { sender: "Director".into(), text: "a|b|c".into() });
    }

    #[test]
    fn parses_priv_command() {
        let m = parse("PRIV|Director|Actor1|*go");
        assert_eq!(m, Message::Priv { sender: "Director".into(), target: "Actor1".into(), text: "*go".into() });
    }

    #[test]
    fn parses_register_full() {
        let m = parse("REGISTER|Director|abc-123|director|secret1|0.4.0|windows-x64");
        assert_eq!(m, Message::Register {
            name: "Director".into(),
            machine_id: "abc-123".into(),
            role: "director".into(),
            secret: "secret1".into(),
            version: "0.4.0".into(),
            platform: "windows-x64".into(),
        });
    }

    #[test]
    fn parses_approved() {
        assert_eq!(parse("APPROVED"), Message::Approved);
    }

    #[test]
    fn parses_denied_with_reason() {
        let m = parse("DENIED|secret mismatch");
        assert_eq!(m, Message::Denied { reason: "secret mismatch".into() });
    }

    #[test]
    fn parses_cmd_no_args() {
        let m = parse("CMD|*go");
        assert_eq!(m, Message::Cmd { command: "*go".into(), args: "".into() });
    }

    #[test]
    fn parses_filechunk() {
        let m = parse("FILECHUNK|line01.wav|3|c29tZWJhc2U2NA==");
        assert_eq!(m, Message::FileChunk { filename: "line01.wav".into(), chunk_num: 3, data: "c29tZWJhc2U2NA==".into() });
    }

    #[test]
    fn parses_osc_cue() {
        let m = parse("OSC_CUE|Actor1|RecIcon|true");
        assert_eq!(m, Message::OscCue { target: "Actor1".into(), parameter: "RecIcon".into(), value: "true".into() });
    }

    #[test]
    fn parses_batch_start() {
        let m = parse("BATCH_START|Actor1|3|1048576");
        assert_eq!(m, Message::BatchStart { target: "Actor1".into(), file_count: 3, total_bytes: 1048576 });
    }

    #[test]
    fn parses_raw_ping_pong() {
        assert_eq!(parse("PING"), Message::Ping);
        assert_eq!(parse("PONG"), Message::Pong);
    }

    #[test]
    fn parses_unknown_as_fallback() {
        let m = parse("NOT_A_REAL_TYPE|x|y");
        assert_eq!(m, Message::Unknown { raw: "NOT_A_REAL_TYPE|x|y".into() });
    }

    #[test]
    fn formats_register_round_trips() {
        let msg = Message::Register {
            name: "Actor1".into(), machine_id: "id-1".into(), role: "actor".into(),
            secret: "".into(), version: "0.4.0".into(), platform: "linux-x64".into(),
        };
        let wire = format(&msg);
        assert_eq!(wire, "REGISTER|Actor1|id-1|actor||0.4.0|linux-x64");
        assert_eq!(parse(&wire), msg);
    }

    #[test]
    fn formats_priv_command_round_trips() {
        let msg = Message::Priv { sender: "Director".into(), target: "Actor1".into(), text: "*stop".into() };
        let wire = format(&msg);
        assert_eq!(wire, "PRIV|Director|Actor1|*stop");
        assert_eq!(parse(&wire), msg);
    }

    #[test]
    fn formats_filereq_round_trips() {
        let msg = Message::FileReq {
            sender: "Director".into(), target: "Actor1".into(), filename: "cue.wav".into(),
            size: 2048, checksum: "d41d8cd98f00b204e9800998ecf8427e".into(),
        };
        let wire = format(&msg);
        assert_eq!(wire, "FILEREQ|Director|Actor1|cue.wav|2048|d41d8cd98f00b204e9800998ecf8427e");
        assert_eq!(parse(&wire), msg);
    }
}