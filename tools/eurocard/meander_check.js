// Gate: same-net copper short-cuts on 2-pad matched nets (merged or too-close meander arms).
// Samples every track at 0.05 mm; D = centre-line distance from the net's first pad. Two same-layer samples
// closer than (width + CLR) with |D1 - D2| > SKIP mean the signal can bypass that much track.
// usage: node meander_check.js board.kicad_pcb [CLR=0.2] [SKIP=2] prefix...   exit 1 on any hit
const fs=require("fs");const a=process.argv.slice(2);const file=a.shift();const num=x=>/^[\d.]+$/.test(x);
const CLR=num(a[0])?+a.shift():0.2,SKIP=num(a[0])?+a.shift():2,pf=a;const s=fs.readFileSync(file,"utf8");
const pads={};                                              // net -> [[x,y],...] absolute pad centres
for(const fp of s.split(/\n\t\(footprint /).slice(1)){const at=fp.match(/\n\t\t\(at ([\d.-]+) ([\d.-]+)(?: ([\d.-]+))?\)/);const X=+at[1],Y=+at[2],fa=+(at[3]||0)*Math.PI/180;
 for(const blk of fp.split(/\n\t\t\(pad /).slice(1)){const p=blk.match(/^"[^"]*" \w+ \w+\s*\(at ([\d.-]+) ([\d.-]+)/);const n=(blk.match(/\(net "([^"]*)"\)/)||[])[1];if(!p||!n)continue;
  (pads[n]=pads[n]||[]).push([X+(+p[1])*Math.cos(fa)+(+p[2])*Math.sin(fa),Y-(+p[1])*Math.sin(fa)+(+p[2])*Math.cos(fa)])}}
const items=[...s.matchAll(/\t\((segment|via)\r?\n([\s\S]*?)\t\)\r?\n/g)].map(m=>{const b=m[2];return{t:m[1],n:(b.match(/\(net "([^"]*)"\)/)||[])[1],l:(b.match(/\(layer "([^"]*)"\)/)||[])[1],w:+(b.match(/\(width ([\d.]+)\)/)||[0,0])[1],xy:[...b.matchAll(/\((?:start|end|at) ([\d.-]+) ([\d.-]+)\)/g)].map(q=>[+q[1],+q[2]])}});
let fail=0;
for(const net of Object.keys(pads).filter(n=>pf.some(p=>n.startsWith(p))).sort()){const S=pads[net][0];
 const segs=items.filter(t=>t.n===net&&t.t==="segment"),vias=items.filter(t=>t.n===net&&t.t==="via");const pts=[],adj=[];
 const link=(i,j,w)=>{(adj[i]=adj[i]||[]).push([j,w]);(adj[j]=adj[j]||[]).push([i,w])};
 for(const g of segs){const [p,q]=g.xy;const L=Math.hypot(q[0]-p[0],q[1]-p[1]);const k=Math.max(1,Math.ceil(L/0.05));const i0=pts.length;
  for(let j=0;j<=k;j++)pts.push({x:p[0]+(q[0]-p[0])*j/k,y:p[1]+(q[1]-p[1])*j/k,l:g.l,w:g.w});for(let j=0;j<k;j++)link(i0+j,i0+j+1,L/k)}
 const H={},key=(x,y)=>Math.floor(x/0.5)+","+Math.floor(y/0.5);pts.forEach((p,i)=>(H[key(p.x,p.y)]=H[key(p.x,p.y)]||[]).push(i));
 const near=(x,y,r,skip)=>{const gx=Math.floor(x/0.5),gy=Math.floor(y/0.5),o=[];for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++)for(const j of H[(gx+dx)+","+(gy+dy)]||[])if(j!==skip&&Math.hypot(pts[j].x-x,pts[j].y-y)<r)o.push(j);return o};
 pts.forEach((p,i)=>{for(const j of near(p.x,p.y,0.011,i))if(pts[j].l===p.l)link(i,j,0)});          // shared ends, T-joins
 for(const v of vias){const id=pts.length;pts.push({x:v.xy[0][0],y:v.xy[0][1],l:"via"});for(const j of near(v.xy[0][0],v.xy[0][1],0.31,id))link(id,j,0)}
 const D=new Float64Array(pts.length).fill(1e9),Q=[];pts.forEach((p,i)=>{if(Math.hypot(p.x-S[0],p.y-S[1])<1.0){D[i]=0;Q.push(i)}});
 while(Q.length){let b=0;for(let k=1;k<Q.length;k++)if(D[Q[k]]<D[Q[b]])b=k;const u=Q.splice(b,1)[0];for(const [v,w] of adj[u]||[])if(D[u]+w<D[v]-1e-9){D[v]=D[u]+w;Q.push(v)}}
 let bad=0,skip=0;pts.forEach((p,i)=>{if(p.l==="via"||D[i]>1e8)return;let hit=false;
  for(const j of near(p.x,p.y,p.w+CLR,i))if(pts[j].l===p.l&&D[j]<1e8&&Math.abs(D[i]-D[j])>SKIP){hit=true;skip=Math.max(skip,Math.abs(D[i]-D[j]))}if(hit)bad++});
 if(bad){fail++;console.log(`FAIL ${net}: ${(bad*0.05).toFixed(1)} mm of track edge gap under ${CLR} mm to its own copper ${SKIP}+ mm further along (largest bypass ${skip.toFixed(1)} mm)`)}}
console.log(fail?`meander_check: ${fail} net(s) fail`:"meander_check: ok");process.exit(fail?1:0);
