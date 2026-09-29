# Shared credentials

Settings → Credentials lists company credentials, usernames and masked key previews. Ana (ana@acme.example) and Ben (ben@acme.example) administer the vault. Each credential has its own grants. A granted person may reveal/copy it or attach it to bots they manage; a direct bot grant works on its assigned machine during an active run. Revoking the parent grant removes delegated bot access. Changing a bot operator invalidates delegation from its former operator.

Secrets use AES-256-GCM with per-write random nonces and credential-bound authenticated data. The data key is wrapped by the dedicated rotating AWS KMS key. SQLite and backups contain ciphertext, not the plaintext data key. Reveal operations are audited; secret values are excluded from audit and idempotency receipts. Restoring a snapshot revokes restored grants to avoid resurrecting permissions.

The bot key name becomes an environment variable only for a granted bot. File credentials become mode-0600 temporary files during the run. Machine login entries describe existing CLI/browser sessions and must be connected separately on each machine. Existing runner-local credentials continue to work during migration; moving a credential to this list does not erase local copies or implicitly grant it to every bot.

The initial migration inventories the existing bot secrets directory and resolves its configured 1Password references. Values are encrypted locally before upload. It adds no grants, preserves existing local files, and imports machine-login metadata without exporting browser sessions. All raw migration evidence remains outside Git.
