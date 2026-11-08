//! Native update HTTP is allowed only while the core grants a cancellable lease.
//! This connection carries no settings copy. Losing it cancels HTTP, never grants access.
use futures_util::{SinkExt, StreamExt};
use hmac::{Hmac, Mac};
use serde_json::{json, Value};
use sha2::Sha256;
use std::{
    future::Future,
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};
use tokio::{net::TcpStream, sync::Notify, time::timeout};
use tokio_tungstenite::{connect_async, tungstenite::Message, MaybeTlsStream, WebSocketStream};

type Socket = WebSocketStream<MaybeTlsStream<TcpStream>>;
const RPC_TIMEOUT: Duration = Duration::from_secs(10);
const CANCELLED: &str = "Update cancelled";

#[derive(Default)]
pub struct Cancellation {
    generation: AtomicU64,
    notify: Notify,
}

impl Cancellation {
    pub fn generation(&self) -> u64 {
        self.generation.load(Ordering::SeqCst)
    }
    pub fn cancel(&self) {
        self.generation.fetch_add(1, Ordering::SeqCst);
        self.notify.notify_waiters();
    }
    async fn cancelled(&self, generation: u64) {
        loop {
            // Register before inspecting the generation; cancellation cannot fall in a gap.
            let notified = self.notify.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            if self.generation() != generation {
                return;
            }
            notified.await;
        }
    }
}

async fn receive(socket: &mut Socket) -> Result<Value, String> {
    loop {
        match socket.next().await {
            Some(Ok(Message::Text(text))) => {
                return serde_json::from_str(&text).map_err(|e| e.to_string())
            }
            Some(Ok(Message::Ping(_))) | Some(Ok(Message::Pong(_))) => continue,
            _ => return Err("Core connection lost; update stopped".into()),
        }
    }
}

async fn rpc(
    socket: &mut Socket,
    id: u32,
    method: &str,
    params: Value,
    cancelled: &mut bool,
) -> Result<Value, String> {
    timeout(RPC_TIMEOUT, async {
        socket
            .send(Message::Text(
                json!({"jsonrpc":"2.0", "id":id, "method":method, "params":params})
                    .to_string()
                    .into(),
            ))
            .await
            .map_err(|e| e.to_string())?;
        loop {
            let message = receive(socket).await?;
            if message["method"] == "updates.cancel" {
                *cancelled = true;
            }
            if message["id"] == id {
                if let Some(error) = message.get("error") {
                    return Err(error["message"]
                        .as_str()
                        .unwrap_or("Core refused the update")
                        .to_owned());
                }
                return message
                    .get("result")
                    .cloned()
                    .ok_or_else(|| "Invalid core update reply".into());
            }
        }
    })
    .await
    .map_err(|_| "Core did not acknowledge the update operation".to_owned())?
}

pub async fn run<T>(
    port: u16,
    token: &str,
    cancellation: &Cancellation,
    generation: u64,
    operation: impl Future<Output = Result<T, String>>,
) -> Result<T, String> {
    // Same actor-bound derivation as server/auth.py; this connection cannot keep
    // the renderer alive and its credential grants only the update lease methods.
    let mut mac = Hmac::<Sha256>::new_from_slice(token.as_bytes()).map_err(|e| e.to_string())?;
    mac.update(b"badshop.actor.v1:updater");
    let updater_token: String = mac
        .finalize()
        .into_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let mut socket = timeout(RPC_TIMEOUT, async {
        let (mut socket, _) = connect_async(format!("ws://127.0.0.1:{port}"))
            .await
            .map_err(|e| e.to_string())?;
        socket
            .send(Message::Text(
                json!({"type":"hello", "actor":"updater", "token":updater_token})
                    .to_string()
                    .into(),
            ))
            .await
            .map_err(|e| e.to_string())?;
        if receive(&mut socket).await?["type"] != "welcome" {
            return Err("Core refused update connection".to_owned());
        }
        Ok(socket)
    })
    .await
    .map_err(|_| "Core connection timed out".to_owned())??;
    let mut stopped = false;
    let reply = rpc(&mut socket, 1, "updates.begin", json!({}), &mut stopped).await?;
    let lease = reply["lease"]
        .as_str()
        .ok_or("Invalid update lease")?
        .to_owned();
    // The owned future is dropped within this block BEFORE acknowledging updates.end.
    // Pinning an outer borrowed future would leave its HTTP request alive until return.
    let result = {
        let operation = operation;
        tokio::pin!(operation);
        if stopped || cancellation.generation() != generation {
            Err(CANCELLED.into())
        } else {
            tokio::select! {
                biased;
                _ = cancellation.cancelled(generation) => Err(CANCELLED.into()),
                error = async {
                    loop {
                        match receive(&mut socket).await {
                            Ok(message) if message["method"] == "updates.cancel" => break CANCELLED.to_owned(),
                            Ok(_) => {},
                            Err(error) => break error,
                        }
                    }
                } => Err(error),
                result = &mut operation => result,
            }
        }
    };
    let ended = rpc(
        &mut socket,
        2,
        "updates.end",
        json!({"lease":lease}),
        &mut stopped,
    )
    .await;
    // Failure to release is visible and leaves the core fail-closed on a policy transition.
    ended?;
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{atomic::AtomicBool, Arc};
    use tokio::{net::TcpListener, sync::oneshot};
    use tokio_tungstenite::accept_async;

    struct ActiveRequest(Arc<AtomicBool>);
    impl Drop for ActiveRequest {
        fn drop(&mut self) {
            self.0.store(false, Ordering::SeqCst);
        }
    }

    // Real loopback websocket exercises wire framing, event/reply ordering and
    // the important lifetime: drop the HTTP future BEFORE the release RPC.
    async fn cancellation_case(mode: &str) {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let port = listener.local_addr().unwrap().port();
        let active = Arc::new(AtomicBool::new(false));
        let active_server = active.clone();
        let cancellation = Arc::new(Cancellation::default());
        let signal = cancellation.clone();
        let (started, running) = oneshot::channel();
        let mode = mode.to_owned();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut socket = accept_async(stream).await.unwrap();
            let hello: Value =
                serde_json::from_str(socket.next().await.unwrap().unwrap().to_text().unwrap())
                    .unwrap();
            assert_eq!(hello["actor"], "updater");
            // Independently calculated with Python's standard hmac module.
            assert_eq!(
                hello["token"],
                "dd9c4940ed2168bbb90eb7762ad6bcfe1a05287ec9f6a3fc4d4b62a398098738"
            );
            socket
                .send(Message::Text(json!({"type":"welcome"}).to_string().into()))
                .await
                .unwrap();
            let begin: Value =
                serde_json::from_str(socket.next().await.unwrap().unwrap().to_text().unwrap())
                    .unwrap();
            assert_eq!(begin["method"], "updates.begin");
            if mode == "denied" {
                socket
                    .send(Message::Text(
                        json!({"id":1,"error":{"message":"Local only"}})
                            .to_string()
                            .into(),
                    ))
                    .await
                    .unwrap();
                return;
            }
            if mode == "before_reply" {
                socket
                    .send(Message::Text(
                        json!({"method":"updates.cancel"}).to_string().into(),
                    ))
                    .await
                    .unwrap();
            }
            socket
                .send(Message::Text(
                    json!({"id":1,"result":{"lease":"owned-lease"}})
                        .to_string()
                        .into(),
                ))
                .await
                .unwrap();
            if mode != "before_reply" {
                running.await.unwrap();
                assert!(active_server.load(Ordering::SeqCst));
                match mode.as_str() {
                    "local" => signal.cancel(),
                    "disconnect" => {
                        socket.close(None).await.unwrap();
                        return;
                    }
                    _ => socket
                        .send(Message::Text(
                            json!({"method":"updates.cancel"}).to_string().into(),
                        ))
                        .await
                        .unwrap(),
                }
            }
            let end: Value =
                serde_json::from_str(socket.next().await.unwrap().unwrap().to_text().unwrap())
                    .unwrap();
            assert_eq!(end["method"], "updates.end");
            assert_eq!(end["params"]["lease"], "owned-lease");
            assert!(
                !active_server.load(Ordering::SeqCst),
                "HTTP future survived its lease"
            );
            socket
                .send(Message::Text(
                    json!({"id":2,"result":{"ended":true}}).to_string().into(),
                ))
                .await
                .unwrap();
        });
        let result: Result<(), String> = timeout(
            Duration::from_secs(3),
            run(
                port,
                "owned",
                &cancellation,
                cancellation.generation(),
                async {
                    active.store(true, Ordering::SeqCst);
                    let _request = ActiveRequest(active.clone());
                    started.send(()).unwrap();
                    std::future::pending().await
                },
            ),
        )
        .await
        .unwrap();
        assert!(result.is_err());
        assert!(!active.load(Ordering::SeqCst));
        server.await.unwrap();
    }

    #[tokio::test]
    async fn core_policy_cancels_before_release() {
        cancellation_case("core").await;
    }
    #[tokio::test]
    async fn local_cancel_drops_before_release() {
        cancellation_case("local").await;
    }
    #[tokio::test]
    async fn denied_policy_never_polls_http() {
        cancellation_case("denied").await;
    }
    #[tokio::test]
    async fn cancellation_before_begin_reply_is_not_lost() {
        cancellation_case("before_reply").await;
    }
    #[tokio::test]
    async fn lost_core_fails_closed() {
        cancellation_case("disconnect").await;
    }
}
