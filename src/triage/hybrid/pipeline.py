"""v1.5 — HybridPipeline: v1 plus one LLM call at the rule-miss node (docs/flows.md).

Steps 1-6 and 8-12 use the exact same v1 component classes, imported not rewritten. Only step 7
gains a second chance: an LLM call when no rule matches. Control flow is still entirely fixed in
code — the model is a function called at one node, never deciding what happens next. That is the
line this project draws between "automation" and "agentic" (docs/flows.md, the organising idea).
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import ValidationError

from triage.clock import Clock
from triage.contracts import (
    Citation,
    DecidedBy,
    Enrichment,
    InboundMessage,
    Outcome,
    Priority,
    Ticket,
    TriageDecision,
    TriageResult,
    Usage,
)
from triage.hybrid.classifier import Classification, ClassificationError, LlmClassifier
from triage.observability.audit import AuditTrail
from triage.observability.logging import correlation_scope, get_logger
from triage.observability.metrics import TriageMetrics
from triage.v1.cmdb import Cmdb, CmdbContext
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

PIPELINE_NAME = "v1_5_hybrid"


@dataclass(frozen=True, slots=True)
class HybridComponents:
    idempotency: IdempotencyStore
    parser: Parser
    extractor: Extractor
    cmdb: Cmdb
    rule_engine: RuleEngine
    classifier: LlmClassifier
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
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class HybridPipeline:
    def __init__(self, components: HybridComponents, clock: Clock, metrics: TriageMetrics) -> None:
        self._c = components
        self._clock = clock
        self._metrics = metrics
        self._log = get_logger(PIPELINE_NAME)

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
                    llm_calls=verdict.llm_calls,
                    prompt_tokens=verdict.prompt_tokens,
                    completion_tokens=verdict.completion_tokens,
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

        # 6) CMDB Lookup
        context = c.cmdb.lookup(
            employee_id=next(iter(fields.employee_ids), None),
            email=message.sender,
            asset_tag=next(iter(fields.asset_tags), None),
        )
        audit.add(
            "cmdb",
            "looked_up",
            employee=context.employee.employee_id if context.employee else None,
            department=context.department.department_id if context.department else None,
            asset=context.asset.asset_tag if context.asset else None,
            notes=list(context.notes),
        )

        # 7) Rule Engine
        match = c.rule_engine.match(ticket.subject, ticket.text)
        if match is not None:
            self._metrics.rule_hits.labels(rule_id=match.rule_id).inc()
            audit.add(
                "rule_engine",
                "rule_hit",
                rule_id=match.rule_id,
                category=match.category,
                urgency=match.urgency.value,
                phrase=match.matched_phrase,
                rules_version=c.rule_engine.version,
            )
            return self._finish(
                message,
                correlation_id,
                ticket,
                context,
                category=match.category,
                urgency=match.urgency,
                rule_id=match.rule_id,
                decided_by=DecidedBy.RULES,
                confidence=1.0,
                citations=(
                    Citation(source_id=f"rule:{match.rule_id}", quote=match.matched_phrase),
                ),
                audit=audit,
            )

        self._metrics.rule_misses.inc()
        audit.add("rule_engine", "no_match", rules_version=c.rule_engine.version)

        # 7b) LLM classify — the only step that differs from v1
        try:
            classification = c.classifier.classify(subject=ticket.subject, text=ticket.text)
        except ClassificationError as exc:
            audit.add("llm_classifier", "failed", error=str(exc))
            return self._to_human(
                message,
                correlation_id,
                f"no rule matched; llm classification failed: {exc}",
                audit,
                ticket,
            )
        audit.add(
            "llm_classifier",
            "classified",
            category=classification.category,
            urgency=classification.urgency.value,
            confidence=classification.confidence,
            attempts=classification.attempts,
            prompt_tokens=classification.prompt_tokens,
            completion_tokens=classification.completion_tokens,
        )

        return self._finish(
            message,
            correlation_id,
            ticket,
            context,
            category=classification.category,
            urgency=classification.urgency,
            rule_id=None,
            decided_by=DecidedBy.LLM_NODE,
            confidence=classification.confidence,
            citations=(Citation(source_id="llm:classify_ticket"),),
            audit=audit,
            classification=classification,
        )

    def _finish(
        self,
        message: InboundMessage,
        correlation_id: UUID,
        ticket: Ticket,
        context: CmdbContext,
        *,
        category: str,
        urgency: Level,
        rule_id: str | None,
        decided_by: DecidedBy,
        confidence: float,
        citations: tuple[Citation, ...],
        audit: AuditTrail,
        classification: Classification | None = None,
    ) -> _Verdict:
        # 8) Priority Matrix
        c = self._c
        assessment = c.priority_matrix.assess(
            urgency=urgency, context=context, subject=ticket.subject, text=ticket.text
        )
        audit.add(
            "priority_matrix",
            "assessed",
            impact=assessment.impact.value,
            urgency=assessment.urgency.value,
            priority=assessment.priority.value,
            reasons=list(assessment.impact_reasons),
        )

        # 9) SLA Calculator
        due_at = c.sla.due_at(ticket.received_at, assessment.priority)
        audit.add("sla", "due", due_at=due_at.isoformat())

        # 10) Routing Table
        route = c.routing.route(category=category, rule_id=rule_id, context=context)
        audit.add("routing_table", "routed", group=route.group, reason=route.reason)

        # 11) Responder
        reply = c.responder.render(
            ticket=ticket,
            category=category,
            priority=assessment.priority,
            assignment_group=route.group,
            due_at=due_at,
            context=context,
        )
        audit.add("responder", "rendered", template=f"{category}.j2")

        decision = self._decision(
            category,
            assessment.priority,
            route.group,
            context,
            due_at,
            reply,
            confidence,
            citations,
        )

        # 12) ITSM Write
        write = c.itsm_writer.write(
            ItsmTicketRequest(
                idempotency_key=idempotency_key(message.message_id),
                correlation_id=correlation_id,
                requester=message.sender,
                subject=ticket.subject,
                description=ticket.text,
                decision=decision,
            )
        )
        self._metrics.itsm_attempts.inc(write.attempts)
        llm_calls = classification.attempts if classification else 0
        prompt_tokens = classification.prompt_tokens if classification else 0
        completion_tokens = classification.completion_tokens if classification else 0
        if write.ref is None:
            audit.add("itsm", "dead_lettered", attempts=write.attempts, error=write.error)
            reason = f"ITSM write failed after {write.attempts} attempts: {write.error}"
            return _Verdict(
                Outcome.DEAD_LETTER,
                decision,
                decided_by,
                reason,
                llm_calls,
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
            llm_calls=llm_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    @staticmethod
    def _decision(
        category: str,
        priority: Priority,
        group: str,
        context: CmdbContext,
        due_at: object,
        reply: str,
        confidence: float,
        citations: tuple[Citation, ...],
    ) -> TriageDecision:
        return TriageDecision(
            category=category,
            priority=priority,
            assignment_group=group,
            enrichment=Enrichment(
                department=context.department.name if context.department else None,
                service=context.asset.service.name if context.asset else None,
                asset_tag=context.asset.asset_tag if context.asset else None,
            ),
            sla_due_at=due_at,  # type: ignore[arg-type]
            draft_response=reply,
            confidence=confidence,
            citations=citations,
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
