#!/usr/bin/env python3
"""DonSquad live lifecycle binding to Squawk Box (production integration).

This module provides the real DonSquad lead (primary LLM agent) with a
simple, foolproof API to emit contemporaneous Squawk Box lifecycle events
while orchestrating real work. It is NOT a smoke test, NOT a helper, and
NOT retrospective.

The lead MUST call these in order:
    with DonSquadLifecycle(task_id="...", objective="...") as lifecycle:
        # lifecycle.begin() emits task.created, READY, ACTIVE, attempt.started
        worker_view = lifecycle.dispatch_worker()
        # ... lead dispatches real work via subagent tool ...
        # ... lead receives worker handoff ...
        lifecycle.accept(worker_handoff, artifacts=...)
        lifecycle.complete_attempt("SUCCEEDED")
    # context exit emits task COMPLETE

Any deviation (missing calls, wrong order, retrospective fabrication)
is a binding failure.
"""
from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Squawk Box imports
SQUAWK_ROOT = Path("/home/sticky-ricky/repos/es-3581100/squawk-box")
if str(SQUAWK_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(SQUAWK_ROOT))

from squawk_box.donsquad import DonSquadManager, WorkerReturn
from squawk_box.ledger import LedgerStore


# Persistent ledger location (shared across operations)
LEDGER_ROOT = Path(os.environ.get("DONSQUAD_LEDGER_ROOT",
    Path.home() / ".local" / "state" / "don-squad" / "ledger")).resolve()


@dataclass
class LifecycleContext:
    """Holds active lifecycle state for a single DonSquad task."""
    manager: DonSquadManager
    task_id: str
    attempt_id: str
    worker_view: Any  # WorkerView
    ledger_root: Path
    started: bool = False
    worker_dispatched: bool = False
    worker_returned: bool = False
    attempt_completed: bool = False
    task_completed: bool = False


class DonSquadLifecycle:
    """
    Production lifecycle binding for the real DonSquad lead.

    Usage (lead MUST follow this exact sequence):
        lifecycle = DonSquadLifecycle(objective="...", external_key="...")
        try:
            lifecycle.begin()  # task.created, READY, ACTIVE, attempt.started
            worker_view = lifecycle.dispatch_worker()
            # Lead dispatches real work via subagent tool using worker_view IDs
            # Lead receives worker handoff (agent-io/v1 return)
            lifecycle.accept(worker_handoff_dict, artifacts=[...])
            lifecycle.complete_attempt("SUCCEEDED")
            lifecycle.complete_task()
        finally:
            lifecycle.ensure_complete()  # Emits COMPLETE if not already done
    """

    def __init__(
        self,
        objective: str,
        external_key: Optional[str] = None,
        title: Optional[str] = None,
        ledger_root: Optional[Path] = None,
        build_id: Optional[str] = None,
    ) -> None:
        self._objective = objective
        self._external_key = external_key or f"ds-task-{uuid.uuid4().hex[:8]}"
        self._title = title or objective[:80]
        self._ledger_root = ledger_root or LEDGER_ROOT
        self._build_id = build_id or f"donsquad-{uuid.uuid4().hex[:8]}"
        self._ctx: Optional[LifecycleContext] = None
        self._store: Optional[LedgerStore] = None
        self._manager: Optional[DonSquadManager] = None

    def _ensure_store(self) -> LedgerStore:
        if self._store is None:
            self._store = LedgerStore(self._ledger_root)
            if not self._store.config_path.exists():
                self._store.initialize(build_id=self._build_id)
            else:
                self._store.require_initialized()
        return self._store

    def _ensure_manager(self) -> DonSquadManager:
        if self._manager is None:
            self._manager = DonSquadManager(self._ensure_store())
        return self._manager

    def begin(self) -> "WorkerView":
        """Emit task.created, READY, ACTIVE, attempt.started. Returns WorkerView for dispatch."""
        if self._ctx is not None:
            raise RuntimeError("Lifecycle already begun; cannot call begin() twice")
        mgr = self._ensure_manager()
        task_id = mgr.begin_task(
            external_key=self._external_key,
            title=self._title,
            objective=self._objective,
        )
        mgr.activate_task(task_id)
        attempt_id = mgr.start_attempt(task_id, ordinal=1)
        worker_view = mgr.dispatch_worker(task_id, attempt_id)
        self._ctx = LifecycleContext(
            manager=mgr,
            task_id=task_id,
            attempt_id=attempt_id,
            worker_view=worker_view,
            ledger_root=self._ledger_root,
            started=True,
        )
        return worker_view

    def dispatch_worker(self) -> Any:
        """Return the WorkerView for the current attempt (after begin())."""
        if self._ctx is None:
            raise RuntimeError("Must call begin() before dispatch_worker()")
        if self._ctx.worker_dispatched:
            raise RuntimeError("Worker already dispatched for this attempt")
        self._ctx.worker_dispatched = True
        return self._ctx.worker_view

    def accept(
        self,
        worker_return: dict[str, Any] | WorkerReturn,
        artifacts: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Record worker observations, claims, failure; observe artifact files."""
        if self._ctx is None:
            raise RuntimeError("Must call begin() before accept()")
        if self._ctx.worker_returned:
            raise RuntimeError("Worker return already accepted for this attempt")
        mgr = self._ctx.manager
        if isinstance(worker_return, dict):
            wr = WorkerReturn.from_dict(worker_return)
        else:
            wr = worker_return
        # Validate IDs match
        if wr.task_id != self._ctx.task_id:
            raise ValueError(f"WorkerReturn task_id {wr.task_id} != lifecycle task_id {self._ctx.task_id}")
        if wr.attempt_id != self._ctx.attempt_id:
            raise ValueError(f"WorkerReturn attempt_id {wr.attempt_id} != lifecycle attempt_id {self._ctx.attempt_id}")
        # Manager records worker return
        accepted = mgr.accept_worker_return(wr)
        # Observe artifacts if provided
        if artifacts:
            for art in artifacts:
                logical = art.get("logical_name") or art.get("logicalName")
                wpath = art.get("workspace_path") or art.get("workspacePath")
                atype = art.get("artifact_type") or art.get("artifactType", "file")
                if not logical or not wpath:
                    raise ValueError("Artifact requires logical_name and workspace_path")
                mgr.observe_artifact(self._ctx.task_id, self._ctx.attempt_id, logical, wpath, artifact_type=atype)
        self._ctx.worker_returned = True
        return accepted

    def complete_attempt(self, outcome: str = "SUCCEEDED", result: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Emit attempt.completed with outcome."""
        if self._ctx is None:
            raise RuntimeError("Must call begin() before complete_attempt()")
        if self._ctx.attempt_completed:
            raise RuntimeError("Attempt already completed")
        mgr = self._ctx.manager
        event = mgr.complete_attempt(self._ctx.attempt_id, outcome, result=result)
        self._ctx.attempt_completed = True
        return event

    def complete_task(self) -> dict[str, Any]:
        """Emit task.status_changed COMPLETE."""
        if self._ctx is None:
            raise RuntimeError("Must call begin() before complete_task()")
        if self._ctx.task_completed:
            raise RuntimeError("Task already completed")
        mgr = self._ctx.manager
        event = mgr.set_task_status(self._ctx.task_id, "COMPLETE")
        self._ctx.task_completed = True
        return event

    def ensure_complete(self) -> None:
        """Best-effort: emit COMPLETE if lifecycle started but not completed."""
        if self._ctx and self._ctx.started and not self._ctx.task_completed:
            try:
                self.complete_task()
            except Exception:
                pass  # Best effort; don't mask original error

    def fail_task(self, reason: str, outcome: str = "FAILED") -> None:
        """Emit failure path: attempt.completed with failure outcome, then COMPLETE."""
        if self._ctx is None:
            raise RuntimeError("Must call begin() before fail_task()")
        if not self._ctx.attempt_completed:
            self.complete_attempt(outcome, result={"error": reason})
        if not self._ctx.task_completed:
            self.complete_task()

    @property
    def task_id(self) -> Optional[str]:
        return self._ctx.task_id if self._ctx else None

    @property
    def attempt_id(self) -> Optional[str]:
        return self._ctx.attempt_id if self._ctx else None

    @property
    def ledger_root(self) -> Path:
        return self._ledger_root


# Convenience context manager for simplest usage
@contextmanager
def don_squad_task(objective: str, external_key: Optional[str] = None, title: Optional[str] = None, ledger_root: Optional[Path] = None, build_id: Optional[str] = None):
    """
    Context manager for the simplest lifecycle binding.

    Usage:
        with don_squad_task("Update portfolio docs") as lifecycle:
            worker_view = lifecycle.begin()
            # dispatch real work via subagent
            # receive handoff
            lifecycle.accept(handoff)
            lifecycle.complete_attempt("SUCCEEDED")
        # COMPLETE emitted on exit
    """
    lifecycle = DonSquadLifecycle(objective=objective, external_key=external_key, title=title, ledger_root=ledger_root, build_id=build_id)
    try:
        yield lifecycle
        if lifecycle._ctx and lifecycle._ctx.started and not lifecycle._ctx.task_completed:
            lifecycle.complete_task()
    except Exception:
        if lifecycle._ctx and lifecycle._ctx.started and not lifecycle._ctx.task_completed:
            lifecycle.fail_task("exception during task")
        raise


# Export WorkerView for type hints
WorkerView = DonSquadManager.dispatch_worker.__annotations__["return"]


if __name__ == "__main__":  # pragma: no cover - manual integration test
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "test-ledger"
        lc = DonSquadLifecycle("integration test", ledger_root=root)
        try:
            wv = lc.begin()
            print(f"Task: {lc.task_id}, Attempt: {lc.attempt_id}")
            print(f"WorkerView: task_id={wv.task_id}, attempt_id={wv.attempt_id}")
            wr = wv.build_worker_return(
                outcome="SUCCEEDED",
                observations=[{"summary": "test", "detail": "ok"}],
                artifacts=[{"logical_name": "test", "workspace_path": "/tmp/x", "artifact_type": "file"}],
            )
            lc.accept(wr)
            lc.complete_attempt("SUCCEEDED")
            print("accept/complete ok")
        finally:
            lc.ensure_complete()
        print(f"Ledger at: {root}")