// Router output -> board: remove (locked yes) from top-level tracks/vias (the router input locks
// the carried copper); signal vias reached on one layer only are left for DRC to report.
const fs=require("fs");const [i,o]=process.argv.slice(2);const L=fs.readFileSync(i,"utf8").split(/\r?\n/);let t=false,n=0;
const out=L.filter(l=>{if(/^\t\((segment|via)$/.test(l))t=true;else if(l==="\t)")t=false;if(t&&l==="\t\t(locked yes)"){n++;return false}return true});
fs.writeFileSync(o,out.join("\n"));console.log("unlocked",n);
