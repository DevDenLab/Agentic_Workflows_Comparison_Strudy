"""v2 — AgentPipeline: a deterministic shell around one reasoning loop (docs/flows.md).

Steps 1-4 (intake through extraction) are v1's exact code, imported not rewritten, same as v1.5.
Unlike v1.5, there is no rule-engine pre-filter: every ticket goes to the agent, which may itself
choose to call `apply_rules` as one of its tools — that is the literal sense in which v1 runs
inside v2. The confidence gate, not the model, decides auto-resolve vs. escalate. Any failure in
the loop (provider error, exhausted budget, exhausted repairs) falls back to v1's rule engine
directly, never to a raw failure.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import ValidationError

from triage.clock import Clock
from triage.contracts import (
    Citation,
    DecidedBy,
    Enrichment,
    InboundMessage,
    Outcome,
    Ticket,
    TriageDecision,
    TriageResult,
    Usage,
)
from triage.observability.audit import AuditTrail
from triage.observability.logging import correlation_scope, get_logger
from triage.observability.metrics import TriageMetrics
from triage.v1.cmdb import Cmdb
from triage.v1.extractor import Extractor
from triage.v1.human_queue import HumanQueue, HumanQueueItem
from triage.v1.itsm import DeadLetterQueue, ItsmTicketRequest, ItsmWriter, idempotency_key
from triage.v1.parser import Parser
from triage.v1.priority_matrix import Level, PriorityMatrix
from triage.v1.queue import IdempotencyStore
from triage.v1.responder import Responder
from triage.v1.routing_table import RoutingTable
from triage.v1.rule_engine import RuleEngine
from triage.v1.sla import SlaCalculator
from triage.v2.agent import AgentFailure, Orchestrator
from triage.v2.budget import BudgetConfig, BudgetExceeded, BudgetGovernor
from triage.v2.confidence import (
    ConfidenceConfig,
    ConfidenceSignals,
    compute_confidence,
    may_auto_resolve,
)
from triage.v2.critic import CriticError, GroundingCritic, citations_are_grounded
from triage.v2.guardrail import InjectionDetector, PiiGuardrail
from triage.v2.retrieval import SearchIndex
from triage.v2.tools import ApplyRulesTool, CmdbLookupTool, KbSearchTool, SimilarTicketsTool, Tool

PIPELINE_NAME = "v2_agentic"


@dataclass(frozen=True, slots=True)
class AgentComponents:
    idempotency: IdempotencyStore
    parser: Parser
    extractor: Extractor
    cmdb: Cmdb
    rule_engine: RuleEngine
    orchestrator: Orchestrator
    critic: GroundingCritic
    budget: BudgetConfig
    confidence: ConfidenceConfig
    kb_index: SearchIndex
    history_index: SearchIndex
    priority_matrix: PriorityMatrix
    sla: SlaCalculator
    routing: RoutingTable
    responder: Responder
    itsm_writer: ItsmWriter
    dead_letters: DeadLetterQueue
    human_queue: HumanQueue


@dataclass(frozen=True, slots=True)
class _Verdict:
    outcome: Outcome
    decision: TriageDecision | None = None
    decided_by: DecidedBy | None = None
    reason: str | None = None
    agent_steps: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class AgentPipeline:
    def __init__(self, components: AgentComponents, clock: Clock, metrics: TriageMetrics) -> None:
        self._c = components
        self._clock = clock
        self._metrics = metrics
        self._log = get_logger(PIPELINE_NAME)
        self._injection_detector = InjectionDetector()

    @property
    def name(self) -> str:
        return PIPELINE_NAME

    def triage(self, message: InboundMessage) -> TriageResult:
        correlation_id = uuid4()
        started = self._clock.monotonic()
        with correlation_scope(correlation_id):
            audit = AuditTrail(self._clock)
            verdict = self._run(message, correlation_id, audit)
            if verdict.outcome is not Outcome.DUPLICATE:
                self._c.idempotency.record(message.message_id, verdict.outcome)
            elapsed = self._clock.monotonic() - started
            result = TriageResult(
                correlation_id=correlation_id,
                message_id=message.message_id,
                pipeline=self.name,
                outcome=verdict.outcome,
                decision=verdict.decision,
                decided_by=verdict.decided_by,
                escalation_reason=verdict.reason,
                usage=Usage(
                    latency_ms=elapsed * 1000,
                    llm_calls=verdict.agent_steps,
                    prompt_tokens=verdict.prompt_tokens,
                    completion_tokens=verdict.completion_tokens,
                    agent_steps=verdict.agent_steps,
                ),
                audit=audit.events,
            )
            self._record_metrics(result, elapsed)
            self._log.info("triaged", outcome=result.outcome.value, message_id=message.message_id)
        return result

    def _run(self, message: InboundMessage, correlation_id: UUID, audit: AuditTrail) -> _Verdict:
        c = self._c

        # 2) Queue & Dedupe
        if c.idempotency.seen(message.message_id):
            audit.add("queue", "duplicate")
            return _Verdict(Outcome.DUPLICATE)

        # 3) Parser
        text = c.parser.parse(message)
        audit.add("parser", "parsed", characters=len(text))

        # 4) Extractor
        fields = c.extractor.extract(message.subject, text)
        audit.add(
            "extractor",
            "extracted",
            employee_ids=list(fields.employee_ids),
            asset_tags=list(fields.asset_tags),
            error_codes=list(fields.error_codes),
        )

        # 5) Validate
        try:
            ticket = Ticket(
                correlation_id=correlation_id,
                message_id=message.message_id,
                channel=message.channel,
                received_at=message.received_at,
                sender=message.sender,
                subject=message.subject,
                text=text,
                extracted=fields,
            )
        except ValidationError as exc:
            return self._to_human(message, correlation_id, f"invalid ticket: {_first(exc)}", audit)

        # 5) Input Guardrail
        guardrail = PiiGuardrail()
        redacted = guardrail.redact(ticket.subject, ticket.text)
        scan = self._injection_detector.scan(ticket.text)
        audit.add(
            "guardrail",
            "redacted",
            injection_suspected=scan.suspicious,
            matched_phrases=list(scan.matched_phrases),
        )

        # 6) Budget Governor
        budget = BudgetGovernor(c.budget, self._clock)

        # 7) Orchestrator Agent
        tools: list[Tool] = [
            KbSearchTool(c.kb_index),
            SimilarTicketsTool(c.history_index),
            CmdbLookupTool(c.cmdb, guardrail),
            ApplyRulesTool(c.rule_engine, redacted.subject, redacted.text),
        ]
        try:
            agent_run = c.orchestrator.run(redacted.subject, redacted.text, tools, budget)
        except (AgentFailure, BudgetExceeded) as exc:
            audit.add("agent", "failed", error=str(exc))
            return self._fallback_to_rules(message, correlation_id, ticket, audit)
        audit.add(
            "agent",
            "submitted",
            category=agent_run.decision.category,
            urgency=agent_run.decision.urgency.value,
            citations=list(agent_run.decision.citations),
            steps=agent_run.steps,
            repair_attempts=agent_run.repair_attempts,
            tool_calls=[tc.name for tc in agent_run.tool_calls],
        )

        # 8) Schema Gate (citations grounded in what was actually retrieved)
        code_grounded, unknown = citations_are_grounded(
            agent_run.decision.citations, agent_run.seen_source_ids
        )
        if not code_grounded:
            audit.add("schema_gate", "ungrounded_citations", unknown=list(unknown))

        # 9) Critic
        grounded = code_grounded
        critic_reason = "citation referenced a source never retrieved" if not code_grounded else ""
        if code_grounded:
            excerpts = [
                agent_run.source_excerpts.get(cid, "(no excerpt recorded)")
                for cid in agent_run.decision.citations
            ]
            try:
                verdict = c.critic.review(
                    category=agent_run.decision.category,
                    urgency=agent_run.decision.urgency.value,
                    rationale=agent_run.decision.rationale,
                    cited_excerpts=excerpts,
                )
                grounded, critic_reason = verdict.grounded, verdict.reason
            except CriticError as exc:
                grounded, critic_reason = False, f"critic unavailable: {exc}"
        audit.add("critic", "reviewed", grounded=grounded, reason=critic_reason)

        # 10) Confidence Gate
        agreement = (
            agent_run.apply_rules_category == agent_run.decision.category
            if agent_run.apply_rules_matched
            else None
        )
        confidence = compute_confidence(
            ConfidenceSignals(
                critic_grounded=grounded,
                apply_rules_agreement=agreement,
                retrieval_strength=agent_run.retrieval_strength,
                repair_attempts=agent_run.repair_attempts,
            )
        )

        draft, _due_at = self._draft(
            message,
            ticket,
            category=agent_run.decision.category,
            urgency=agent_run.decision.urgency,
            rule_id=agent_run.apply_rules_rule_id if agreement else None,
            confidence=confidence,
            citations=tuple(Citation(source_id=cid) for cid in agent_run.decision.citations),
        )
        auto = may_auto_resolve(confidence, draft.category, draft.priority, c.confidence)
        audit.add(
            "confidence_gate",
            "gated",
            confidence=round(confidence, 3),
            apply_rules_agreement=agreement,
            retrieval_strength=round(agent_run.retrieval_strength, 3),
            auto_resolve=auto,
        )

        if not auto:
            reason = f"confidence {confidence:.2f} below threshold, or high blast radius"
            self._c.human_queue.put(
                HumanQueueItem(
                    correlation_id=correlation_id,
                    message=message,
                    reason=reason,
                    ticket=ticket,
                    draft=draft,
                    evidence=agent_run.decision.citations,
                )
            )
            audit.add("human_queue", "queued", confidence=round(confidence, 3))
            return _Verdict(
                Outcome.HUMAN_REVIEW,
                draft,
                DecidedBy.AGENT,
                reason,
                agent_run.steps,
                agent_run.prompt_tokens,
                agent_run.completion_tokens,
            )

        return self._write_itsm(
            message,
            correlation_id,
            draft,
            DecidedBy.AGENT,
            audit,
            agent_steps=agent_run.steps,
            prompt_tokens=agent_run.prompt_tokens,
            completion_tokens=agent_run.completion_tokens,
        )

    def _fallback_to_rules(
        self, message: InboundMessage, correlation_id: UUID, ticket: Ticket, audit: AuditTrail
    ) -> _Verdict:
        """The model is unavailable or the budget ran out: fall back to v1's rule engine rather
        than failing. This is deterministic, so it never needs the confidence gate."""
        c = self._c
        match = c.rule_engine.match(ticket.subject, ticket.text)
        if match is None:
            audit.add("rule_engine", "no_match_fallback")
            return self._to_human(
                message, correlation_id, "agent unavailable; no rule matched", audit, ticket
            )
        audit.add(
            "rule_engine",
            "rule_hit_fallback",
            rule_id=match.rule_id,
            category=match.category,
            urgency=match.urgency.value,
        )
        draft, _ = self._draft(
            message,
            ticket,
            category=match.category,
            urgency=match.urgency,
            rule_id=match.rule_id,
            confidence=1.0,
            citations=(Citation(source_id=f"rule:{match.rule_id}", quote=match.matched_phrase),),
        )
        return self._write_itsm(message, correlation_id, draft, DecidedBy.RULES_FALLBACK, audit)

    def _draft(
        self,
        message: InboundMessage,
        ticket: Ticket,
        *,
        category: str,
        urgency: Level,
        rule_id: str | None,
        confidence: float,
        citations: tuple[Citation, ...],
    ) -> tuple[TriageDecision, datetime]:
        c = self._c
        context = c.cmdb.lookup(
            employee_id=next(iter(ticket.extracted.employee_ids), None),
            email=message.sender,
            asset_tag=next(iter(ticket.extracted.asset_tags), None),
        )
        assessment = c.priority_matrix.assess(
            urgency=urgency, context=context, subject=ticket.subject, text=ticket.text
        )
        due_at = c.sla.due_at(ticket.received_at, assessment.priority)
        route = c.routing.route(category=category, rule_id=rule_id, context=context)
        reply = c.responder.render(
            ticket=ticket,
            category=category,
            priority=assessment.priority,
            assignment_group=route.group,
            due_at=due_at,
            context=context,
        )
        decision = TriageDecision(
            category=category,
            priority=assessment.priority,
            assignment_group=route.group,
            enrichment=Enrichment(
                department=context.department.name if context.department else None,
                service=context.asset.service.name if context.asset else None,
                asset_tag=context.asset.asset_tag if context.asset else None,
            ),
            sla_due_at=due_at,
            draft_response=reply,
            confidence=confidence,
            citations=citations,
        )
        return decision, due_at

    def _write_itsm(
        self,
        message: InboundMessage,
        correlation_id: UUID,
        decision: TriageDecision,
        decided_by: DecidedBy,
        audit: AuditTrail,
        *,
        agent_steps: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> _Verdict:
        write = self._c.itsm_writer.write(
            ItsmTicketRequest(
                idempotency_key=idempotency_key(message.message_id),
                correlation_id=correlation_id,
                requester=message.sender,
                subject=message.subject,
                description=message.raw_body,
                decision=decision,
            )
        )
        self._metrics.itsm_attempts.inc(write.attempts)
        if write.ref is None:
            audit.add("itsm", "dead_lettered", attempts=write.attempts, error=write.error)
            reason = f"ITSM write failed after {write.attempts} attempts: {write.error}"
            return _Verdict(
                Outcome.DEAD_LETTER,
                decision,
                decided_by,
                reason,
                agent_steps,
                prompt_tokens,
                completion_tokens,
            )
        audit.add(
            "itsm",
            "created",
            ticket_number=write.ref.number,
            new_ticket=write.ref.created,
            attempts=write.attempts,
        )
        return _Verdict(
            Outcome.AUTO_RESOLVED,
            decision,
            decided_by,
            None,
            agent_steps,
            prompt_tokens,
            completion_tokens,
        )

    def _to_human(
        self,
        message: InboundMessage,
        correlation_id: UUID,
        reason: str,
        audit: AuditTrail,
        ticket: Ticket | None = None,
    ) -> _Verdict:
        self._c.human_queue.put(
            HumanQueueItem(
                correlation_id=correlation_id, message=message, reason=reason, ticket=ticket
            )
        )
        audit.add("human_queue", "queued", reason=reason)
        return _Verdict(Outcome.HUMAN_REVIEW, reason=reason)

    def _record_metrics(self, result: TriageResult, elapsed_seconds: float) -> None:
        decided_by = result.decided_by.value if result.decided_by else "none"
        self._metrics.tickets.labels(
            pipeline=self.name, outcome=result.outcome.value, decided_by=decided_by
        ).inc()
        self._metrics.latency.labels(pipeline=self.name).observe(elapsed_seconds)
        self._metrics.dead_letter_depth.set(self._c.dead_letters.depth())
        self._metrics.human_queue_depth.set(self._c.human_queue.depth())


def _first(exc: ValidationError) -> str:
    error = exc.errors()[0]
    return f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
