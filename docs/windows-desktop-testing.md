# Kuractus Windows Desktop testing

## Policy

Windows Desktop verification must not take control of a developer's primary
desktop. Tests must not focus, move, resize, or close the Kuractus window, click the
tray, send notifications, or kill processes. They must not stop Docker, change
ports, modify credentials, or reset Kuractus data on a daily-use machine.

Use existing tests and isolated CI first. Use the read-only PowerShell snapshot
script for a local installed-runtime health report. Tests that need tray,
notification, window, drag-and-drop, first-launch, restore, or uninstall UI must
run in a disposable Windows VM or be reported as `BLOCKED`. Do not add a new UI
automation dependency unless a dedicated isolated runner is available.

## Test tiers

1. **Pull request CI:** use the exact-head `Windows Desktop` GitHub Actions run
   and the regular `CI` run. These are asynchronous and execute away from the
   developer's desktop. Existing Vitest, pytest, Rust, frozen-sidecar, and
   packaging checks remain the default.
2. **Read-only installed-runtime snapshot:** run
   `desktop/scripts/Get-KuractusDesktopSnapshot.ps1`. It checks the installed
   executable/version, running process IDs, `/ready`, the exact Kuractus Postgres
   container, listeners on ports 17890/15432, an optional artifact hash, and an
   optional backup archive structure (manifest, required members, and member
   names). It never launches or stops an application or
   container, opens a window, accesses credentials, or reads backup contents
   beyond `manifest.json` and archive member names. It writes JSON and text logs
   under `%TEMP%\kuractus-desktop-dogfood`.
3. **Isolated Windows VM:** use only for behavior that needs the actual shell or
   Windows UI. Provide a disposable profile, temporary workspace, and a Docker
   context containing only Kuractus's test services. Keep this tier deferred when
   no VM is available.

Do not infer a UI result from a build, a unit test, an API health response, or a
read-only host snapshot. Do not infer a runtime result from a static code test.

## Commands

Read-only snapshot for the installed app:

```powershell
./desktop/scripts/Get-KuractusDesktopSnapshot.ps1
```

Verify a downloaded CI artifact and a known safety backup without installing,
restoring, or extracting either archive:

```powershell
./desktop/scripts/Get-KuractusDesktopSnapshot.ps1 `
  -ArtifactZip .\kuractus-desktop-windows.zip `
  -ExpectedArtifactSha256 <sha256-from-github> `
  -BackupPath "$env:TEMP\aura-safety-backup.aurabackup"
```

Use the following existing CI commands only in CI or a disposable checkout.
Long test jobs should run in GitHub Actions or another background process with
stdout/stderr saved as artifacts; do not run a foreground GUI test on a primary
desktop.

```powershell
npm test --prefix web -- --reporter=dot --maxWorkers=2
python -m pytest -q tests/api/test_desktop_runtime.py tests/desktop
cargo test --manifest-path desktop/src-tauri/Cargo.toml
```

## D1–D7 evidence matrix

The matrix separates a complete dogfood scenario from the automated evidence
that covers parts of it. Status applies to the complete D item. This is a
point-in-time report: the read-only host snapshot was captured on 2026-11-25 at
09:16 ICT. Its JSON and text logs are local evidence and are not committed.

| Item | Status | Test method | Evidence | Logs | Remaining blocker |
| --- | --- | --- | --- | --- | --- |
| D1 Install and ready runtime | **FAIL** | Exact-head CI, installer checksum, read-only PowerShell process/API/container snapshot | Windows CI passed for `be720547fb309b442e6ed68b3b1702587a24ef37`; installer hash matched its artifact. The latest snapshot found no Kuractus process, no listener on 17890/15432, `/ready` refused the connection, and the Kuractus Postgres container was stopped. | `%TEMP%\aura-desktop-dogfood\snapshot-*.log` and `.json` | Runtime was not running at snapshot time. Start/repair must be done in an isolated test environment before re-evaluating D1. |
| D2 Tray, quit, relaunch, persistence | **BLOCKED** | Automated process-state observation only; no tray or window control | User reported close-to-tray and reopen kept the runtime Ready. Normal quit, relaunch, and persisted-object check were not confirmed in an isolated run. | Previous CI artifacts do not prove tray behavior. | Requires a disposable Windows VM/session. |
| D3 Folder and selected-file flow | **BLOCKED** | Vitest folder/index/file-preview tests, Rust path-validation tests in CI | Unit coverage exists for metadata-only indexing, explicit file opening, and path validation. It does not verify selecting text and sending it to a project from the installed UI. | Windows Desktop run linked below; local snapshot logs if supplied | Requires a disposable folder and isolated UI session for the complete flow. |
| D4 Notifications | **BLOCKED** | Frontend unit tests; no real toast test on the primary desktop | The app's notification handling is opt-in and generic; CI does not demonstrate Windows toast delivery for approval/success/failure events. | No native notification log was produced. | Requires an isolated Windows session with notifications enabled. |
| D5 Failure recovery | **NOT TESTED** | Read-only health/container snapshot only | Current snapshot showed the runtime stopped; no API/DB port conflict or Docker/API outage was injected. | Snapshot log and JSON | Fault injection must use a VM or disposable network/container namespace. |
| D6 Backup and restore | **BLOCKED** | Backup archive structure check plus CI archive tests | The safety backup's manifest format, required database dump, and member names passed a read-only structure check (3 members; no credential/config member names). This does not verify every archive payload or prove restore. No restore or uninstall was run against the live profile. | Backup: `%TEMP%\aura-safety-before-update-127a5dd.aurabackup`; use paths printed by the latest snapshot run for local logs | Restore/uninstall persistence requires a disposable profile and volume. |
| D7 Security boundaries | **BLOCKED** | CSP test, Rust path-validation tests, source inspection, read-only listener snapshot | CI passed CSP and native path-validation tests. The current runtime had no listeners, so live loopback binding could not be verified; Credential Manager and drag/drop behavior need isolated runtime evidence. | Windows Desktop run linked below; snapshot log and JSON | Complete live verification requires the isolated runtime. |

## Baseline CI evidence before this workflow change

The passing run below is for the branch's previous head, before the new
snapshot-script parser step. It provides baseline package and test evidence;
the new workflow revision must pass CI on its own exact head before it is
reported as verified.

- Commit: `be720547fb309b442e6ed68b3b1702587a24ef37`
- Main CI: [run 45166155565](https://github.com/nhatminh-115/Kuractus/actions/runs/45166155565) — passed.
- Windows Desktop: [run 45166155568](https://github.com/nhatminh-115/Kuractus/actions/runs/45166155568) — passed; artifact ID `14815162371`.
- Artifact ZIP SHA-256: `4e656f870d6fd7885976b4cdfeda88193f86560b963543677a1ac0f6f517a090`.
- NSIS installer SHA-256: `23c1f100799437f67344edd1811e8e5030772e3cf14bea101dc87bb91cf42adf`.

CI proves code tests and packaging on the exact commit. It does not change the
D1–D7 statuses above because it does not test the installed application in a
disposable Windows profile.
