//! Owns the core process. Closing stdin is its cross-platform graceful shutdown protocol.
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, OpenOptions},
    io::{BufRead, BufReader, Read},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{mpsc, Arc, Condvar, Mutex},
    thread,
    time::{Duration, Instant},
};

#[derive(Clone)]
pub struct Launch {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub log_path: PathBuf,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Connection {
    pub port: u16,
    pub token: String,
    #[serde(default)]
    pub log_path: String,
}
#[derive(Clone, Serialize)]
pub struct Status {
    pub state: String,
    pub attempt: usize,
    pub log_path: String,
    pub port: Option<u16>,
    pub token: Option<String>,
    pub error: Option<String>,
}
#[derive(Default)]
struct Snapshot {
    connection: Option<Connection>,
    error: Option<String>,
    stopped: bool,
}
enum Control {
    Stop,
    Restart,
}
pub struct Supervisor {
    snapshot: Arc<(Mutex<Snapshot>, Condvar)>,
    control: mpsc::Sender<Control>,
    thread: Mutex<Option<thread::JoinHandle<()>>>,
}

pub fn parse_handshake(line: &str, log_path: &std::path::Path) -> Result<Connection, String> {
    let mut c: Connection =
        serde_json::from_str(line).map_err(|_| "The core sent an invalid startup response")?;
    if c.port == 0 || c.token.len() < 16 || c.token.len() > 1024 {
        return Err("The core sent invalid connection details".into());
    }
    c.log_path = log_path.to_string_lossy().into();
    Ok(c)
}

fn terminate(child: &mut Child) {
    drop(child.stdin.take());
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if matches!(child.try_wait(), Ok(Some(_))) {
            return;
        }
        thread::sleep(Duration::from_millis(50));
    }
    let _ = child.kill();
    let _ = child.wait();
}

impl Supervisor {
    pub fn start(launch: Launch, emit: impl Fn(Status) + Send + 'static) -> Self {
        let snapshot = Arc::new((Mutex::new(Snapshot::default()), Condvar::new()));
        let shared = snapshot.clone();
        let (tx, rx) = mpsc::channel();
        let handle = thread::spawn(move || {
            let mut attempt = 0;
            let publish = |state: &str,
                           attempt: usize,
                           connection: Option<Connection>,
                           error: Option<String>| {
                let (lock, changed) = &*shared;
                let mut data = lock.lock().unwrap();
                data.connection = connection.clone();
                data.error = error.clone();
                data.stopped = state == "stopped";
                changed.notify_all();
                drop(data);
                emit(Status {
                    state: state.into(),
                    attempt,
                    log_path: launch.log_path.to_string_lossy().into(),
                    port: connection.as_ref().map(|c| c.port),
                    token: connection.map(|c| c.token),
                    error,
                });
            };
            loop {
                publish("starting", attempt, None, None);
                let launched =
                    (|| -> Result<(Child, mpsc::Receiver<Result<String, String>>), String> {
                        if let Some(parent) = launch.log_path.parent() {
                            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
                        }
                        if launch
                            .log_path
                            .metadata()
                            .map(|m| m.len() > 2 * 1024 * 1024)
                            .unwrap_or(false)
                        {
                            let _ = fs::rename(
                                &launch.log_path,
                                launch.log_path.with_extension("previous.log"),
                            );
                        }
                        let log = OpenOptions::new()
                            .create(true)
                            .append(true)
                            .open(&launch.log_path)
                            .map_err(|e| e.to_string())?;
                        let mut cmd = Command::new(&launch.program);
                        cmd.args(&launch.args)
                            .stdin(Stdio::piped())
                            .stdout(Stdio::piped())
                            .stderr(log);
                        #[cfg(windows)]
                        {
                            use std::os::windows::process::CommandExt;
                            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
                        }
                        let mut child =
                            cmd.spawn().map_err(|e| format!("Can't start core: {e}"))?;
                        let stdout = child.stdout.take().unwrap();
                        let (ready_tx, ready_rx) = mpsc::channel();
                        thread::spawn(move || {
                            let mut reader = BufReader::new(stdout);
                            let mut line = String::new();
                            let result = reader
                                .by_ref()
                                .take(65536)
                                .read_line(&mut line)
                                .map_err(|e| e.to_string())
                                .map(|_| line);
                            let _ = ready_tx.send(result);
                            // Keep draining if a dependency prints after startup, so its pipe cannot fill.
                            let _ = std::io::copy(&mut reader, &mut std::io::sink());
                        });
                        Ok((child, ready_rx))
                    })();
                let mut restart = false;
                let mut failure = None;
                match launched {
                    Err(e) => failure = Some(e),
                    Ok((mut child, ready)) => {
                        let deadline = Instant::now() + Duration::from_secs(30);
                        let mut connected = false;
                        loop {
                            match rx.try_recv() {
                                Ok(Control::Stop) | Err(mpsc::TryRecvError::Disconnected) => {
                                    terminate(&mut child);
                                    publish("stopped", attempt, None, None);
                                    return;
                                }
                                Ok(Control::Restart) => {
                                    restart = true;
                                    break;
                                }
                                Err(mpsc::TryRecvError::Empty) => {}
                            }
                            if !connected {
                                match ready.try_recv() {
                                    Ok(Ok(line)) => {
                                        match parse_handshake(&line, &launch.log_path) {
                                            Ok(c) => {
                                                publish("ready", attempt, Some(c), None);
                                                connected = true;
                                            }
                                            Err(e) => {
                                                failure = Some(e);
                                                break;
                                            }
                                        }
                                    }
                                    Ok(Err(e)) => {
                                        failure = Some(e);
                                        break;
                                    }
                                    Err(mpsc::TryRecvError::Disconnected) => {
                                        failure = Some("The core closed during startup".into());
                                        break;
                                    }
                                    Err(mpsc::TryRecvError::Empty)
                                        if Instant::now() >= deadline =>
                                    {
                                        failure =
                                            Some("The core did not start within 30 seconds".into());
                                        break;
                                    }
                                    _ => {}
                                }
                            }
                            match child.try_wait() {
                                Ok(Some(status)) => {
                                    failure = Some(format!("The core exited ({status})"));
                                    break;
                                }
                                Err(e) => {
                                    failure = Some(format!("Can't check core status: {e}"));
                                    break;
                                }
                                _ => {}
                            }
                            thread::sleep(Duration::from_millis(50));
                        }
                        terminate(&mut child);
                    }
                }
                if restart {
                    attempt = 0;
                    continue;
                }
                if attempt < 3 {
                    attempt += 1;
                    continue;
                }
                publish("failed", attempt, None, failure);
                match rx.recv() {
                    Ok(Control::Restart) => {
                        attempt = 0;
                    }
                    _ => {
                        publish("stopped", attempt, None, None);
                        return;
                    }
                }
            }
        });
        Self {
            snapshot,
            control: tx,
            thread: Mutex::new(Some(handle)),
        }
    }

    pub fn connection(&self) -> Result<Connection, String> {
        let (lock, changed) = &*self.snapshot;
        let (data, timeout) = changed
            .wait_timeout_while(lock.lock().unwrap(), Duration::from_secs(35), |s| {
                s.connection.is_none() && s.error.is_none() && !s.stopped
            })
            .unwrap();
        if let Some(c) = &data.connection {
            return Ok(c.clone());
        }
        if timeout.timed_out() {
            return Err("The core is still starting; check the log or retry".into());
        }
        Err(data
            .error
            .clone()
            .unwrap_or_else(|| "The core has stopped".into()))
    }
    pub fn restart(&self) -> Result<(), String> {
        {
            let mut s = self.snapshot.0.lock().unwrap();
            s.connection = None;
            s.error = None;
        }
        self.control
            .send(Control::Restart)
            .map_err(|_| "The core supervisor has stopped".into())
    }
    pub fn stop(&self) {
        let _ = self.control.send(Control::Stop);
        if let Some(handle) = self.thread.lock().unwrap().take() {
            let _ = handle.join();
        }
    }
}
impl Drop for Supervisor {
    fn drop(&mut self) {
        self.stop();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn handshake_rejects_invalid_and_attaches_log() {
        let path = PathBuf::from("log.txt");
        for line in [
            "bad",
            r#"{"port":0,"token":"abcdefghijklmnop"}"#,
            r#"{"port":1234,"token":"x"}"#,
        ] {
            assert!(parse_handshake(line, &path).is_err());
        }
        let c = parse_handshake(r#"{"port":1234,"token":"abcdefghijklmnop"}"#, &path).unwrap();
        assert_eq!(c.port, 1234);
        assert_eq!(c.log_path, "log.txt");
    }
    #[test]
    fn missing_binary_stops_after_three_restarts_and_can_close() {
        let dir = tempfile::tempdir().unwrap();
        let (tx, rx) = mpsc::channel();
        let supervisor = Supervisor::start(
            Launch {
                program: dir.path().join("missing"),
                args: vec![],
                log_path: dir.path().join("log"),
            },
            move |s| {
                tx.send(s).unwrap();
            },
        );
        let mut starts = 0;
        loop {
            let status = rx.recv_timeout(Duration::from_secs(5)).unwrap();
            if status.state == "starting" {
                starts += 1;
            }
            if status.state == "failed" {
                break;
            }
        }
        assert_eq!(starts, 4);
        assert!(supervisor.connection().is_err());
        supervisor.stop();
    }
    #[cfg(unix)]
    #[test]
    fn stops_a_live_child_by_closing_stdin() {
        let dir = tempfile::tempdir().unwrap();
        let supervisor = Supervisor::start(
            Launch {
                program: "/bin/sh".into(),
                args: vec![
                    "-c".into(),
                    "echo '{\"port\":1234,\"token\":\"abcdefghijklmnop\"}'; cat >/dev/null".into(),
                ],
                log_path: dir.path().join("log"),
            },
            |_| {},
        );
        assert_eq!(supervisor.connection().unwrap().port, 1234);
        let start = Instant::now();
        supervisor.stop();
        assert!(start.elapsed() < Duration::from_secs(2));
    }
}
