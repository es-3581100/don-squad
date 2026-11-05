// STARTUP-029 Gate C2: the *exact* STARTUP-020 guard is invoked by the real
// normal-session SessionTools.resolve wrapper with no model and no user files.
// The Plugin.Service is stubbed to DISPATCH to the exact guard hook, so this
// does not test OpenCode's plugin discovery/loader or the full prompt loop.
import { expect, test } from "bun:test"
import { Effect, Schema } from "effect"
import fs from "node:fs/promises"
import path from "node:path"
import os from "node:os"
import crypto from "node:crypto"
import { pathToFileURL } from "node:url"
import { SessionTools } from "@/session/tools"
import { Plugin } from "@/plugin"
import { Permission } from "@/permission"
import { ToolRegistry } from "@/tool/registry"
import { MCP } from "@/mcp"
import { Truncate } from "@/tool/truncate"
import { RuntimeFlags } from "@/effect/runtime-flags"

const expected = process.env.DS029_GUARD_SHA256
const file = process.env.DS029_GUARD_FILE

const sha = (b:Uint8Array) => crypto.createHash("sha256").update(b).digest("hex")

test("pinned STARTUP-020 hook blocks synthetic tool in real SessionTools wrapper", async () => {
  if (!file || !expected) throw new Error("Guard filename and pin required")
  const bytes=await fs.readFile(file)
  expect(sha(bytes)).toBe(expected)
  const temp=await fs.mkdtemp(path.join(os.tmpdir(),"ds029-pinned-guard-"))
  const previousConfig=process.env.OPENCODE_CONFIG_DIR
  const previousState=process.env.XDG_STATE_HOME
  process.env.OPENCODE_CONFIG_DIR=path.join(temp,"only-synthetic-config")
  process.env.XDG_STATE_HOME=path.join(temp,"only-synthetic-state")
  let hooks=0
  let body=0
  try {
    await fs.mkdir(process.env.OPENCODE_CONFIG_DIR,{recursive:true})
    const mod=await import(pathToFileURL(file).href)
    const guard=await mod.DonSquadV1StartupGuard({directory:temp})
    const before=guard["tool.execute.before"]
    expect(typeof before).toBe("function")
    const plugin={trigger:(name:string,input:any,output:any) => Effect.promise(async()=>{
      if(name==="tool.execute.before") { hooks++;await before(input,output) }
      return output
    })}
    const registry={tools:()=>Effect.succeed([{
      id:"synthetic_would_mutate",description:"no-op in-memory counter",
      parameters:Schema.Struct({marker:Schema.String}),
      execute:()=>Effect.sync(()=>{
        body++;return {title:"unexpected",output:"unexpected",metadata:{}}
      }),
    }])}
    const service={ask:()=>Effect.die("Synthetic body should not invoke ask")}
    const input:any={
      agent:{name:"don-squad",permission:[{permission:"*",pattern:"*",action:"deny"}]},
      model:{providerID:"test",api:{id:"test-model",npm:"@ai-sdk/openai-compatible"}},
      session:{id:"ses_ds029_pinned",permission:[]},
      processor:{message:{id:"msg_ds029_pinned"},updateToolCall:()=>Effect.void,completeToolCall:()=>Effect.void},
      bypassAgentCheck:false,messages:[],promptOps:{},
    }
    const effect=SessionTools.resolve(input).pipe(
      Effect.provideService(Plugin.Service,plugin as any),
      Effect.provideService(Permission.Service,service as any),
      Effect.provideService(ToolRegistry.Service,registry as any),
      Effect.provideService(MCP.Service,{clients:()=>Effect.succeed({}),tools:()=>Effect.succeed({})} as any),
      Effect.provideService(Truncate.Service,{output:()=>Effect.succeed({content:"",truncated:false})} as any),
      Effect.provideService(RuntimeFlags.Service,{} as any),
    )
    const tools:any=await Effect.runPromise(effect)
    let message=""
    try{
      await tools.synthetic_would_mutate.execute({marker:"synth"},{toolCallId:"ds029",abortSignal:new AbortController().signal})
    }catch(e){message=String(e)}
    expect(message).toContain("Don-Squad critical integrity state")
    expect(hooks).toBe(1)
    expect(body).toBe(0)
    console.log("DS029_C02_PINNED_GUARD_IN_PRODUCTION_WRAPPER_DENIED__NO_MODEL")
  }finally{
    if(previousConfig===undefined)delete process.env.OPENCODE_CONFIG_DIR
    else process.env.OPENCODE_CONFIG_DIR=previousConfig
    if(previousState===undefined)delete process.env.XDG_STATE_HOME
    else process.env.XDG_STATE_HOME=previousState
    await fs.rm(temp,{recursive:true,force:true})
  }
})
