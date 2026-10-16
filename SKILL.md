---
name: agent-house-moving
description: Use when moving a Hermes agent to a new machine.
version: 1.1.0
author: Andy
license: MIT
required_environment_variables:
  - name: VPS_PW
    prompt: SSH password for the new box
    help: Password for the sudo-capable user on the new machine (set it with /key VPS_PW <pw> in a DM).
  - name: TELE_2ND_BOT
    prompt: Token of the bot the moved agent will own
    help: The new bot's token from @BotFather (set it with /key TELE_2ND_BOT <token> in a DM). The agent copies it to the new box as TELEGRAM_BOT_TOKEN.
metadata:
  hermes:
    tags: [hermes, migration, deploy, ssh, systemd, telegram]
    category: devops
---

# Agent House-Moving

Move a Hermes agent off the machine it was built on and onto your own VPS or MiniPC —
identity, memory, skills, secrets and Telegram channel intact — then prove it survives on
its own. Run the steps in order; the order is the safety.

## When to Use

Use when asked to "move my agent to my new box", "deploy my agent on my VPS", "take my
agent home", or any Session 5 capstone house-move — moving a Hermes agent to a new machine
(VPS or MiniPC).

## Two names carry the two secrets

Neither value is ever typed into chat; both go in through `/key` in a **DM**:

| Name | What it holds | Where it ends up |
|------|---------------|------------------|
| `VPS_PW` | SSH password of the sudo-capable user on the new box | used once by `sshpass` to install the key, then removed |
| `TELE_2ND_BOT` | token of the new bot the moved agent owns (from @BotFather → `/newbot`) | copied to the new box as `TELEGRAM_BOT_TOKEN` |

Both are declared in this skill's `required_environment_variables`, so once the skill is
loaded the agent's `terminal` can read `$VPS_PW` and `$TELE_2ND_BOT`.

> **Where the agent lives.** On a normal install the Hermes home is `~/.hermes`; in the
> course container it is `/opt/data` (so `config.yaml`, `.env` and `skills/` live there).
> Use `$HERMES_HOME` rather than hard-coding a path.

## What moves (and what never does)

Ship what *defines* the agent — settings, skills, memory, schedules — as a package with
**no secret values in it**. Real secrets (provider keys, the Telegram token) are filled in
on the target, never carried in the bag.

## The sequence

### 0 · Prep — the new box is reachable

- Put the new box on **Tailscale** (so both the old box and Hermes Desktop can reach it),
  or confirm it is on the same LAN.
- Note its address and a sudo-capable user + password.
- Check: `ssh -o ConnectTimeout=10 <user>@<newbox> hostname`

### 1 · Give the moved agent its own bot — do this first

The agent already has a bot on the old box. The moved agent gets a **new** bot of its own,
so the two never contend for one token (only one instance can poll a given token, so two
instances on one token would `409` forever).

In Telegram, DM **@BotFather** → `/newbot` → pick a name and a username → copy the token.
Then, in a **DM** with the agent on the old box:

```
/key TELE_2ND_BOT <the new token>
```

Keep the token out of any group chat. Using a fresh bot rather than revoking the old one is
deliberate: the old box keeps working untouched, and the new box gets a token nobody else
polls — no `409`, no revocation, nothing to undo. Send the new bot a `/start` from your own
Telegram account so it can reach you.

### 2 · Hand the new box's SSH password to the agent — via /key, never in chat

```
/key VPS_PW <the password>
```

`/key` writes it to `$HERMES_HOME/.env` **without the value ever reaching the model**. Use a
**DM only** — anything typed in a group is visible to everyone in it.

> The `/key` command ships with this skill: the `keyenv` plugin lives in `plugins/keyenv/`. Where you have to install it: `cp -r plugins/keyenv "$HERMES_HOME/plugins/" && hermes plugins enable keyenv`. In the course container it is already installed.

**Declare it, or the shell can't read it.** Putting the name in `.env` is not the same as
forwarding it to the agent's commands: sandboxed children run with a scrubbed environment.
Add the name to `terminal.env_passthrough` in `config.yaml`, or list it under this skill's
`required_environment_variables` (already done here). Then `$VPS_PW` is available to
`terminal` once the skill is loaded. Undeclared, it may still slip through on a plain local
backend, but `execute_code` blocks any name containing `PASSWORD` and a remote/Docker/SSH
backend forwards nothing it was not told to.

From here on, reference it as `$VPS_PW`, never as the literal: the terminal tool replaces a
literal secret with `[REDACTED]` and the command silently breaks.

### 3 · Install the agent's key on the new box

```bash
# create a key on the old box if there isn't one
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""

# push the public key (sshpass wrapping ssh-copy-id works; piping it does NOT)
sshpass -p "$VPS_PW" ssh-copy-id -o StrictHostKeyChecking=accept-new <user>@<newbox>
```

If `sshpass`/`ssh-copy-id` is unavailable:

```bash
sshpass -p "$VPS_PW" ssh -o StrictHostKeyChecking=accept-new <user>@<newbox> \
  "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" \
  < ~/.ssh/id_ed25519.pub
```

Optional, needed for hands-off automation: passwordless sudo. This step must be run by the
human, interactively — non-interactive sudo needs a TTY:

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

Never disable password auth before the BatchMode test passes, or you lock yourself out.
Then drop the password so it is not sitting in `.env` when you pack:

```
/key rm VPS_PW
```

### 5 · Pack and move the agent

Gather what defines the agent — never the secrets:

| What | Where | Ship as |
|------|-------|---------|
| Settings | `$HERMES_HOME/config.yaml` | the file |
| Secrets | `$HERMES_HOME/.env` | `.env.example` (keys, **NO values**) |
| Skills | `$HERMES_HOME/skills/` | the folders |
| Plugins | `$HERMES_HOME/plugins/` (optional) | ship `keyenv/` too if you want `/key` on the target |
| Memory | persistent store | export, or rebuild on first use |
| Schedules | cron config | the list |

```bash
tar czf /tmp/agent-pack.tgz -C "$HERMES_HOME" config.yaml skills   # + plugins / memory / cron per setup
scp /tmp/agent-pack.tgz <user>@<newbox>:~/
```

On the new box: install Hermes, extract the pack, then fill the real secrets into
`$HERMES_HOME/.env` — the provider key(s) **and** the new bot token. Copy them across
without ever printing a value (run this on the OLD box):

```bash
# old box → new box; the values travel over the pipe, nothing is echoed
grep -hE '^(TELE_2ND_BOT|TELEGRAM_ALLOWED_USERS|ANTHROPIC_API_KEY|OPENROUTER_API_KEY)=' "$HERMES_HOME/.env" \
  | sed 's/^TELE_2ND_BOT=/TELEGRAM_BOT_TOKEN=/' \
  | ssh <user>@<newbox> 'cat >> ~/.hermes/.env && chmod 600 ~/.hermes/.env'
```

Adjust the key names to the provider the agent actually uses, and make sure
`TELEGRAM_ALLOWED_USERS` carries your own Telegram user id — otherwise the new bot receives
your messages and ignores them. Then make it a service:

```ini
# /etc/systemd/system/hermes.service  — [Service] ExecStart=<hermes> gateway, Restart=on-failure
sudo systemctl enable --now hermes
```

### 6 · Bring up Telegram on the NEW instance first — and confirm

Start the new gateway, then verify from Telegram: message your bot, get a reply. Confirm
the new instance owns the poll:

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
`docker stop <hermes-container>` or `sudo systemctl stop hermes`. Keep the old box until
step 9 passes.

### 9 · Verify survival, then retire the old box

```bash
sudo reboot            # on the new box
# after it comes back:
ssh <user>@<newbox> "systemctl is-active hermes"
```

Agent back on its own and the bot answers → done. Until then, do not delete the old machine.

## Gotchas

- **A declared var is a forwarded var.** `/key` puts a value in `.env`; the agent's shell only sees it if the name is declared (`terminal.env_passthrough` or a skill's `required_environment_variables`). `execute_code` blocks `PASSWORD`-named vars outright.
- **One poller per token.** Two instances on one token → `409` forever. Give the moved agent its own bot (step 1) and there is no clash to begin with.
- **Never paste a secret into chat.** Passwords and tokens go through `/key` (or the vault), in a DM.
- **Redaction breaks literal secrets.** Put the value in `.env`, reference `$VAR` in commands; a literal becomes `[REDACTED]`.
- **Key auth before you close the door.** The BatchMode test must pass before `PasswordAuthentication no`.
- **Provider keys travel too.** An agent with no provider key answers nothing — fill `.env` on the target.
- **The new bot needs `TELEGRAM_ALLOWED_USERS`.** Without your user id in the target `.env`, the moved agent is deaf to your messages.
- **The agent can't kill its own gateway.** Host-side stop only.

## Handover line

`Moved to <newbox> · own bot issued · Desktop re-pointed · old box stopped · reboot survived`
