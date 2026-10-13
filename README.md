# Agent House-Moving

Move a Hermes agent off the machine you built it on and onto your own VPS or MiniPC — with
its identity, memory, skills and Telegram channel intact — then prove it survives on its own.

This is the **Session 5 capstone procedure**, packaged as a Hermes skill so your agent can
run it for you. The same steps are in [`SKILL.md`](SKILL.md), which is what an agent loads;
this README is the human-readable version.

## Install

```bash
hermes skills install andynguyendk/agent-house-moving/
```

Or drop this folder into `~/.hermes/skills/`. Then ask your agent: *"move yourself to my new
box"* — it will follow this procedure.

The `/key` plugin the procedure relies on ships alongside it, under [`plugins/keyenv/`](plugins/keyenv/) — see below.

## The `/key` plugin (shipped here)

The house-move hands secrets over with `/key`, which saves a value straight into
`~/.hermes/.env` without the value ever reaching the model. The plugin is included in this
repo, so you don't need to source it separately.

```bash
cp -r plugins/keyenv ~/.hermes/plugins/
hermes plugins enable keyenv
```

Then, in a **DM**:

```
/key NAME VALUE      # save NAME=VALUE into ~/.hermes/.env (not echoed, not logged)
/key list            # show saved names
/key rm NAME         # remove one
```

Use it in a DM only — anything typed in a group is visible to everyone in it. And note that
saving the value is only half the job: to let the agent's shell *read* it, the name must be
declared (this skill declares `NEWBOX_SSH_PASSWORD`; for other names use
`terminal.env_passthrough` in `config.yaml`).

## What moves (and what never does)

Ship what *defines* the agent — settings, skills, memory, schedules — as a package with
**no secret values in it**. Real secrets (provider keys, the Telegram token) are filled in on
the target, never carried in the bag.

## The procedure

Run the steps in order. The order is the safety.

### 0 · Prep — the new box is reachable
Put the new box on **Tailscale** (so both the old box and Hermes Desktop can reach it), or
confirm it is on the same LAN. Note its address and a sudo-capable user + password.

Check: `ssh -o ConnectTimeout=10 <user>@<newbox> hostname`

### 1 · Rotate the Telegram bot token — do this first
In Telegram, DM **@BotFather** → `/mybots` → your bot → **API Token** → **Revoke current
token**. BotFather issues a new token and kills the old one.

Rotating first is the whole trick: only one instance can poll a bot token, so killing the old
token means the old machine can never re-attach and the new box is the only possible poller.
Keep the new token out of chat — you hand it in at step 5.

Once rotated, the old gateway's Telegram calls fail with `401 Unauthorized`: it loses the
channel (though the old instance itself keeps running until you stop it in step 8).

### 2 · Hand the new box's SSH password to the agent — via `/key`, never in chat
```
/key NEWBOX_SSH_PASSWORD <the password>
```
`/key` writes it to `~/.hermes/.env` **without the value ever reaching the model**. Use a
**DM only** — anything typed in a group is visible to everyone in it.

**Declare it, or the shell can't read it.** Putting the name in `.env` is not the same as
forwarding it to the agent's commands — sandboxed children run with a scrubbed environment.
Add the name to `terminal.env_passthrough` in `config.yaml`, or list it under the skill's
`required_environment_variables` (this skill already does). Then `$NEWBOX_SSH_PASSWORD` is
available to `terminal` once the skill is loaded. Undeclared, it may still slip through on a
plain local backend, but `execute_code` blocks any name containing `PASSWORD` and a
remote/Docker/SSH backend forwards nothing it wasn't told to.

From here on, reference it as `$NEWBOX_SSH_PASSWORD`, never as the literal: the terminal tool
replaces a literal secret with `[REDACTED]` and the command silently breaks.

### 3 · Install the agent's key on the new box
```bash
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
sshpass -p "$NEWBOX_SSH_PASSWORD" ssh-copy-id -o StrictHostKeyChecking=accept-new <user>@<newbox>
```
If `sshpass`/`ssh-copy-id` is unavailable, push the public key by hand:
```bash
sshpass -p "$NEWBOX_SSH_PASSWORD" ssh -o StrictHostKeyChecking=accept-new <user>@<newbox> \
  "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" \
  < ~/.ssh/id_ed25519.pub
```
Optional (for hands-off automation): passwordless sudo. This one step the human runs,
interactively — non-interactive sudo needs a TTY:
```bash
ssh <user>@<newbox>
echo "<user> ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/<user>
```
Verify: `ssh <user>@<newbox> "sudo whoami"` → prints `root`, no prompt.

### 4 · Verify key auth, THEN turn off password login
```bash
ssh -o BatchMode=yes <user>@<newbox> "echo OK"     # MUST print OK — do not skip
ssh <user>@<newbox> "sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && sudo systemctl reload ssh"
```
Never disable password auth before the BatchMode test passes, or you lock yourself out. Then
drop the password so it is not sitting in `.env` when you pack: `/key rm NEWBOX_SSH_PASSWORD`

### 5 · Pack and move the agent
Gather what defines the agent — never the secrets:

| What | Where | Ship as |
|------|-------|---------|
| Settings | `~/.hermes/config.yaml` | the file |
| Secrets | `~/.hermes/.env` | `.env.example` (keys, **NO values**) |
| Skills | `~/.hermes/skills/` | the folders |
| Memory | persistent store | export, or rebuild on first use |
| Schedules | cron config | the list |

```bash
tar czf /tmp/agent-pack.tgz -C ~/.hermes config.yaml skills      # + memory / cron per setup
scp /tmp/agent-pack.tgz <user>@<newbox>:~/
```
On the new box: install Hermes, extract the pack, fill real secrets into `~/.hermes/.env`
(provider keys **and** the rotated `TELEGRAM_BOT_TOKEN` from step 1), then make it a service
(systemd unit, `Restart=on-failure`) and `sudo systemctl enable --now hermes`.

### 6 · Bring up Telegram on the NEW instance first — and confirm
Start the new gateway, then verify from Telegram: message your bot, get a reply. Confirm the
new instance owns the poll:
```bash
T=$(grep -E '^TELEGRAM_BOT_TOKEN=' ~/.hermes/.env | cut -d= -f2-)
curl -s -o /dev/null -w '%{http_code}\n' "https://api.telegram.org/bot$T/getUpdates?timeout=1"
# 409 = an instance is polling (the new one) → good
```
Do not proceed until the bot answers.

### 7 · Re-point Hermes Desktop
Disconnect Desktop from the old gateway and reconnect to the new instance (its host/port).
Confirm the agent still has its soul, memory and skills — if it doesn't, the pack didn't land.

### 8 · Stop the old instance — from the host, not the agent
The agent **cannot** stop the gateway it is running through (a `systemd-run --user` helper
dies with the session). Stop it from the machine side: on the OLD host,
`docker stop <hermes-container>` or `sudo systemctl stop hermes`. Keep the old box until step
9 passes.

### 9 · Verify survival, then retire the old box
```bash
sudo reboot            # on the new box
ssh <user>@<newbox> "systemctl is-active hermes"
```
Agent back on its own and the bot answers → done. Until then, do not delete the old machine.

## Gotchas

- **A declared var is a forwarded var.** `/key` puts a value in `.env`; the agent's shell only sees it if the name is declared (`terminal.env_passthrough` or a skill's `required_environment_variables`). `execute_code` blocks `PASSWORD`-named vars outright.
- **One poller per token.** Two instances on one token → `409` forever. Rotate first (step 1).
- **Never paste a secret into chat.** Passwords and tokens go through `/key` (or the vault), in a DM.
- **Redaction breaks literal secrets.** Put the value in `.env`, reference `$VAR`; a literal becomes `[REDACTED]`.
- **Key auth before you close the door.** The BatchMode test must pass before `PasswordAuthentication no`.
- **Provider keys travel too.** An agent with no provider key answers nothing — fill `.env` on the target.
- **The agent can't kill its own gateway.** Host-side stop only.

## Handover line

`Moved to <newbox> · token rotated · Desktop re-pointed · old box stopped · reboot survived`

---

Course content © Andy Nguyen. For the Hermes & OpenClaw AI agent course.
