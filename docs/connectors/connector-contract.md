# Connector Contract

Activity connectors are the input side of the proactive loop. Each one turns a third-party
source (GitHub, browser, Slack) into a stream of `ActivitySignal`s that the daemon feeds to
the Interest Agent.

## The interface

```python
# daemon/connector_base.py
@dataclass
class ActivitySignal:
    source: str           # "github" | "browser" | "slack" | …
    event_type: str       # "commit" | "search" | "message" | …
    timestamp: datetime   # the event's REAL time — drives interest decay
    data: dict            # event-specific payload
    user_id: str | None = None
    description: str = ""

class ActivityConnector(ABC):
    def __init__(self, config: dict): ...          # reads `enabled`, name = class name
    async def fetch(self, since: datetime | None) -> list[ActivitySignal]   # required
    async def initialize(self) -> None             # optional: auth/setup
    async def shutdown(self) -> None               # optional: cleanup
```

`fetch(since)` returns only signals newer than `since` (delta query) and must **stamp each
signal with the event's real timestamp** — decay is age-based, so a wrong timestamp
silently corrupts the interest model.

## Registry

A process-global `ConnectorRegistry` (`connector_base.py`) holds registered connectors.
The daemon registers enabled ones at startup and iterates the enabled set each cycle:

```python
register_connector(connector)      # add to global registry
get_enabled_connectors()           # daemon iterates these every ingest cycle
```

## Adding a connector

1. Subclass `ActivityConnector`; set `self.name`; implement `async fetch(since)`.
2. Map source events → `ActivitySignal(source, event_type, timestamp, data)`.
3. Register it in `PersonalAssistantDaemon._initialize_connectors()` behind a config flag.
4. Add a `[connectors.<name>]` section to `config/settings.toml` (and the env equivalents).
5. Test with mocked signals (no live network).

## How signals become interests

`InterestAgent._signal_to_text` knows how to flatten each `(source, event_type)` into text
for classification (see [agents/interest.md](../agents/interest.md)). When you add a new
source/event, extend that method so the classifier sees the salient fields.

---

> **Source of truth:** `src/daemon/connector_base.py`,
> `src/daemon/service.py::_initialize_connectors`.
