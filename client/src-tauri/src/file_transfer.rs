use base64::{engine::general_purpose::STANDARD, Engine as _};
use std::collections::BTreeMap;

pub const CHUNK_SIZE: usize = 65536; // 64KB, matches shared.py clients

pub fn md5_hex(data: &[u8]) -> String {
    format!("{:x}", md5::compute(data))
}

/// Splits raw bytes into base64-encoded 64KB chunks (director side, before sending FILECHUNK).
pub fn split_into_chunks(data: &[u8]) -> Vec<String> {
    data.chunks(CHUNK_SIZE).map(|c| STANDARD.encode(c)).collect()
}

/// Extracts the character name from a filename following the " - Character.ext" convention
/// used by director_client_ws.py's routing dialog, e.g. "Scene1_Line04 - Alice.wav" -> "Alice".
pub fn extract_character(filename: &str) -> Option<String> {
    let stem = filename.rsplit_once('.').map(|(s, _)| s).unwrap_or(filename);
    stem.rsplit_once(" - ").map(|(_, character)| character.trim().to_string()).filter(|c| !c.is_empty())
}

/// Accumulates base64 chunks for one in-progress file receive (actor side).
#[derive(Default)]
pub struct FileReceiveBuffer {
    chunks: BTreeMap<u32, Vec<u8>>,
}

impl FileReceiveBuffer {
    pub fn add_chunk(&mut self, chunk_num: u32, b64_data: &str) -> Result<(), String> {
        let bytes = STANDARD.decode(b64_data).map_err(|e| format!("Invalid base64: {}", e))?;
        self.chunks.insert(chunk_num, bytes);
        Ok(())
    }

    /// Assembles chunks in order and verifies the MD5 checksum. Returns the assembled
    /// bytes on success, or an error string (matching FILEERR reason text) on mismatch.
    pub fn finalize(&self, expected_checksum: &str) -> Result<Vec<u8>, String> {
        let mut data = Vec::new();
        for (_, chunk) in &self.chunks {
            data.extend_from_slice(chunk);
        }
        let actual = md5_hex(&data);
        if actual != expected_checksum {
            return Err(format!("Checksum mismatch: expected {}, got {}", expected_checksum, actual));
        }
        Ok(data)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn md5_hex_matches_known_vector() {
        // MD5("") == d41d8cd98f00b204e9800998ecf8427e
        assert_eq!(md5_hex(b""), "d41d8cd98f00b204e9800998ecf8427e");
    }

    #[test]
    fn split_into_chunks_respects_chunk_size() {
        let data = vec![0u8; CHUNK_SIZE * 2 + 10];
        let chunks = split_into_chunks(&data);
        assert_eq!(chunks.len(), 3);
        // Each base64 chunk decodes back to <= CHUNK_SIZE raw bytes.
        for c in &chunks {
            let decoded = STANDARD.decode(c).unwrap();
            assert!(decoded.len() <= CHUNK_SIZE);
        }
    }

    #[test]
    fn extract_character_parses_dash_pattern() {
        assert_eq!(extract_character("Scene1_Line04 - Alice.wav"), Some("Alice".to_string()));
    }

    #[test]
    fn extract_character_returns_none_without_pattern() {
        assert_eq!(extract_character("just_a_file.wav"), None);
    }

    #[test]
    fn extract_character_handles_multiple_dashes() {
        // Only the LAST " - " before the extension separates the character.
        assert_eq!(extract_character("Take-2 - Bob.mp3"), Some("Bob".to_string()));
    }

    #[test]
    fn receive_buffer_assembles_out_of_order_chunks() {
        let mut buf = FileReceiveBuffer::default();
        let full_data = b"hello world, this is a test file".to_vec();
        let chunks = split_into_chunks(&full_data);
        assert!(chunks.len() >= 1);
        // Insert in reverse order to prove BTreeMap reorders by chunk_num.
        for (i, c) in chunks.iter().enumerate().rev() {
            buf.add_chunk(i as u32, c).unwrap();
        }
        let checksum = md5_hex(&full_data);
        let assembled = buf.finalize(&checksum).unwrap();
        assert_eq!(assembled, full_data);
    }

    #[test]
    fn receive_buffer_rejects_bad_checksum() {
        let mut buf = FileReceiveBuffer::default();
        buf.add_chunk(0, &STANDARD.encode(b"corrupted")).unwrap();
        let result = buf.finalize("0000000000000000000000000000000");
        assert!(result.is_err());
    }
}
