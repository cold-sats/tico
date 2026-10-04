import * as THREE from '../vendor/three/three.module.min.js';
import { RoundedBoxGeometry } from '../vendor/three/RoundedBoxGeometry.js';
import { mergeGeometries } from '../vendor/three/BufferGeometryUtils.js';

export function createBuilding(data, preferences = {}, openMember = () => {}) {
const controller = new AbortController();
const on = (target, type, fn, options = {}) => target.addEventListener(type, fn, {...options, signal: controller.signal});
const resources = new Set(), mats = new Map(), geos = new Map();
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const palettes = [
  {color:0x79c9b3,rug:0x819d8a,wall:0xdceadd}, {color:0xf0c786,rug:0xada17d,wall:0xeee4cc},
  {color:0xaca5d3,rug:0x9b92b3,wall:0xe4e0ed}, {color:0x8fbcd8,rug:0x8ca8b6,wall:0xd9e9ec}
];
const columns = innerWidth<560 ? Math.min(2,Math.ceil(Math.sqrt(data.groups.length/2))) : Math.min(3, Math.ceil(Math.sqrt(data.groups.length))), rows = Math.ceil(data.groups.length / columns);
const BUILDINGS = data.groups.map((group, id) => ({...group, ...palettes[id % 4], id,
  x: ((id % columns) - (columns - 1)/2)*18, z: (Math.floor(id/columns) - (rows-1)/2)*17,
  levels: Math.max(1, Math.ceil(group.members.length/6))}));
const campusWidth = columns*18, campusDepth = rows*17, maxHeight = Math.max(...BUILDINGS.map(b=>b.levels))*3.5+3;
const state = {floor:null,t:0,hover:null,selected:null,zoom:1,yaw:.36,pitch:.42,drag:false};
const renderer = new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});
renderer.setPixelRatio(Math.min(devicePixelRatio,innerWidth < 600 ? 1.4 : 1.6)); renderer.setSize(innerWidth,innerHeight);
renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFShadowMap;
renderer.shadowMap.autoUpdate=false; renderer.shadowMap.needsUpdate=true;
renderer.outputColorSpace=THREE.SRGBColorSpace; renderer.toneMapping=THREE.ACESFilmicToneMapping; renderer.toneMappingExposure=1.35;
$('#world').replaceChildren(renderer.domElement);
renderer.domElement.setAttribute('aria-label','Solarpunk campus. Each computer is a building with its bots and human collaborators.');
renderer.domElement.setAttribute('role','img'); renderer.domElement.setAttribute('aria-describedby','scene-instructions');
const scene=new THREE.Scene(); scene.background=new THREE.Color(0x142d35); scene.fog=new THREE.FogExp2(0x142d35,.0018);
const camera=new THREE.OrthographicCamera(-20,20,15,-15,.1,1000);
let currentTarget=new THREE.Vector3(0,3,0), currentPosition=new THREE.Vector3(22,28,55), currentScale=40;
const hemi=new THREE.HemisphereLight(0xc3e6ea,0x638f76,1.6); scene.add(hemi);
const sun=new THREE.DirectionalLight(0xffe9bf,2.4); sun.position.set(-20,40,30); sun.castShadow=true;
sun.shadow.mapSize.set(2048,2048); const shadowSize=Math.max(campusWidth,campusDepth,maxHeight)+15;
Object.assign(sun.shadow.camera,{left:-shadowSize,right:shadowSize,top:shadowSize,bottom:-shadowSize,near:.1,far:180});
sun.shadow.normalBias=.045; sun.shadow.bias=-.00015; sun.shadow.radius=3; scene.add(sun);
const fill=new THREE.DirectionalLight(0x92b8ec,1.25); fill.position.set(14,18,-14); scene.add(fill);
const world=new THREE.Group(), landscape=new THREE.Group(), tunnels=new THREE.Group(); scene.add(world); world.add(landscape,tunnels);
const characters=[], emissives=[], buildingGroups=[], hitMeshes=[], hoverFrames=[], pods=[];
function material(color,opts={}){const key=String(color)+JSON.stringify(opts);if(!mats.has(key))mats.set(key,new THREE.MeshStandardMaterial({color,roughness:.78,metalness:0,...opts}));return mats.get(key);}
function mesh(g,geo,mat,x,y,z,shadow=true){const m=new THREE.Mesh(geo,typeof mat==='number'||typeof mat==='string'?material(mat):mat);m.position.set(x,y,z);m.castShadow=shadow;m.receiveShadow=true;g.add(m);resources.add(geo);resources.add(m.material);if(m.material.map)resources.add(m.material.map);return m;}
function box(g,x,y,z,w,h,d,c,r=.04){const key=`b:${w}:${h}:${d}:${r}`;if(!geos.has(key))geos.set(key,r?new RoundedBoxGeometry(w,h,d,2,Math.min(r,w/3,h/3,d/3)):new THREE.BoxGeometry(w,h,d));return mesh(g,geos.get(key),c,x,y,z);}
function ball(g,x,y,z,r,c,scale){const key='ball';if(!geos.has(key))geos.set(key,new THREE.SphereGeometry(1,16,12));const m=mesh(g,geos.get(key),c,x,y,z);m.scale.set(r*(scale?.[0]||1),r*(scale?.[1]||1),r*(scale?.[2]||1));return m;}
function cyl(g,x,y,z,rt,rb,h,c,sides=20){const key=`c:${rt}:${rb}:${h}:${sides}`;if(!geos.has(key))geos.set(key,new THREE.CylinderGeometry(rt,rb,h,sides));return mesh(g,geos.get(key),c,x,y,z);}
function rod(g,a,b,r,c){const aa=new THREE.Vector3(...a),bb=new THREE.Vector3(...b),v=bb.clone().sub(aa);const m=cyl(g,...aa.clone().add(bb).multiplyScalar(.5).toArray(),r,r,v.length(),c,8);m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),v.normalize());return m;}
function textTexture(label,fg='#49635b',bg=null,font=70,w=768,h=192){const cv=document.createElement('canvas');cv.width=w;cv.height=h;const ctx=cv.getContext('2d');if(bg){ctx.fillStyle=bg;ctx.fillRect(0,0,w,h);}ctx.fillStyle=fg;ctx.font=`600 ${font}px -apple-system, BlinkMacSystemFont, sans-serif`;while(ctx.measureText(label).width>w-60&&font>12){font--;ctx.font=`600 ${font}px -apple-system, BlinkMacSystemFont, sans-serif`;}ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(label,w/2,h/2);const t=new THREE.CanvasTexture(cv);t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=4;return t;}
function sign(g,label,x,y,z,w,h,fg,bg){const th=Math.max(64,Math.round(1536*h/w));const tex=textTexture(label,fg,bg,Math.round(th*.7),1536,th);const m=mesh(g,new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:tex,transparent:true,depthWrite:false}),x,y,z,false);return m;}
function glowing(c,intensity=.4){const m=material(c,{emissive:c,emissiveIntensity:intensity});if(!emissives.includes(m))emissives.push(m);return m;}
function plant(g,x,y,z,size=1,pot=0xc5a88b){const p=new THREE.Group();p.position.set(x,y,z);p.scale.setScalar(size);g.add(p);cyl(p,0,.22,0,.25,.2,.44,pot);cyl(p,0,.45,0,.25,.25,.08,pot);cyl(p,0,.47,0,.2,.2,.03,0x675c48);rod(p,[0,.45,0],[0,1.15,0],.025,0x768565);for(let i=0;i<7;i++){const t=i*2.4,yy=.65+(i%3)*.2;const l=ball(p,Math.cos(t)*.19,yy,Math.sin(t)*.19,.23,[0x8fae75,0x72995f,0xa2b986][i%3],[.6,1.7,.7]);l.rotation.z=Math.sin(t)*.65;l.rotation.x=Math.cos(t)*.7;}return p;}
function tree(g,x,y,z,s=1){const t=new THREE.Group();g.add(t);t.position.set(x,y,z);t.scale.setScalar(s);cyl(t,0,1,0,.12,.18,2,0x9b8268,8);rod(t,[0,1.1,0],[.5,1.85,.15],.07,0x9b8268);rod(t,[0,1.2,0],[-.4,1.9,-.1],.06,0x9b8268);ball(t,0,2.25,0,.84,0x93b187,[1,1.3,1]);ball(t,.5,2.08,.13,.55,0xaac59a);ball(t,-.4,2.18,-.1,.64,0x85a779);ball(t,.12,2.95,-.1,.56,0xa9c396);return t;}
function screen(g,x,y,z,w=1.02,angle=0){const s=new THREE.Group();s.position.set(x,y,z);s.rotation.y=angle;g.add(s);box(s,0,0,0,w,.68,.1,0x466366,.06);box(s,0,.015,.058,w-.1,.56,.015,glowing(0xb4d9c5,.28),.02);for(let r=0;r<5;r++){const width=.2+(r*7%4)*.12;box(s,-w*.35+width/2,.18-r*.077,.073,width,.025,.008,r%2?0x77aca8:0x6a9791,0);}box(s,0,-.39,0,.075,.17,.075,0x687f78);box(s,0,-.48,.06,.4,.05,.3,0x91a196);return s;}
function mug(g,x,y,z,c=0xdda57e){cyl(g,x,y+.095,z,.095,.085,.19,c);cyl(g,x,y+.194,z,.074,.074,.009,0x6a4e3c);const tor=new THREE.TorusGeometry(.071,.021,6,10);const m=mesh(g,tor,c,x+.095,y+.11,z);m.rotation.y=Math.PI/2;}
function desk(g,x,z,c=0xe6d1b0,dual=false){const d=new THREE.Group();d.position.set(x,0,z);g.add(d);box(d,0,1.03,0,2.5,.16,1.25,c,.08);for(const xx of [-1.02,1.02])for(const zz of [-.42,.42])box(d,xx,.48,zz,.09,1,.09,0xc0b69b,.02);screen(d,dual?-.56:0,1.62,-.25,dual?.87:1.02);if(dual)screen(d,.49,1.62,-.25,.87,-.07);box(d,0,1.133,.25,.68,.045,.23,0xc4d2bc,.025);for(let j=0;j<3;j++)box(d,-.27+j*.19,1.16,.25,.12,.008,.12,0xa5b69e,.004);box(d,.59,1.13,.25,.12,.06,.18,0xa8b6a1,.04);mug(d,.97,1.13,-.06);return d;}
function couch(g,x,z,c,angle=0){const co=new THREE.Group();co.position.set(x,0,z);co.rotation.y=angle;g.add(co);box(co,0,.34,0,2.55,.47,1,c,.15);box(co,0,.83,-.4,2.6,.86,.26,c,.1);for(const xx of [-1.15,1.15])box(co,xx,.69,0,.28,.68,1.08,c,.09);for(const xx of [-.64,.05,.7])box(co,xx,.61,.04,.6,.16,.72,0xe3d9be,.07);return co;}
function character(g,data,x,z,floor,index){
  const {id:actorId,name,type,state:activity,detail:message,href}=data; const color=type==='human'?0xd1ae8a:palettes[floor%4].color,root=new THREE.Group();root.position.set(x,.28,z);root.scale.setScalar(1.14);g.add(root);
  const ch={actorId,href,activity,root,name,type,color,message,floor,index,home:new THREE.Vector3(x,.28,z),wave:0,head:null,arm:null};
  const c=new THREE.Group();root.add(c);ch.body=c;
  if(type==='bot'){
    cyl(c,0,.15,0,.22,.25,.22,0x546f6c);box(c,0,.46,0,.51,.46,.4,color,.15);box(c,0,.94,0,.66,.54,.51,color,.18);
    box(c,0,.95,.242,.51,.32,.035,0x29474d,.1);
    for(const xx of [-.13,.13])box(c,xx,.98,.269,.077,.095,.02,glowing(0xc4f5d8,.7),.028);
    box(c,0,.86,.27,.115,.024,.013,0xb0e4d0,.01);
    rod(c,[0,1.2,0],[0,1.36,0],.023,0x688d80);ball(c,0,1.39,0,.048,glowing(0xf0c98d,.5));
    for(const xx of [-.3,.3]){const a=box(c,xx,.5,0,.11,.31,.14,color,.05);if(xx>.2)ch.arm=a;}
    box(c,0,.49,.213,.14,.055,.01,0xe5e6c7,.02);ch.head=c;
  }else{
    for(const xx of [-.13,.13]){box(c,xx,.24,0,.17,.43,.2,0x536e6e,.06);box(c,xx,.085,.06,.2,.14,.32,0xe6dcc1,.055);}
    box(c,0,.66,0,.51,.54,.31,color,.12);cyl(c,0,.99,0,.1,.1,.15,0xe2b594);
    const head=new THREE.Group();head.position.y=1.19;c.add(head);ball(head,0,0,0,.255,0xe2b594,[.9,1.1,.9]);
    ball(head,0,.13,-.055,.238,floor===1?0x855f46:floor===2?0x514b42:0x655144,[1,.8,1]);
    for(const xx of [-.075,.075])ball(head,xx,.008,.21,.018,0x354c47);ch.head=head;
    for(const xx of [-.34,.34]){const a=new THREE.Group();a.position.set(xx,.83,0);c.add(a);box(a,0,-.14,0,.14,.33,.16,color,.05);ball(a,0,-.34,0,.087,0xe2b594);if(xx>.2)ch.arm=a;}
  }
  const halo=mesh(root,new THREE.RingGeometry(.38,.43,32),new THREE.MeshBasicMaterial({color:0xf5d39c,side:THREE.DoubleSide,transparent:true,opacity:0}),0,.022,0,false);halo.rotation.x=-Math.PI/2;ch.halo=halo;
  root.traverse(o=>{if(o.isMesh)o.userData.character=ch;});characters.push(ch);return ch;
}


// A cutaway island makes the below-ground Loop visible without hiding the offices.
box(landscape,0,-1.15,0,campusWidth+2,1.15,campusDepth+1,0x394f4e,.6);
box(landscape,0,-1.77,0,campusWidth+1.2,.18,campusDepth+.2,0x203f40,.15);
const ground=mesh(scene,new THREE.PlaneGeometry(2000,2000),new THREE.MeshBasicMaterial({color:0x142d35,toneMapped:false}),0,-1.88,0,false);
ground.rotation.x=-Math.PI/2;
const groundShadow=mesh(scene,new THREE.PlaneGeometry(2000,2000),new THREE.ShadowMaterial({opacity:.18}),0,-1.87,0,false); groundShadow.rotation.x=-Math.PI/2;

function solarGarden(roof,b) {
  box(roof,0,0,-2.65,12.6,.24,3.1,0xdbe6d6,.12);
  box(roof,0,.15,-2.65,12.1,.08,2.7,0x8baf81,.12);
  for(const x of [-6,6])box(roof,x,.35,-2.65,.22,.36,3,0xd8e4cf,.035);
  box(roof,0,.35,-4,12.2,.36,.22,0xd8e4cf);
  // The rear terrace leaves the front roof cut away, so every floor remains visible.
  for(const x of [-4.8,.5])for(const z of [-3.6,-1.5])box(roof,x,1.2,z,.1,2.05,.1,0xa5c3b1,.02);
  for(let j=0;j<2;j++) {
    const z=-3.22+j*1.12;
    box(roof,-2.15,2.25,z,5.6,.12,.93,material(0x285b69,{metalness:.45,roughness:.28}),.04);
    for(let k=0;k<6;k++)box(roof,-4.45+k*.93,2.32,z,.018,.012,.86,0x65a6aa,0);
  }
  for(const z of [-3.25,-1.85]) {
    box(roof,3.25,.32,z,3.3,.35,.72,0xb6c8a0,.1);
    for(let j=0;j<6;j++)ball(roof,2+j*.5,.65,z,.29,j%2?0x9fc283:0x78aa7b,[1,.65,1]);
  }
  tree(roof,5.1,.22,-2.5,.58); plant(roof,1.3,.22,-2.5,.75);
  box(roof,-2.15,.65,-1.5,2.7,.12,.4,0xd2b78c);
  for(const x of [-3.2,-1.1])box(roof,x,.4,-1.5,.1,.65,.4,0x91aa91);
  // Fine mint roof trim gives the complex its futuristic outline.
  box(roof,0,.18,-1.07,12.45,.045,.06,glowing(b.color,.75),.02);
}
for(const b of BUILDINGS) {
  const island=new THREE.Group(); landscape.add(island); island.position.set(b.x,0,b.z);
  box(island,0,-.13,0,15.8,.95,12.2,0x9ab38c,.4);
  box(island,0,.38,0,15.3,.08,11.7,0x73966e,.25);
  box(island,0,.44,.1,13.3,.11,9.6,0xcedac5,.17);
  for(const x of [-7.15,7.15]) {
    tree(island,x,.42,-3.3,.82); tree(island,x,.42,2.1,.63);
    box(island,x,.57,-.1,.6,.18,3.1,0x8daf7c,.16);
    for(const z of [-1,0,1])ball(island,x,.78,z,.29,0xacbe85,[1,.65,1]);
  }
  // A small entry plaza and two lamps, with paths leading into the tunnel portal.
  box(island,0,.49,4.8,4.2,.12,1.5,0xd7ddc8,.08);
  for(const x of [-2.6,2.6]) {
    cyl(island,x,1.25,5,.04,.06,1.6,0x618879,8);
    ball(island,x,2.07,5,.15,glowing(0xf9dca5,.85));
  }
  const group=new THREE.Group(); group.position.set(b.x,.65,b.z); world.add(group); b.room=group; buildingGroups.push(group);
  const roofs = b.roof=new THREE.Group(); roofs.position.y=b.levels*3.5; group.add(roofs); solarGarden(roofs,b);
  for(let level=0;level<b.levels;level++) {
    const floor=new THREE.Group(); floor.position.y=level*3.5; group.add(floor);
    box(floor,0,0,0,12.5,.3,8.3,0xdde4d3,.1);
    box(floor,0,.19,0,12,.08,7.9,0xd9c8a5,.035);
    for(let j=0;j<12;j++)box(floor,-5.7+j*1.03,.237,0,.013,.008,7.7,0xbfb794,0);
    box(floor,0,1.8,-3.95,12.3,3.3,.18,b.wall,.06);
    box(floor,-6.12,1.78,0,.16,3.3,8.1,0xc7d9c7,.035);
    // Broad rear windows and a glass side wall frame the open cutaway.
    for(const x of [-3.8,0,3.8]) {
      box(floor,x,1.95,-3.81,2.7,1.6,.06,0x578c87,.025);
      box(floor,x,1.95,-3.77,2.57,1.46,.012,glowing(0x82b7ab,.24),.015);
      box(floor,x,1.95,-3.73,.035,1.47,.03,0xa8c7b4,0);
    }
    box(floor,6.12,1.65,0,.06,3.1,7.8,material(0x90c8bd,{transparent:true,opacity:.12,depthWrite:false}),.02);
    for(const x of [-6.1,6.1])for(const z of [-3.9,3.9])box(floor,x,1.76,z,.16,3.5,.16,0xbdcfb9,.02);
    box(floor,0,3.45,4.05,12.4,.16,.16,0xc8d8c2);
    box(floor,0,.18,4.13,12.35,.06,.07,glowing(b.color,.6),.02);
    box(floor,0,.248,.2,10.7,.012,6.2,b.rug,.12);
    plant(floor,-5.46,.26,2.85,.7); plant(floor,5.55,.26,-2.7,.85);
    // Every identity has a workstation. No representative sampling or fabricated teammates.
    const occupants=b.members.slice(level*6,(level+1)*6);
    occupants.forEach((member,index)=>{
      const x=-3.65+(index%3)*3.65, z=index<3?1.65:-1.75;
      const work=new THREE.Group(); floor.add(work); work.position.set(x,.25,z); work.scale.setScalar(.83);
      desk(work,0,0,member.type==='human'?0xdbc19a:0xc5d8bf);
      const ch=character(floor,member,x+.62,z+.86,b.id,level*6+index); ch.root.scale.setScalar(.95);
      ch.root.rotation.y=-.22;
    });
    if(!occupants.length) {
      couch(floor,0,1,0x98bda8); plant(floor,-2.3,.25,1,.9);
      sign(floor,'Ready for your bots',0,2.8,-3.68,5,.5,'#efead5');
    }
    const pl=new THREE.PointLight(0xffdba8,9,13,2); pl.position.set(0,2.9,1.3); floor.add(pl);
  }
  // The machine name is part of the architecture and stays legible in the campus view.
  box(group,0,.39,4.45,10.7,.77,.12,0x264b4c,.08);
  sign(group,b.name,0,.51,4.53,9.7,.43,'#f3e6be');
  const subtitle=b.kind==='computer'?'COMPUTER  /  '+b.members.filter(m=>m.type==='bot').length+' BOTS':'SHARED SPACE';
  sign(group,subtitle,0,.16,4.54,4.8,.16,'#83c8b5');
  const hit=box(group,0,b.levels*1.75,0,12.4,b.levels*3.5,8.1,material(0xffffff,{transparent:true,opacity:0,depthWrite:false}),0);
  hit.userData.pickFloor=b.id; hit.userData.keep=true; hit.castShadow=false; hit.receiveShadow=false; hitMeshes.push(hit);
  const outline=mesh(group,new THREE.BoxGeometry(12.7,.045,8.5),new THREE.MeshBasicMaterial({color:b.color,transparent:true,opacity:0}),0,.25,0,false);
  outline.userData.keep=true; hoverFrames.push(outline);
  // Recessed Loop entrance: two illuminated arches reveal the underground connection.
  for(const z of [5.05,6.15]) {
    const ring=mesh(island,new THREE.TorusGeometry(.73,.1,6,24,Math.PI),0xd7e3ca,0,.12,z);
    const glow=mesh(island,new THREE.TorusGeometry(.62,.023,6,24,Math.PI),glowing(b.color,1.1),0,.12,z+.015,false);
    ring.userData.keep=true; glow.userData.keep=true;
  }
  box(island,0,-.44,5.55,1.4,.15,2.5,0x223f42,.05);
}
// A visible cutaway Loop joins the portals. Pods are scenery, not reported bot traffic.
for(let i=1;i<BUILDINGS.length;i++) {
  const a=BUILDINGS[i-1],b=BUILDINGS[i];
  const sameRow=a.z===b.z;
  const points=sameRow ? [new THREE.Vector3(a.x,.18,a.z+6.15),new THREE.Vector3(a.x,.02,a.z+7.15),new THREE.Vector3(b.x,.02,b.z+7.15),new THREE.Vector3(b.x,.18,b.z+6.15)]
    : [new THREE.Vector3(a.x,.18,a.z+6.15),new THREE.Vector3(a.x+8.5,.02,a.z+7),new THREE.Vector3(campusWidth/2+.3,.02,a.z+7),new THREE.Vector3(campusWidth/2+.3,.02,b.z+7),new THREE.Vector3(b.x,.02,b.z+7),new THREE.Vector3(b.x,.18,b.z+6.15)];
  const curve=new THREE.CatmullRomCurve3(points,false,'catmullrom',.12);
  mesh(tunnels,new THREE.TubeGeometry(curve,72,.68,12,false),material(0x9bcab8,{transparent:true,opacity:.18,depthWrite:false,side:THREE.DoubleSide,roughness:.25}),0,0,0,false);
  for(const side of [-.42,.42]) {
    const rail=new THREE.CatmullRomCurve3(points.map(p=>p.clone().add(new THREE.Vector3(0,-.18,side))),false,'catmullrom',.12);
    mesh(tunnels,new THREE.TubeGeometry(rail,72,.022,5,false),glowing(0x74e2ca,1.25),0,0,0,false);
  }
  for(const point of points.slice(1,-1)) {
    const ring=mesh(tunnels,new THREE.TorusGeometry(.7,.06,6,20),0x89aa98,point.x,point.y,point.z);
    ring.rotation.y=Math.PI/2;
  }
  const pod=new THREE.Group(); tunnels.add(pod);
  box(pod,0,0,0,.62,.48,1.05,0xebdbc0,.18); box(pod,0,.16,.06,.5,.26,.61,0x37575e,.11);
  box(pod,0,-.12,.5,.4,.04,.02,glowing(0xbef8dc,1.2),.01);
  pods.push({root:pod,curve,phase:i*.29});
}
// Merge opaque static scenery by material; keep characters, glass and pods independent.
function batchStatic(root) {
  root.updateWorldMatrix(true,true);
  const inverse=root.matrixWorld.clone().invert(), batches=new Map(), originals=[];
  root.traverse(o=>{
    if(!o.isMesh||o.userData.character||o.userData.keep||o.material.transparent)return;
    const key=o.material.uuid+':'+o.castShadow;
    if(!batches.has(key))batches.set(key,{material:o.material,cast:o.castShadow,geos:[]});
    const geo=o.geometry.index?o.geometry.toNonIndexed():o.geometry.clone();
    geo.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inverse,o.matrixWorld));
    batches.get(key).geos.push(geo); originals.push(o);
  });
  for(const b of batches.values()) {
    const geo=mergeGeometries(b.geos,false); if(!geo)continue;
    const m=new THREE.Mesh(geo,b.material);m.castShadow=b.cast;m.receiveShadow=true;root.add(m);resources.add(geo);
    b.geos.forEach(g=>g.dispose());
  }
  originals.forEach(o=>o.removeFromParent());
}
// Roofs must remain removable when entering a building.
for(const b of BUILDINGS){batchStatic(b.roof);b.roof.userData.keep=true;}
// Do not batch roofs into the room, since each roof has its own visibility lifecycle.
for(const b of BUILDINGS){b.room.remove(b.roof);batchStatic(b.room);b.room.add(b.roof);}
batchStatic(landscape);

const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
function desiredCamera() {
  const aspect=innerWidth/innerHeight,small=innerWidth<560;
  let target,scale;
  if(state.floor===null) {
    target=new THREE.Vector3(0,maxHeight*.3,0);
    const width=campusWidth*Math.cos(state.yaw)+campusDepth*Math.abs(Math.sin(state.yaw))+7;
    const height=maxHeight*Math.cos(state.pitch)+campusDepth*Math.sin(state.pitch)+9;
    scale=Math.max(height,width/aspect)*(small?1.1:1.03)/state.zoom;
  } else {
    const b=BUILDINGS[state.floor];target=new THREE.Vector3(b.x,b.levels*1.75+.3,b.z);
    scale=Math.max(b.levels*3.5+5,(small?16.5:19)/aspect)/state.zoom;
  }
  const distance=Math.max(80,campusWidth+campusDepth+maxHeight);
  return {target,scale,position:target.clone().add(new THREE.Vector3(Math.sin(state.yaw)*Math.cos(state.pitch)*distance,Math.sin(state.pitch)*distance,Math.cos(state.yaw)*Math.cos(state.pitch)*distance))};
}
function updateCamera(dt) {
  const desired=desiredCamera(),lerp=reduced.matches?1:1-Math.exp(-dt*5.2);
  currentTarget.lerp(desired.target,lerp);currentPosition.lerp(desired.position,lerp);currentScale=THREE.MathUtils.lerp(currentScale,desired.scale,lerp);
  camera.position.copy(currentPosition);camera.lookAt(currentTarget);
  const aspect=innerWidth/innerHeight;camera.left=-currentScale*aspect/2;camera.right=currentScale*aspect/2;camera.top=currentScale/2;camera.bottom=-currentScale/2;camera.updateProjectionMatrix();
}
function project(v) {const p=v.clone().project(camera);return {x:(p.x+1)*innerWidth/2,y:(1-p.y)*innerHeight/2};}
$('#floors').replaceChildren();
for(const b of BUILDINGS) {
  const button=document.createElement('button');button.className='scene-access';button.dataset.floor=b.id;button.dataset.computer=b.key;
  button.textContent=b.name;button.setAttribute('aria-label',b.name+', '+b.members.length+' teammates');$('#floors').append(button);
}
function memberLabels() {
  $('#people').replaceChildren();
  for(const ch of characters.filter(c=>c.floor===state.floor)) {
    const button=document.createElement('button');button.className='scene-access';button.dataset.person=ch.actorId;button.dataset.state=ch.activity;button.textContent=ch.name;
    button.setAttribute('aria-label',ch.name+' · '+ch.message);button.onclick=()=>sayHi(ch);$('#people').append(button);
  }
}
function setHover(id) {state.hover=id;$$('[data-floor]').forEach(b=>b.classList.toggle('hovered',Number(b.dataset.floor)===id));}
function closeSpeech() {state.selected=null;$('#speech').hidden=true;}
function subtitle(b) {return b.members.filter(m=>m.type==='human').length+' people · '+b.members.filter(m=>m.type==='bot').length+' bots · '+b.members.filter(m=>m.state==='running').length+' running';}
function setFloor(id) {
  state.floor=id;state.zoom=1;state.yaw=id===null?(innerWidth<560?.14:.36):.08;state.pitch=id===null?(innerWidth<560?.58:.32):.24;
  setHover(null);closeSpeech();$('#hover-label').hidden=true;
  $('#floors').hidden=id!==null;$('#floor-heading').hidden=id===null;$('#back').hidden=id===null;$('#people').hidden=id===null;
  document.body.classList.toggle('inside',id!==null);memberLabels();
  $('#campus-hint').textContent=id===null?'Select a building to step inside':'Select a teammate · Drag to look around';
  if(id!==null) {
    const b=BUILDINGS[id];$('#floor-title').textContent=b.name;$('#floor-number').textContent=b.kind==='computer'?'Computer':'Shared space';$('#floor-subtitle').textContent=subtitle(b);
  }
  buildingGroups.forEach((g,i)=>g.visible=id===null||i===id);
  BUILDINGS.forEach(b=>b.roof.visible=id===null);
  landscape.visible=id===null;tunnels.visible=id===null;
  ground.position.y=id===null?-1.88:.28;groundShadow.position.y=ground.position.y+.01;
  renderer.shadowMap.needsUpdate=true;preferences.floorId=id===null?null:BUILDINGS[id].key;
}
$$('[data-floor]').forEach(b=>{b.onclick=()=>setFloor(+b.dataset.floor);b.onpointerenter=()=>setHover(+b.dataset.floor);b.onpointerleave=()=>setHover(null);b.onfocus=()=>setHover(+b.dataset.floor);b.onblur=()=>setHover(null);});
$('#back').onclick=()=>{const id=state.floor;setFloor(null);$(`[data-floor="${id}"]`)?.focus();};
function sayHi(ch) {
  if(state.floor!==ch.floor)setFloor(ch.floor);
  state.selected=ch;ch.wave=3;$('#speech-type').textContent=(ch.type==='human'?'Person':'Bot')+' · '+BUILDINGS[ch.floor].name;
  $('#speech-name').textContent=ch.name;$('#speech-message').textContent=ch.type==='human'?'Works with bots on this computer. Presence is not tracked.':(!data.fresh?'Status is unavailable. Reconnecting…':ch.message);
  if(BUILDINGS[ch.floor].kind==='commons'&&ch.type==='human')$('#speech-message').textContent='Human teammate. Presence is not tracked.';
  $('#speech-open').hidden=!ch.href;$('#speech-open').onclick=()=>openMember(ch.actorId);$('#speech').hidden=false;
}
$('#speech-close').onclick=closeSpeech;
function pick(ev) {
  pointer.set(ev.clientX/innerWidth*2-1,-ev.clientY/innerHeight*2+1);raycaster.setFromCamera(pointer,camera);
  if(state.floor===null) {
    const hits=raycaster.intersectObjects(hitMeshes,false);return hits.length?{floor:hits[0].object.userData.pickFloor}:null;
  }
  const hits=raycaster.intersectObjects(buildingGroups[state.floor].children,true);
  for(const hit of hits) {
    if(hit.object.userData.character)return {character:hit.object.userData.character};
    if(!hit.object.material?.transparent)return {room:true};
  }
  return null;
}
let down=null;
on(renderer.domElement,'pointerdown',e=>{down={x:e.clientX,y:e.clientY,yaw:state.yaw,pitch:state.pitch};state.drag=false;renderer.domElement.setPointerCapture(e.pointerId);});
on(renderer.domElement,'pointermove',e=>{
  if(down) {
    const dx=e.clientX-down.x,dy=e.clientY-down.y;if(Math.hypot(dx,dy)>5)state.drag=true;
    if(state.drag){state.yaw=THREE.MathUtils.clamp(down.yaw-dx*.004,-.65,.85);state.pitch=THREE.MathUtils.clamp(down.pitch+dy*.003,.08,.7);$('#hover-label').hidden=true;}
  } else {
    const hit=pick(e);if(state.floor===null)setHover(hit?.floor??null);renderer.domElement.style.cursor=hit?'pointer':'grab';
    const label=hit?.character?hit.character.name+' · '+hit.character.message:hit?.floor!==undefined?BUILDINGS[hit.floor].name:null;
    $('#hover-label').hidden=!label;
    if(label){$('#hover-label').textContent=label;$('#hover-label').style.left=THREE.MathUtils.clamp(e.clientX,100,innerWidth-100)+'px';$('#hover-label').style.top=e.clientY+'px';}
  }
});
on(renderer.domElement,'pointerup',e=>{
  if(down&&!state.drag){const hit=pick(e);if(hit?.floor!==undefined)setFloor(hit.floor);else if(hit?.character)sayHi(hit.character);else if(!hit&&state.floor!==null&&!state.selected)setFloor(null);else closeSpeech();}
  down=null;state.drag=false;
});
on(renderer.domElement,'pointercancel',()=>{down=null;state.drag=false;});
on(renderer.domElement,'pointerleave',()=>{$('#hover-label').hidden=true;if(!down)setHover(null);});
on(renderer.domElement,'wheel',e=>{e.preventDefault();state.zoom=THREE.MathUtils.clamp(state.zoom*Math.exp(-e.deltaY*.0008),.7,1.8);},{passive:false});
on(document,'keydown',e=>{if(e.ctrlKey||e.metaKey||e.altKey)return;if(e.key==='Escape'){if(state.selected)closeSpeech();else if(state.floor!==null)setFloor(null);}if(/^[1-9]$/.test(e.key)&&+e.key<=BUILDINGS.length)setFloor(+e.key-1);if(e.key==='0')setFloor(null);});
on(window,'resize',()=>renderer.setSize(innerWidth,innerHeight));
on(renderer.domElement,'webglcontextlost',e=>{e.preventDefault();controller.abort();cancelAnimationFrame(frameId);window.dispatchEvent(new Event('overview-context-lost'));});
let last=0,frameId=0,frames=0,loadingTimer=0;
function animate(now) {
  frameId=0;if(document.hidden){last=0;return;}const dt=last?Math.min(.05,(now-last)/1000):.016;last=now;
  // Read the live query: some iframe browsers update matches without delivering a change event.
  const paused=reduced.matches;
  if(!paused)state.t+=dt;const t=state.t;updateCamera(dt);
  hoverFrames.forEach((m,i)=>m.material.opacity=THREE.MathUtils.lerp(m.material.opacity,state.hover===i?.6:0,.14));
  characters.forEach((ch,i)=>{
    ch.halo.material.opacity=state.selected===ch?.7:0;
    if(paused||!data.fresh)return;
    ch.wave=Math.max(0,ch.wave-dt);ch.body.position.y=ch.type==='bot'&&ch.activity==='running'?Math.sin(t*2.5+i)*.025:0;
    if(ch.arm)ch.arm.rotation.z=ch.wave>0?-.9+Math.sin(t*12)*.3:ch.type==='bot'&&ch.activity==='running'?Math.sin(t*2+i)*.08:0;
  });
  pods.forEach(({root,curve,phase})=>{const pos=(t*.035+phase)%1;root.position.copy(curve.getPointAt(pos));root.rotation.y=Math.atan2(curve.getTangentAt(pos).x,curve.getTangentAt(pos).z);});
  if(state.selected) {
    const p=project(state.selected.root.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,1.9,0)));
    $('#speech').style.left=THREE.MathUtils.clamp(p.x,125,innerWidth-125)+'px';$('#speech').style.top=THREE.MathUtils.clamp(p.y,270,innerHeight-50)+'px';
  }
  renderer.render(scene,camera);frames++;
  if(frames===3){$('#loading').classList.add('gone');loadingTimer=setTimeout(()=>$('#loading').hidden=true,200);document.body.dataset.sceneReady='true';}
  frameId=requestAnimationFrame(animate);
}
on(document,'visibilitychange',()=>{if(!document.hidden&&!frameId){last=0;frameId=requestAnimationFrame(animate);}});
const remembered=BUILDINGS.findIndex(b=>b.key===preferences.floorId);setFloor(remembered>=0?remembered:null);
frameId=requestAnimationFrame(animate);
return {
  select(key){const id=BUILDINGS.findIndex(b=>b.key===key);setFloor(id>=0?id:null);},
  update(next) {
    data=next;
    for(const b of BUILDINGS){const current=next.groups.find(g=>g.key===b.key);if(current)b.members=current.members;}
    const members=new Map(next.groups.flatMap(g=>g.members).map(m=>[m.id,m]));
    for(const ch of characters){const member=members.get(ch.actorId);if(member){ch.activity=member.state;ch.message=member.detail;ch.href=member.href;}}
    for(const ch of characters.filter(c=>c.floor===state.floor)){const button=$$('[data-person]').find(b=>b.dataset.person===ch.actorId);if(button){button.dataset.state=ch.activity;button.setAttribute('aria-label',ch.name+' · '+ch.message);}}
    if(state.floor!==null)$('#floor-subtitle').textContent=subtitle(BUILDINGS[state.floor]);
    if(state.selected)sayHi(state.selected);
  },
  dispose() {
    controller.abort();clearTimeout(loadingTimer);cancelAnimationFrame(frameId);
    scene.traverse(o=>{if(o.geometry)resources.add(o.geometry);if(o.material){resources.add(o.material);if(o.material.map)resources.add(o.material.map);}});
    geos.forEach(g=>resources.add(g));mats.forEach(m=>resources.add(m));resources.forEach(r=>r.dispose?.());
    renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();
  }
};
}
