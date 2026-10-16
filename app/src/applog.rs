//! The shell's own log file. An app opened from Finder or the Dock has no terminal, so stderr goes nowhere; every
//! line also goes to `tico.log` in the app's log folder (~/Library/Logs/<bundle id>/ on macOS), which Help opens and
//! Support diagnostics attach the end of. At MAX_BYTES the file moves to `tico.log.1`, so two files at most are kept.
//! This crate logs at info and above, other crates at warn and above; `RUST_LOG=<level>` sets one level for all.
use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

pub const FILE_NAME: &str = "tico.log";
const MAX_BYTES: u64 = 1024 * 1024;
// What `tail` reads from the end of each file: enough for its lines, never the whole file.
const TAIL_BYTES: u64 = 64 * 1024;

struct FileLog {
    path: Option<PathBuf>,
    file: Mutex<Option<File>>,
    level: Option<log::LevelFilter>,
    max: u64,
}

fn open(path: &Path) -> std::io::Result<File> {
    OpenOptions::new().create(true).append(true).open(path)
}

fn rotated(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_owned();
    name.push(".1");
    PathBuf::from(name)
}

impl FileLog {
    fn new(dir: Option<&Path>, level: Option<log::LevelFilter>, max: u64) -> Self {
        let path = dir.and_then(|dir| std::fs::create_dir_all(dir).ok().map(|_| dir.join(FILE_NAME)));
        let file = path.as_deref().and_then(|p| open(p).ok());
        FileLog { path: file.as_ref().and(path), file: Mutex::new(file), level, max }
    }

    fn write_line(&self, line: &str) {
        let Some(path) = &self.path else { return };
        let mut file = self.file.lock().unwrap_or_else(|e| e.into_inner());
        let full = file.as_ref().and_then(|f| f.metadata().ok()).map(|m| m.len() + line.len() as u64 > self.max);
        if full.unwrap_or(false) {
            // Closed before the rename, which Windows refuses on an open file.
            *file = None;
            let _ = std::fs::rename(path, rotated(path));
            *file = open(path).ok();
        }
        if let Some(f) = file.as_mut() {
            let _ = f.write_all(line.as_bytes());
        }
    }
}

impl log::Log for FileLog {
    fn enabled(&self, metadata: &log::Metadata) -> bool {
        let level = self.level.unwrap_or(if metadata.target().starts_with(env!("CARGO_CRATE_NAME")) {
            log::LevelFilter::Info
        } else {
            log::LevelFilter::Warn
        });
        metadata.level() <= level
    }

    fn log(&self, record: &log::Record) {
        if !self.enabled(record.metadata()) {
            return;
        }
        let line = format!("{} {} {}: {}\n", timestamp(SystemTime::now()), record.level(), record.target(), record.args());
        eprint!("{line}");
        self.write_line(&line);
    }

    fn flush(&self) {
        if let Some(f) = self.file.lock().unwrap_or_else(|e| e.into_inner()).as_mut() {
            let _ = f.flush();
        }
    }
}

/// Logs to stderr and, when `dir` can be written, to its log file. Returns the file's path, or None for stderr alone.
pub fn init(dir: Option<&Path>) -> Option<PathBuf> {
    let level = std::env::var("RUST_LOG").ok().and_then(|v| v.parse().ok());
    let logger = FileLog::new(dir, level, MAX_BYTES);
    let path = logger.path.clone();
    log::set_max_level(level.unwrap_or(log::LevelFilter::Info));
    log::set_boxed_logger(Box::new(logger)).ok()?;
    path
}

/// `path` with the home folder as `~`, so the log (and diagnostics made from it) does not name the person's account.
pub fn shown(path: &Path) -> String {
    let home = std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(PathBuf::from);
    match home.as_deref().and_then(|home| path.strip_prefix(home).ok()) {
        Some(rest) => Path::new("~").join(rest).display().to_string(),
        None => path.display().to_string(),
    }
}

/// The last `keep` lines of the log, the rotated file's end first when the current one is short.
pub fn tail(path: &Path, keep: usize) -> Vec<String> {
    let mut lines = Vec::new();
    for file in [rotated(path), path.to_path_buf()] {
        lines.extend(tail_of(&file));
    }
    let skip = lines.len().saturating_sub(keep);
    lines.split_off(skip)
}

fn tail_of(path: &Path) -> Vec<String> {
    let Ok(mut file) = File::open(path) else { return Vec::new() };
    let len = file.metadata().map(|m| m.len()).unwrap_or(0);
    let start = len.saturating_sub(TAIL_BYTES);
    let mut bytes = Vec::new();
    if file.seek(SeekFrom::Start(start)).is_err() || file.read_to_end(&mut bytes).is_err() {
        return Vec::new();
    }
    let text = String::from_utf8_lossy(&bytes);
    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
    // A read that starts mid-file starts mid-line.
    if start > 0 && !lines.is_empty() {
        lines.remove(0);
    }
    lines
}

/// `2026-10-16T06:47:31Z`, UTC, without a date library.
fn timestamp(now: SystemTime) -> String {
    let secs = now.duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
    let (days, rest) = (secs / 86400, secs % 86400);
    // Civil date from days since 1970-01-01 (Howard Hinnant's days_from_civil, inverted).
    let z = days as i64 + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + if month <= 2 { 1 } else { 0 };
    format!("{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z", rest / 3600, rest % 3600 / 60, rest % 60)
}

#[cfg(test)]
mod tests {
    use super::*;
    use log::Log;
    use std::time::Duration;

    fn scratch(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("tico-applog-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        dir
    }

    fn line(logger: &FileLog, text: &str) {
        logger.log(&log::Record::builder().level(log::Level::Info).target(env!("CARGO_CRATE_NAME"))
            .args(format_args!("{text}")).build());
    }

    #[test]
    fn the_log_rotates_to_one_old_file_and_tail_reads_across_both() {
        let dir = scratch("rotate");
        let logger = FileLog::new(Some(&dir), None, 200);
        for n in 0..12 {
            line(&logger, &format!("update check {n}: current"));
        }
        let path = dir.join(FILE_NAME);
        assert!(std::fs::metadata(&path).unwrap().len() <= 200);
        assert!(rotated(&path).exists());
        assert!(!dir.join("tico.log.1.1").exists());
        let lines = tail(&path, 3);
        assert_eq!(lines.len(), 3);
        assert!(lines[2].ends_with("update check 11: current"), "{lines:?}");
        assert!(lines[0].ends_with("update check 9: current"), "{lines:?}");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn other_crates_log_warnings_only_and_an_unwritable_folder_keeps_stderr() {
        let logger = FileLog::new(None, None, MAX_BYTES);
        assert!(logger.path.is_none());
        let info = |target| log::Metadata::builder().level(log::Level::Info).target(target).build();
        assert!(logger.enabled(&info(env!("CARGO_CRATE_NAME"))));
        assert!(!logger.enabled(&info("hyper::client")));
        line(&logger, "no file, no panic");
    }

    #[test]
    fn timestamps_are_utc_dates() {
        assert_eq!(timestamp(UNIX_EPOCH), "1970-01-01T00:00:00Z");
        assert_eq!(timestamp(UNIX_EPOCH + Duration::from_secs(1_792_133_251)), "2026-10-16T06:47:31Z");
        assert_eq!(timestamp(UNIX_EPOCH + Duration::from_secs(951_782_400)), "2000-02-29T00:00:00Z");
    }
}
