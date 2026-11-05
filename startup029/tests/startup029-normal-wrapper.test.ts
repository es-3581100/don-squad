// STARTUP-029 Gate C1: execute the exact v1.18.35 SessionTools.resolve
// production normal-session AI-SDK tool wrapper. It is NOT debug agent --tool.
// No model request: a deterministic synthetic tool body and plugin hook are
// provided as in-process dependencies. This tests wrapper hook ordering, not
// auto-discovery/loading of the Don-Squad plugin or the complete prompt loop.
import { expect, test } from "bun:test"
import { Effect, Schema } from "effect"
import { SessionTools } from "@/session/tools"
import { Plugin } from "@/plugin"
import { Permission } from "@/permission"
import { ToolRegistry } from "@/tool/registry"
import { MCP } from "@/mcp"
import { Truncate } from "@/tool/truncate"
import { RuntimeFlags } from "@/effect/runtime-flags"

const blocked = "DS029_NORMAL_HOOK_BLOCKED_BEFORE_BODY"

test("normal session wrapper invokes tool.execute.before before a no-ask tool body", async () => {
  let hookCalls = 0
  let bodyCalls = 0
  const plugin = {
    trigger: (name: string, _input: any, output: any) => Effect.gen(function* () {
      if (name === "tool.execute.before") {
        hookCalls++
        return yield* Effect.fail(new Error(blocked))
      }
      return output
    }),
  }
  const registry = {
    tools: () => Effect.succeed([{
      id: "synthetic_would_mutate",
      description: "Only increments an in-memory counter if hook fails open",
      parameters: Schema.Struct({ marker: Schema.String }),
      execute: (_args:any, _ctx:any) => Effect.sync(() => {
        bodyCalls++
        return { title: "UNEXPECTED", output: "UNEXPECTED", metadata: {} }
      }),
    }]),
  }
  const fakePermission = { ask: () => Effect.die("Synthetic no-ask tool unexpectedly called Permission.ask") }
  const fakeMcp = { clients: () => Effect.succeed({}) }
  const fakeTruncate = { output: () => Effect.succeed({content:"",truncated:false}) }
  const input:any = {
    agent: {name:"don-squad",permission:[{ permission:"*",pattern:"*",action:"deny" }]},
    model: {providerID:"test",api:{id:"test-model",npm:"@ai-sdk/openai-compatible"}},
    session: {id:"ses_ds029",permission:[]},
    processor: {
      message:{id:"msg_ds029"},
      updateToolCall:()=>Effect.void,
      completeToolCall:()=>Effect.void,
    },
    bypassAgentCheck:false,messages:[],promptOps:{},
  }
  const program = SessionTools.resolve(input).pipe(
    Effect.provideService(Plugin.Service,plugin as any),
    Effect.provideService(Permission.Service,fakePermission as any),
    Effect.provideService(ToolRegistry.Service,registry as any),
    Effect.provideService(MCP.Service,fakeMcp as any),
    Effect.provideService(Truncate.Service,fakeTruncate as any),
    Effect.provideService(RuntimeFlags.Service,{} as any),
  )
  const tools:any = await Effect.runPromise(program)
  expect(tools.synthetic_would_mutate?.execute).toBeDefined()
  let errorString=""
  try {
    await tools.synthetic_would_mutate.execute(
      {marker:"synthetic"},
      {toolCallId:"call_ds029",abortSignal:new AbortController().signal},
    )
  } catch(error) { errorString = String(error) }
  expect(errorString).toContain(blocked)
  expect(hookCalls).toBe(1)
  expect(bodyCalls).toBe(0)
  console.log("DS029_C01_PRODUCTION_SESSION_TOOLS_HOOK_DENIAL_CONFIRMED__NO_MODEL")
})
