import http from 'node:http';
import { readFile } from 'node:fs/promises';
const files=new Map([
 ['/','preview/index.html'],['/preview/','preview/index.html'],
 ['/tests/fixtures.mjs','tests/fixtures.mjs'],
 ['/custom_components/budget_manager/frontend/budget-manager-panel.js','custom_components/budget_manager/frontend/budget-manager-panel.js'],
]);
http.createServer(async(req,res)=>{
 const path=files.get(new URL(req.url,'http://localhost').pathname);
 if(!path){res.writeHead(404);res.end();return;}
 try{const data=await readFile(new URL(`../${path}`,import.meta.url));res.writeHead(200,{'Content-Type':path.endsWith('html')?'text/html':'text/javascript','Cache-Control':'no-store'});res.end(data);}catch{res.writeHead(500);res.end('Preview unavailable');}
}).listen(8788,'127.0.0.1',()=>console.log('Synthetic Budget preview: http://127.0.0.1:8788/'));
