//! Per-checkout groups on the Docker runner. Every bot's files are group-shared with its turn users (the pool's
//! group), so the group alone would let one leased turn into every bot's checkout. Each checkout and worktree root
//! instead gets a group of its own (owner `bot`, mode 0770), and a leased turn user is given only the groups of the
//! paths its turn runs in (crate::isolation::prefix_for). Below a root nothing changes: the pool's group still lets
//! that turn write the bot's files once it is inside.
//!
//! Not covered (SECURITY.md): turns on harnesses without `isolated_user` run as `bot`, the owner of every checkout,
//! as do watchers, worktree setup commands and the runner's own git; shared base clones (`repos/<base>`) stay open to
//! the pool's group, since every computer task worktree of that base needs them.
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::os::fd::AsRawFd;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

use crate::isolation::{open_at, pinned_parent};

/// Group ids above the image's users and pool, below the 65534 `nogroup`.
const FIRST: u32 = 20000;
const LAST: u32 = 59999;
const FILE: &str = "turn-groups.json";

struct Groups {
    file: Option<PathBuf>,
    /// Checkout root path to its group. Kept across restarts so a root keeps its group and no two roots share one.
    by_path: BTreeMap<String, u32>,
}

static GROUPS: OnceLock<Mutex<Groups>> = OnceLock::new();
/// A leased turn user's checkout groups, read whenever a command is started as that user.
static GRANTS: OnceLock<Mutex<HashMap<u32, BTreeSet<u32>>>> = OnceLock::new();

fn groups() -> &'static Mutex<Groups> {
    GROUPS.get_or_init(|| Mutex::new(Groups { file: None, by_path: BTreeMap::new() }))
}

fn grants() -> &'static Mutex<HashMap<u32, BTreeSet<u32>>> {
    GRANTS.get_or_init(Default::default)
}

/// Load the group map from the supervisor's state directory (closed to bot code).
pub fn initialize(state_dir: &Path) {
    let file = state_dir.join(FILE);
    let by_path = std::fs::read_to_string(&file).ok()
        .and_then(|text| serde_json::from_str::<BTreeMap<String, u32>>(&text).ok())
        .unwrap_or_default()
        .into_iter().filter(|(_, g)| (FIRST..=LAST).contains(g)).collect();
    let mut g = groups().lock().unwrap();
    g.file = Some(file);
    g.by_path = by_path;
}

/// Whether roots are gated here: only where turns can run as leased users.
fn wanted() -> bool {
    crate::isolation::enabled() && crate::turn_users::available()
}

/// The supplementary groups `uid` runs with (none for `bot` or any user without a grant).
pub fn granted(uid: u32) -> Vec<u32> {
    grants().lock().unwrap().get(&uid).map(|s| s.iter().copied().collect()).unwrap_or_default()
}

/// Let a leased turn user into these checkout roots, for its commands from now on.
pub fn grant(uid: u32, gids: &[u32]) {
    if gids.is_empty() { return; }
    grants().lock().unwrap().entry(uid).or_default().extend(gids);
}

/// Before the UID can be lent to another turn.
pub fn revoke(uid: u32) {
    grants().lock().unwrap().remove(&uid);
}

/// Gate each path that is a bot-owned checkout or worktree root and return the groups now on those roots.
/// A path that is not one (a missing directory, the workspace itself, a supervisor-owned folder) is left alone.
pub async fn gate(paths: Vec<PathBuf>) -> Vec<u32> {
    if !wanted() { return vec![]; }
    tokio::task::spawn_blocking(move || gate_blocking(&paths)).await.unwrap_or_default()
}

pub fn gate_blocking(paths: &[PathBuf]) -> Vec<u32> {
    let Some((bot, _)) = crate::isolation::identity() else { return vec![] };
    let mut out = BTreeSet::new();
    for path in paths.iter().collect::<BTreeSet<_>>() {
        match gate_one(path, bot) {
            Ok(Some(gid)) => { out.insert(gid); }
            Ok(None) => {}
            Err(e) => crate::util::log(&format!("Tico runner: cannot give {} its own group: {e}", path.display())),
        }
    }
    out.into_iter().collect()
}

/// The workspace's checkouts (`<ws>/<name>`), task-lane worktrees (`<ws>/sessions/<bot>/<task>`) and computer
/// task worktrees (`<ws>/tasks/<name>`), so a checkout no turn has run in yet is closed to leased turns too.
pub fn gate_workspace(workspace: &Path) {
    if !wanted() { return; }
    let children = |dir: &Path| -> Vec<PathBuf> {
        std::fs::read_dir(dir).map(|r| r.flatten().map(|e| e.path()).collect()).unwrap_or_default()
    };
    let mut roots = children(workspace);
    for lane in children(&workspace.join("sessions")) { roots.extend(children(&lane)); }
    roots.extend(children(&workspace.join("tasks")));
    gate_blocking(&roots);
}

fn gate_one(path: &Path, bot: u32) -> std::io::Result<Option<u32>> {
    let Some((parent, name)) = pinned_parent(path) else { return Ok(None) };
    let Some(fd) = open_at(parent.as_raw_fd(), &name, libc::O_RDONLY | libc::O_DIRECTORY) else { return Ok(None) };
    let info = stat(fd.as_raw_fd())?;
    // A checkout or worktree root holds `.git` (a directory, or a file naming the main checkout's).
    let dot_git = std::ffi::CString::new(".git").unwrap();
    let mut probe = std::mem::MaybeUninit::<libc::stat>::uninit();
    // SAFETY: fstatat on a descriptor this process owns, without following a link.
    let checkout = unsafe { libc::fstatat(fd.as_raw_fd(), dot_git.as_ptr(), probe.as_mut_ptr(), libc::AT_SYMLINK_NOFOLLOW) } == 0;
    // SAFETY: geteuid has no preconditions.
    let me = unsafe { libc::geteuid() };
    // A root this runner was gating when it stopped is still the supervisor's, with a checkout group: finish it.
    let interrupted = info.st_uid == me && (FIRST..=LAST).contains(&info.st_gid);
    if !(info.st_uid == bot || interrupted) || !checkout { return Ok(None); }
    let key = path.display().to_string();
    let gid = {
        let mut g = groups().lock().unwrap();
        match g.by_path.get(&key) {
            Some(gid) => *gid,
            None => {
                let used: BTreeSet<u32> = g.by_path.values().copied().collect();
                // A root gated before the map was lost keeps its group if no other root holds it.
                let gid = if (FIRST..=LAST).contains(&info.st_gid) && !used.contains(&info.st_gid) {
                    info.st_gid
                } else {
                    (FIRST..=LAST).find(|c| !used.contains(c) && !system_group(*c))
                        .ok_or_else(|| std::io::Error::other("no free checkout group"))?
                };
                g.by_path.insert(key, gid);
                save(&g)?;
                gid
            }
        }
    };
    let mode = u32::from(info.st_mode) & 0o7777;
    let wanted_mode = (mode & 0o7000) | 0o770;
    let fd = fd.as_raw_fd();
    // SAFETY: fchown and fchmod on the pinned descriptor. The supervisor may change any owner (CAP_CHOWN) but only
    // its own inode's mode (no CAP_FOWNER), so a mode change borrows ownership for that one call.
    unsafe {
        if mode != wanted_mode || interrupted {
            if libc::fchown(fd, me, gid) != 0 { return Err(std::io::Error::last_os_error()); }
            let changed = libc::fchmod(fd, wanted_mode as libc::mode_t);
            let error = std::io::Error::last_os_error();
            if libc::fchown(fd, bot, gid) != 0 { return Err(std::io::Error::last_os_error()); }
            if changed != 0 { return Err(error); }
        } else if info.st_gid != gid && libc::fchown(fd, bot, gid) != 0 {
            return Err(std::io::Error::last_os_error());
        }
    }
    Ok(Some(gid))
}

fn stat(fd: i32) -> std::io::Result<libc::stat> {
    let mut raw = std::mem::MaybeUninit::<libc::stat>::uninit();
    // SAFETY: fstat on a descriptor this process owns.
    if unsafe { libc::fstat(fd, raw.as_mut_ptr()) } != 0 { return Err(std::io::Error::last_os_error()); }
    Ok(unsafe { raw.assume_init() })
}

/// A group the image already names (its members would get into the checkout).
fn system_group(gid: u32) -> bool {
    // SAFETY: getgrgid reads the group database; only the null check is used.
    !unsafe { libc::getgrgid(gid) }.is_null()
}

fn save(g: &Groups) -> std::io::Result<()> {
    let Some(file) = &g.file else { return Ok(()) };
    let temporary = file.with_extension("json.tmp");
    {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        let mut out = std::fs::OpenOptions::new().write(true).create(true).truncate(true).mode(0o600).open(&temporary)?;
        out.write_all(serde_json::to_string(&g.by_path).map_err(std::io::Error::other)?.as_bytes())?;
        out.sync_all()?;
    }
    std::fs::rename(&temporary, file)
}
