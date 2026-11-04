import { Plugin } from "@opencode/plugin/tui";
import fs from "node:fs";import path from "node:path";import os from "node:os";
const root=()=>process.env.XDG_STATE_HOME?path.join(process.env.XDG_STATE_HOME,"don-squad"):path.join(os.homedir(),".local","state","don-squad");
const read=()=>{try{return JSON.parse(fs.readFileSync(path.join(root(),"health.json"),"utf8"))}catch{return {severity:"minor",issues:[]}}};
export default Plugin.define({id:"don-squad.guard.tui",setup(ctx){let last="";const timer=setInterval(()=>{const h=read(),active=(h.issues||[]).filter(x=>x.active),top=active.at(-1);const key=(h.severity||"minor")+":"+(top?.code||"")+":"+(top?.ts||"");if(key!==last&&(h.severity==="medium"||h.severity==="critical")){last=key;ctx.ui.toast.show({message:`Don-Squad ${h.severity.toUpperCase()}: ${top?.message||"guard issue"}`,variant:h.severity==="critical"?"error":"warning"})}},1500);return()=>clearInterval(timer)}});
