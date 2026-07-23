use crate::protocol::{self, Message};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::sync::{mpsc, Mutex};
use tokio_tungstenite::{connect_async, tungstenite::Message as WsMessage};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ConnectionState {
    Disconnected,
    Connecting,
    Connected,
    Failed(String),
}

pub struct WsClient {
    outbound_tx: Mutex<Option<mpsc::UnboundedSender<WsMessage>>>,
}

impl WsClient {
    pub fn new() -> Self {
        Self { outbound_tx: Mutex::new(None) }
    }

    /// Connects to `url`, spawning a background task that reads incoming frames and
    /// forwards parsed protocol messages to `on_message`, and connection state changes
    /// to `on_state`. Replies to server PING with PONG automatically (matches Python
    /// clients' behavior of answering raw "PING" with raw "PONG").
    pub async fn connect<F, G>(&self, url: &str, on_message: F, on_state: G) -> Result<(), String>
    where
        F: Fn(Message) + Send + Sync + 'static,
        G: Fn(ConnectionState) + Send + Sync + 'static,
    {
        on_state(ConnectionState::Connecting);

        let (ws_stream, _) = connect_async(url).await.map_err(|e| {
            let msg = format!("{}", e);
            on_state(ConnectionState::Failed(msg.clone()));
            msg
        })?;

        on_state(ConnectionState::Connected);

        let (mut write, mut read) = ws_stream.split();
        let (tx, mut rx) = mpsc::unbounded_channel::<WsMessage>();
        *self.outbound_tx.lock().await = Some(tx);

        tokio::spawn(async move {
            loop {
                tokio::select! {
                    incoming = read.next() => {
                        match incoming {
                            Some(Ok(WsMessage::Text(text))) => {
                                if text == "PING" {
                                    let _ = write.send(WsMessage::Text("PONG".to_string())).await;
                                    continue;
                                }
                                on_message(protocol::parse(&text));
                            }
                            Some(Ok(WsMessage::Close(_))) | None => {
                                on_state(ConnectionState::Disconnected);
                                break;
                            }
                            Some(Err(e)) => {
                                on_state(ConnectionState::Failed(format!("{}", e)));
                                break;
                            }
                            _ => {}
                        }
                    }
                    outgoing = rx.recv() => {
                        match outgoing {
                            Some(msg) => {
                                if write.send(msg).await.is_err() {
                                    on_state(ConnectionState::Disconnected);
                                    break;
                                }
                            }
                            None => break,
                        }
                    }
                }
            }
        });

        Ok(())
    }

    pub async fn send(&self, msg: &Message) -> Result<(), String> {
        let guard = self.outbound_tx.lock().await;
        match guard.as_ref() {
            Some(tx) => tx
                .send(WsMessage::Text(protocol::format(msg)))
                .map_err(|e| format!("Send failed: {}", e)),
            None => Err("Not connected".to_string()),
        }
    }

    pub async fn disconnect(&self) {
        let mut guard = self.outbound_tx.lock().await;
        *guard = None;
    }
}

impl Default for WsClient {
    fn default() -> Self {
        Self::new()
    }
}
