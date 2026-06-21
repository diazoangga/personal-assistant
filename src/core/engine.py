"""Core Engine - interface-agnostic heart of the Personal Assistant."""

import asyncio
import uuid
from typing import Any, AsyncIterator, Callable

from .commands import (
    Command,
    Ask,
    Brainstorm,
    ShowInterests,
    ResearchTopic,
    ShowGraph,
    Opportunities,
    ShowDigest,
    Feedback,
    IngestNow,
    JobStatus,
    Cancel,
    SetPref,
    Topics,
    Sources,
)
from .events import Event, Started, Progress, Message, Result
from .jobs import Job, JobQueue
from .bus import EventBus


class Engine:
    """
    Core Engine that handles all commands and streams events.

    Interface-agnostic: both CLI and Slack adapters use this same engine.
    """

    def __init__(
        self,
        agents: dict[str, Any] | None = None,
        ingest: Any | None = None,
        store: Any | None = None,
        memory: Any | None = None,
        graph: Any | None = None,
        llm: Any | None = None,
    ):
        self._bus = EventBus()
        self._jobs = JobQueue()

        # Core dependencies (injected at construction)
        self._agents = agents or {}
        self._ingest = ingest
        self._store = store  # Vector KB
        self._memory = memory  # SQLite user model
        self._graph = graph  # SQLite graph store
        self._llm = llm  # OpenRouter runtime

    async def submit(self, cmd: Command) -> str:
        """
        Submit a command for async execution.

        Returns immediately with a job_id. Stream events via events().
        """
        job_id = uuid.uuid4().hex[:8]
        handler = self._route(cmd)

        # Create job and start handler
        job = Job(job_id=job_id, command=cmd)
        await self._jobs.spawn(job, handler(job_id, cmd))

        # Publish started event
        await self._bus.publish(Started(job_id=job_id, kind=cmd.__class__.__name__.lower()))

        return job_id

    def events(self, job_id: str) -> AsyncIterator[Event]:
        """Stream events for a job."""
        return self._bus.subscribe(job_id)

    def _route(self, cmd: Command) -> Callable:
        """Route command to its handler."""
        routes = {
            Ask: self._handle_ask,
            Brainstorm: self._handle_brainstorm,
            ResearchTopic: self._handle_research,
            ShowGraph: self._handle_graph,
            Opportunities: self._handle_opportunities,
            ShowDigest: self._handle_digest,
            Feedback: self._handle_feedback,
            IngestNow: self._handle_ingest,
            JobStatus: self._handle_status,
            Cancel: self._handle_cancel,
            SetPref: self._handle_setpref,
            Topics: self._handle_topics,
            Sources: self._handle_sources,
            ShowInterests: self._handle_interests,
        }
        return routes.get(type(cmd), self._handle_unknown)

    async def _handle_ask(self, job_id: str, cmd: Ask):
        """Handle Ask command - cited Q&A over KB."""
        try:
            if "brainstorm" not in self._agents:
                raise RuntimeError("Brainstorming Agent not initialized")

            # Use Brainstorming Agent's inquiry path
            agent = self._agents["brainstorm"]
            answer = await agent.answer(cmd.query)

            await self._bus.publish(
                Message(job_id=job_id, role="assistant", text=answer.text, citations=answer.citations)
            )
            await self._bus.publish(Result(job_id=job_id, ok=True, payload={"answer": answer.text}))
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_brainstorm(self, job_id: str, cmd: Brainstorm):
        """Handle Brainstorm command - interactive session."""
        try:
            if "brainstorm" not in self._agents:
                raise RuntimeError("Brainstorming Agent not initialized")

            agent = self._agents["brainstorm"]
            await agent.run_session(job_id, cmd, publish=self._bus.publish)
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_research(self, job_id: str, cmd: ResearchTopic):
        """Handle ResearchTopic command - manual Research Agent trigger."""
        try:
            if "research" not in self._agents:
                raise RuntimeError("Research Agent not initialized")

            agent = self._agents["research"]
            findings = await agent.research(cmd.topic, depth=cmd.depth, publish=self._bus.publish)

            await self._bus.publish(
                Result(job_id=job_id, ok=True, payload={"summary": findings.summary})
            )
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_graph(self, job_id: str, cmd: ShowGraph):
        """Handle ShowGraph command - view citation/knowledge graph."""
        try:
            if not self._graph:
                raise RuntimeError("Graph store not initialized")

            subgraph = await self._graph.relevant_subgraphs(
                interests=[cmd.topic] if cmd.topic else None
            )
            await self._bus.publish(
                Result(job_id=job_id, ok=True, payload={"graph": subgraph, "kind": cmd.kind})
            )
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_opportunities(self, job_id: str, cmd: Opportunities):
        """Handle Opportunities command - list/save/dismiss opportunities."""
        try:
            if "opportunity" not in self._agents:
                raise RuntimeError("Opportunity Agent not initialized")

            agent = self._agents["opportunity"]

            if cmd.action == "list":
                opps = await agent.list_opportunities()
                await self._bus.publish(
                    Result(job_id=job_id, ok=True, payload={"opportunities": opps})
                )
            elif cmd.action == "save" and cmd.ref:
                await agent.save_opportunity(cmd.ref)
                await self._bus.publish(Result(job_id=job_id, ok=True, payload={"saved": cmd.ref}))
            elif cmd.action == "dismiss" and cmd.ref:
                await agent.dismiss_opportunity(cmd.ref)
                await self._bus.publish(Result(job_id=job_id, ok=True, payload={"dismissed": cmd.ref}))
            else:
                raise ValueError(f"Invalid action: {cmd.action}")
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_digest(self, job_id: str, cmd: ShowDigest):
        """Handle ShowDigest command - show insight digest."""
        try:
            if "opportunity" not in self._agents:
                raise RuntimeError("Opportunity Agent not initialized")

            agent = self._agents["opportunity"]
            digest = await agent.build_digest(date=cmd.date)

            await self._bus.publish(
                Result(job_id=job_id, ok=True, payload={"digest": digest.to_dict()})
            )
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_feedback(self, job_id: str, cmd: Feedback):
        """Handle Feedback command - record feedback on recommendation/answer."""
        try:
            if not self._memory:
                raise RuntimeError("Memory store not initialized")

            self._memory.record_feedback(cmd)
            await self._bus.publish(Result(job_id=job_id, ok=True))
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_ingest(self, job_id: str, cmd: IngestNow):
        """Handle IngestNow command - trigger activity sensing."""
        try:
            if not self._ingest:
                raise RuntimeError("Ingest pipeline not initialized")

            await self._ingest.sense(connector=cmd.connector, publish=self._bus.publish, job_id=job_id)
            await self._bus.publish(Result(job_id=job_id, ok=True))
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_status(self, job_id: str, cmd: JobStatus):
        """Handle JobStatus command - check job status."""
        try:
            job = self._jobs.get(cmd.job_id) if cmd.job_id else None

            if not job:
                await self._bus.publish(
                    Result(job_id=job_id, ok=False, payload={"error": "Job not found"})
                )
                return

            await self._bus.publish(
                Result(
                    job_id=job_id,
                    ok=True,
                    payload={
                        "job_id": job.job_id,
                        "state": job.state.value,
                        "kind": type(job.command).__name__,
                        "created_at": job.created_at,
                        "updated_at": job.updated_at,
                    },
                )
            )
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_cancel(self, job_id: str, cmd: Cancel):
        """Handle Cancel command - cancel a running job."""
        try:
            cancelled = await self._jobs.cancel(cmd.job_id)
            await self._bus.publish(
                Result(job_id=job_id, ok=cancelled, payload={"cancelled": cancelled})
            )
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_setpref(self, job_id: str, cmd: SetPref):
        """Handle SetPref command - set user preference."""
        try:
            if not self._memory:
                raise RuntimeError("Memory store not initialized")

            self._memory.set_pref(cmd.key, cmd.value)
            await self._bus.publish(Result(job_id=job_id, ok=True))
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_topics(self, job_id: str, cmd: Topics):
        """Handle Topics command - manage tracked topics."""
        try:
            if not self._memory:
                raise RuntimeError("Memory store not initialized")

            if cmd.action == "add" and cmd.name:
                self._memory.add_topic(cmd.name)
            elif cmd.action == "rm" and cmd.name:
                self._memory.remove_topic(cmd.name)
            elif cmd.action == "list":
                pass  # Will be fetched from memory

            topics = self._memory.list_topics()
            await self._bus.publish(Result(job_id=job_id, ok=True, payload={"topics": topics}))
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_sources(self, job_id: str, cmd: Sources):
        """Handle Sources command - manage connectors."""
        try:
            if not self._ingest:
                raise RuntimeError("Ingest pipeline not initialized")

            if cmd.action == "add" and cmd.name:
                self._ingest.add_connector(cmd.name)
            elif cmd.action == "rm" and cmd.name:
                self._ingest.remove_connector(cmd.name)

            connectors = self._ingest.list_connectors()
            await self._bus.publish(Result(job_id=job_id, ok=True, payload={"connectors": connectors}))
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_interests(self, job_id: str, cmd: ShowInterests):
        """Handle ShowInterests command - show interest model."""
        try:
            if "interest" not in self._agents:
                raise RuntimeError("Interest Agent not initialized")

            agent = self._agents["interest"]

            if cmd.view == "show":
                interests = await agent.get_top_interests()
                await self._bus.publish(
                    Result(job_id=job_id, ok=True, payload={"interests": interests})
                )
            elif cmd.view == "timeline":
                timeline = await agent.get_interest_timeline()
                await self._bus.publish(
                    Result(job_id=job_id, ok=True, payload={"timeline": timeline})
                )
        except Exception as e:
            await self._bus.publish(Result(job_id=job_id, ok=False, payload={"error": str(e)}))

    async def _handle_unknown(self, job_id: str, cmd: Command):
        """Handle unknown commands."""
        await self._bus.publish(
            Result(
                job_id=job_id,
                ok=False,
                payload={"error": f"Unknown command: {type(cmd).__name__}"},
            )
        )
