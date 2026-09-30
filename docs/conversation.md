# Bot conversation

## Cloud room scopes

Tico records the room contract on every conversation instead of inferring privacy from
the page that opened it:

- `personal`: one active room per human and bot. Tico (`bot:coo`) always uses this mode, so Ana,
  Ben, and every other signed-in human have different conversation and provider-session IDs.
  Ordinary owner inspection does not bypass another human's personal room. **Start fresh**
  archives the active room without deleting its messages and opens a new provider context on the
  next send.
- `shared`: one active room per `room_key`. CPO uses a shared room whose current members are its
  explicit/primary humans plus the team owner. Membership changes are enforced at read time and
  synchronized into the room; an old private CPO pair is archived intact and never copied into the
  group history.
- `task`: context attached to one task. Task discussion remains separate from both main room types.
- `direct`: legacy and bot-to-bot conversations that do not use a main-room contract.

The local runner keys provider sessions by `(bot, conversation, runtime)`. A personal Tico room is
therefore private at both the cloud-history and model-session layers, while every member of the CPO
room deliberately shares one provider context. Tico runs can call `hub health check` for a live
snapshot filtered to the human who initiated that private run. Personal messages, preferences,
and attachments must not be copied into Tico's shared repository files.

Every bot page shows its persistent main conversation from Tico messages and runs. Chat is a
conversation on hub.acme.example; the assigned computer executes the run and streams the reply back
into the same room. How the pieces fit: [How Tico works](how-it-works.md).
