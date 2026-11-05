// STARTUP-029 Gate B: executes the unmodified OpenCode v1.18.35 production
// Permission.node implementation (Effect Layer), not the debug-agent shortcut.
// Intended location in pinned repo: packages/opencode/test/donsquad-startup029/
// No model, tool, network, user files, permission approval UI, or Git calls.
import { describe, expect, test } from "bun:test"
import { Cause, Effect, Either, Exit, Fiber, Layer } from "effect"
import { Permission } from "@/permission"
import { EventV2Bridge } from "@/event-v2-bridge"
import { InstanceRef } from "@/effect/instance-ref"

const sessionA = "ses_startup029-a" as any
const sessionB = "ses_startup029-b" as any
const context = {
  directory: "/startup029-detached-only",
  worktree: "/startup029-detached-only",
  project: { id: "startup029-fixture" },
} as any

// Replace *only the event output*; run the actual Permission.node.implementation
// and its real InstanceState/ScopedCache, Deferred and Effect methods.
const eventStub = Layer.succeed(EventV2Bridge.Service, {
  publish: () => Effect.void,
} as any)
const production = Layer.provide(Permission.node.implementation!, eventStub)

const rule = (permission: string, action: "allow" | "deny" | "ask") =>
  ({ permission, pattern: "*", action })
const deny = (permission: string) => [rule(permission, "deny")]
const askRules = (permission: string) => [rule(permission, "ask")]

function request(permission: string, ruleset: any[], sessionID = sessionA, id?: string) {
  return {
    ...(id ? { id } : {}),
    sessionID,
    permission,
    patterns: ["synthetic_resource"],
    always: ["*"],
    ruleset,
    metadata: {},
  } as any
}

function withProduction<A, E, R>(program: Effect.Effect<A, E, R>) {
  return Effect.runPromise(
    Effect.scoped(
      program.pipe(
        Effect.provide(production),
        Effect.provideService(InstanceRef, context),
      ),
    ),
  )
}

const waitForPending = (service: any) => Effect.gen(function* () {
  for (let n = 0; n < 100; n++) {
    const list = yield* service.list()
    if (list.length === 1) return list[0]
    yield* Effect.sleep("10 millis")
  }
  return yield* Effect.fail(new Error("Pending request never observed"))
})

// This test returning PASS is *vulnerability reproduction*, not policy approval.
// The independent disposition must be BLOCKED when override_observed=true.
describe("STARTUP-029 Gate B: real V1 Effect Permission.Service", () => {
  test("hard agent deny rejects requests without an earlier approval", async () => {
    await withProduction(Effect.gen(function* () {
      const service = yield* Permission.Service
      for (const name of ["read","bash","edit","task","webfetch","websearch","skill","external_directory"]) {
        const outcome = yield* service.ask(request(name,deny(name))).pipe(Effect.either)
        expect(Either.isLeft(outcome)).toBe(true)
        if (Either.isLeft(outcome)) expect((outcome.left as any)._tag).toBe("PermissionDeniedError")
      }
      const allowed = yield* service.ask(request("question",[rule("question","allow")])).pipe(Effect.either)
      expect(Either.isRight(allowed)).toBe(true)
    }))
    console.log("DS029_B01_BASELINE_DENY_PASS")
  })

  test("persistent always approval supersedes later agent deny across requests", async () => {
    await withProduction(Effect.gen(function* () {
      const service = yield* Permission.Service
      // Start with ASK, let the service create a real pending entry / Deferred.
      const first = yield* Effect.fork(service.ask(request("read",askRules("read"),sessionA)))
      const pending = yield* waitForPending(service)
      yield* service.reply({requestID:pending.id, reply:"always"} as any)
      const approved = yield* Fiber.await(first)
      expect(Exit.isSuccess(approved)).toBe(true)
      // **Same underlying state**, but a new request has native agent DENY.
      // V1 evaluates [...deny, ...state.approved] with findLast.
      const second = yield* service.ask(request("read",deny("read"),sessionA)).pipe(Effect.either)
      expect(Either.isRight(second)).toBe(true)
      // Also challenge cross-session reuse within this per-instance cache.
      const third = yield* service.ask(request("read",deny("read"),sessionB)).pipe(Effect.either)
      expect(Either.isRight(third)).toBe(true)
    }))
    console.log("DS029_B02_APPROVAL_OVERRIDES_LATER_DENY_REPRODUCED__SECURITY_GATE_FAIL")
  })

  test("once approval does NOT persist and hard deny still blocks", async () => {
    await withProduction(Effect.gen(function* () {
      const service = yield* Permission.Service
      const fiber = yield* Effect.fork(service.ask(request("edit",askRules("edit"))))
      const pending = yield* waitForPending(service)
      yield* service.reply({requestID:pending.id, reply:"once"} as any)
      const initial = yield* Fiber.await(fiber)
      expect(Exit.isSuccess(initial)).toBe(true)
      const next = yield* service.ask(request("edit",deny("edit"))).pipe(Effect.either)
      expect(Either.isLeft(next)).toBe(true)
    }))
    console.log("DS029_B03_ONCE_NOT_PERSISTENT_PASS")
  })
})
