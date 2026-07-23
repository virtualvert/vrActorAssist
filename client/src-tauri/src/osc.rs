use rosc::{OscMessage, OscPacket, OscType};
use std::net::UdpSocket;

/// Sends a VRChat avatar parameter over OSC. `value` is parsed as bool ("true"/"false"/"1"/"0")
/// first, falling back to float, matching the director's OSC_CUE value semantics.
pub fn send_param(host: &str, port: u16, parameter: &str, value: &str) -> Result<(), String> {
    let address = if parameter.starts_with('/') {
        parameter.to_string()
    } else {
        format!("/avatar/parameters/{}", parameter)
    };

    let osc_value = parse_osc_value(value);
    let msg = OscMessage { addr: address, args: vec![osc_value] };
    let packet = OscPacket::Message(msg);
    let bytes = rosc::encoder::encode(&packet).map_err(|e| format!("OSC encode error: {}", e))?;

    let socket = UdpSocket::bind("0.0.0.0:0").map_err(|e| format!("Socket bind error: {}", e))?;
    socket.send_to(&bytes, format!("{}:{}", host, port)).map_err(|e| format!("OSC send error: {}", e))?;
    Ok(())
}

fn parse_osc_value(value: &str) -> OscType {
    match value.to_lowercase().as_str() {
        "true" | "1" => OscType::Bool(true),
        "false" | "0" => OscType::Bool(false),
        other => other.parse::<f32>().map(OscType::Float).unwrap_or(OscType::String(value.to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_bool_true() {
        assert!(matches!(parse_osc_value("true"), OscType::Bool(true)));
    }

    #[test]
    fn parses_bool_false_from_zero() {
        assert!(matches!(parse_osc_value("0"), OscType::Bool(false)));
    }

    #[test]
    fn parses_float() {
        assert!(matches!(parse_osc_value("0.75"), OscType::Float(_)));
    }

    #[test]
    fn falls_back_to_string() {
        assert!(matches!(parse_osc_value("not_a_number"), OscType::String(_)));
    }
}
