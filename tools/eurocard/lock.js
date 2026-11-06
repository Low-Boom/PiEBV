// Camera pass -> second router pass: add (locked yes) to the top-level tracks/vias of the nets whose
// name matches the regex, so the "*" pass routes around them and does not rip or re-route them.
// usage: node lock.js in.kicad_pcb out.kicad_pcb "^(Sync|Trigger|TDRSTN)[1-6]$"
const fs=require("fs");const [i,o,rx]=process.argv.slice(2);const R=new RegExp(rx);let n=0;
const s=fs.readFileSync(i,"utf8").replace(/(?<=\n)\t\((segment|via)(\r?\n)([\s\S]*?)\t\)(\r?\n)/g,(m,t,nl,body,nl2)=>{
  const net=(body.match(/\(net "([^"]*)"\)/)||[])[1]||"";
  if(!R.test(net)||/\(locked yes\)/.test(body))return m;n++;return "\t("+t+nl+"\t\t(locked yes)"+nl+body+"\t)"+nl2});
fs.writeFileSync(o,s);console.log("locked",n);
