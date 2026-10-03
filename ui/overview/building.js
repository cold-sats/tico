import * as THREE from '../vendor/three/three.module.min.js';
import { RoundedBoxGeometry } from '../vendor/three/RoundedBoxGeometry.js';
import { mergeGeometries } from '../vendor/three/BufferGeometryUtils.js';

export function createBuilding(data, preferences = {}, openMember = () => {}) {
const controller = new AbortController();
const on = (target, type, fn, options = {}) => target.addEventListener(type, fn, {...options, signal: controller.signal});
const resources = new Set();
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const icon = (body) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
const icons = {
  sun:icon('<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5"/>'),
  moon:icon('<path d="M21 13a9 9 0 0 1-10-10 9 9 0 1 0 10 10Z"/>'),
  pause:icon('<path d="M9 6v12m6-12v12" stroke-width="2"/>'),
  play:icon('<path d="m9 5 10 7-10 7Z" fill="currentColor" stroke="none"/>'),
  full:icon('<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>'),
  reset:icon('<path d="M4 10a8 8 0 1 1 1 8M4 4v6h6"/>'),
};
$('#light').innerHTML=icons.sun;$('#pause').innerHTML=reduced.matches?icons.play:icons.pause;$('#fullscreen').innerHTML=icons.full;$('#reset').innerHTML=icons.reset;

const palettes = [
  {color:0xe0aa82,rug:0xddb79b,wall:0xf1dfcc}, {color:0xb7a0d0,rug:0xbba5ce,wall:0xe6d9eb},
  {color:0x8cbcac,rug:0x91b9aa,wall:0xdce9de}, {color:0x9bafcb,rug:0xa5b9cc,wall:0xe1e8e9}
];
const DEPTS = data.groups.map((group, id) => ({...group, ...palettes[id % 4], id, sub: group.members.length + ' teammates', tag: group.members.length + ' teammates', page: 0}));
const numFloors = DEPTS.length;
const state={floor:null,night:!!preferences.night,paused:preferences.paused ?? reduced.matches,t:0,hover:null,selected:null,zoom:1,yaw:.36,pitch:.2,transition:null,drag:false};
let renderer;
try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});}catch(e){throw e;}
renderer.setPixelRatio(Math.min(devicePixelRatio,innerWidth < 600 ? 1.4 : 1.6));renderer.setSize(innerWidth,innerHeight);
renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;
renderer.shadowMap.autoUpdate=false;renderer.shadowMap.needsUpdate=true;
renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.35;
$('#world').replaceChildren(renderer.domElement);renderer.domElement.setAttribute('aria-label','3D headquarters. Use the department buttons to explore each floor.');renderer.domElement.setAttribute('role','img');
const scene=new THREE.Scene();scene.background=new THREE.Color(0xdfe9e2);scene.fog=new THREE.FogExp2(0xdfe9e2,.003);
const camera=new THREE.OrthographicCamera(-20,20,15,-15,.1,180);
const target=new THREE.Vector3(0,7.7,0);let currentTarget=target.clone();let currentPosition=new THREE.Vector3(15,17,37);let currentScale=28;
const hemi=new THREE.HemisphereLight(0xf4f5e4,0x8caa9b,2.9);scene.add(hemi);
const sun=new THREE.DirectionalLight(0xffedd5,4);sun.position.set(-14,27,19);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);Object.assign(sun.shadow.camera,{left:-24,right:24,top:27,bottom:-18,near:.1,far:90});sun.shadow.normalBias=.045;sun.shadow.bias=-.00015;sun.shadow.radius=3;scene.add(sun);
const fill=new THREE.DirectionalLight(0xd2e5f5,1.5);fill.position.set(12,12,-8);scene.add(fill);
const warmLight=new THREE.AmbientLight(0xffdbc0,.25);scene.add(warmLight);
const world=new THREE.Group();scene.add(world);
const floorGroups=[], ceilingParts=[], roof=new THREE.Group(), landscape=new THREE.Group(), facade=new THREE.Group();world.add(landscape,facade,roof);
const characters=[], lights=[], hitMeshes=[], emissives=[], hoverFrames=[];
const mats=new Map(),geos=new Map();
function material(color,opts={}){const key=String(color)+JSON.stringify(opts);if(!mats.has(key))mats.set(key,new THREE.MeshStandardMaterial({color,roughness:.78,metalness:0,...opts}));return mats.get(key);}
function mesh(g,geo,mat,x,y,z,shadow=true){const m=new THREE.Mesh(geo,typeof mat==='number'||typeof mat==='string'?material(mat):mat);m.position.set(x,y,z);m.castShadow=shadow;m.receiveShadow=true;g.add(m);resources.add(geo);resources.add(m.material);if(m.material.map)resources.add(m.material.map);return m;}
function box(g,x,y,z,w,h,d,c,r=.04){const key=`b:${w}:${h}:${d}:${r}`;if(!geos.has(key))geos.set(key,r?new RoundedBoxGeometry(w,h,d,2,Math.min(r,w/3,h/3,d/3)):new THREE.BoxGeometry(w,h,d));return mesh(g,geos.get(key),c,x,y,z);}
function ball(g,x,y,z,r,c,scale){const key='ball';if(!geos.has(key))geos.set(key,new THREE.SphereGeometry(1,16,12));const m=mesh(g,geos.get(key),c,x,y,z);m.scale.set(r*(scale?.[0]||1),r*(scale?.[1]||1),r*(scale?.[2]||1));return m;}
function cyl(g,x,y,z,rt,rb,h,c,sides=20){const key=`c:${rt}:${rb}:${h}:${sides}`;if(!geos.has(key))geos.set(key,new THREE.CylinderGeometry(rt,rb,h,sides));return mesh(g,geos.get(key),c,x,y,z);}
function rod(g,a,b,r,c){const aa=new THREE.Vector3(...a),bb=new THREE.Vector3(...b),v=bb.clone().sub(aa);const m=cyl(g,...aa.clone().add(bb).multiplyScalar(.5).toArray(),r,r,v.length(),c,8);m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),v.normalize());return m;}
function textTexture(label,fg='#49635b',bg=null,font=70,w=768,h=192){const cv=document.createElement('canvas');cv.width=w;cv.height=h;const ctx=cv.getContext('2d');if(bg){ctx.fillStyle=bg;ctx.fillRect(0,0,w,h);}ctx.fillStyle=fg;ctx.font=`600 ${font}px -apple-system, BlinkMacSystemFont, sans-serif`;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(label,w/2,h/2);const t=new THREE.CanvasTexture(cv);t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=4;return t;}
function sign(g,label,x,y,z,w,h,fg,bg){const tex=textTexture(label,fg,bg,60);const m=mesh(g,new THREE.PlaneGeometry(w,h),new THREE.MeshBasicMaterial({map:tex,transparent:true,depthWrite:false}),x,y,z,false);return m;}
function glowing(c,intensity=.4){const m=material(c,{emissive:c,emissiveIntensity:intensity});if(!emissives.includes(m))emissives.push(m);return m;}
function plant(g,x,y,z,size=1,pot=0xc5a88b){const p=new THREE.Group();p.position.set(x,y,z);p.scale.setScalar(size);g.add(p);cyl(p,0,.22,0,.25,.2,.44,pot);cyl(p,0,.45,0,.25,.25,.08,pot);cyl(p,0,.47,0,.2,.2,.03,0x675c48);rod(p,[0,.45,0],[0,1.15,0],.025,0x768565);for(let i=0;i<7;i++){const t=i*2.4,yy=.65+(i%3)*.2;const l=ball(p,Math.cos(t)*.19,yy,Math.sin(t)*.19,.23,[0x8fae75,0x72995f,0xa2b986][i%3],[.6,1.7,.7]);l.rotation.z=Math.sin(t)*.65;l.rotation.x=Math.cos(t)*.7;}return p;}
function tree(g,x,y,z,s=1){const t=new THREE.Group();g.add(t);t.position.set(x,y,z);t.scale.setScalar(s);cyl(t,0,1,0,.12,.18,2,0x9b8268,8);rod(t,[0,1.1,0],[.5,1.85,.15],.07,0x9b8268);rod(t,[0,1.2,0],[-.4,1.9,-.1],.06,0x9b8268);ball(t,0,2.25,0,.84,0x93b187,[1,1.3,1]);ball(t,.5,2.08,.13,.55,0xaac59a);ball(t,-.4,2.18,-.1,.64,0x85a779);ball(t,.12,2.95,-.1,.56,0xa9c396);return t;}
function book(g,x,y,z,w,h,color){return box(g,x,y+h/2,z,w,h,.28,color,.012);}
function bookshelf(g,x,z,color=0xd0b28e){box(g,x,1.04,z,1.55,2.08,.48,color);for(let i=0;i<3;i++){box(g,x,.32+i*.61,z+.27,1.4,.48,.04,0xefe6d3,.01);for(let j=0;j<6;j++){const h=.26+(j*7%5)*.035;book(g,x-.58+j*.21,.14+i*.61,z+.33,.12,h,[0x98afa0,0xdab08d,0xb1a0c2,0xc6c1a1][(i+j)%4]);}box(g,x,.64+i*.61,z+.05,1.55,.08,.6,color);}plant(g,x,2.12,z,.55);}
function screen(g,x,y,z,w=1.02,angle=0){const s=new THREE.Group();s.position.set(x,y,z);s.rotation.y=angle;g.add(s);box(s,0,0,0,w,.68,.1,0x466366,.06);box(s,0,.015,.058,w-.1,.56,.015,glowing(0xb4d9c5,.28),.02);for(let r=0;r<5;r++){const width=.2+(r*7%4)*.12;box(s,-w*.35+width/2,.18-r*.077,.073,width,.025,.008,r%2?0x77aca8:0x6a9791,0);}box(s,0,-.39,0,.075,.17,.075,0x687f78);box(s,0,-.48,.06,.4,.05,.3,0x91a196);return s;}
function mug(g,x,y,z,c=0xdda57e){cyl(g,x,y+.095,z,.095,.085,.19,c);cyl(g,x,y+.194,z,.074,.074,.009,0x6a4e3c);const tor=new THREE.TorusGeometry(.071,.021,6,10);const m=mesh(g,tor,c,x+.095,y+.11,z);m.rotation.y=Math.PI/2;}
function desk(g,x,z,c=0xe6d1b0,dual=false){const d=new THREE.Group();d.position.set(x,0,z);g.add(d);box(d,0,1.03,0,2.5,.16,1.25,c,.08);for(const xx of [-1.02,1.02])for(const zz of [-.42,.42])box(d,xx,.48,zz,.09,1,.09,0xc0b69b,.02);screen(d,dual?-.56:0,1.62,-.25,dual?.87:1.02);if(dual)screen(d,.49,1.62,-.25,.87,-.07);box(d,0,1.133,.25,.68,.045,.23,0xc4d2bc,.025);for(let j=0;j<3;j++)box(d,-.27+j*.19,1.16,.25,.12,.008,.12,0xa5b69e,.004);box(d,.59,1.13,.25,.12,.06,.18,0xa8b6a1,.04);mug(d,.97,1.13,-.06);return d;}
function chair(g,x,z,c=0xa2b69a,angle=0){const ch=new THREE.Group();ch.position.set(x,0,z);ch.rotation.y=angle;g.add(ch);cyl(ch,0,.3,0,.07,.07,.48,0x6a7a6e);for(let i=0;i<4;i++){const a=i*Math.PI/2;rod(ch,[0,.15,0],[Math.cos(a)*.36,.1,Math.sin(a)*.36],.04,0x6a7a6e);ball(ch,Math.cos(a)*.35,.075,Math.sin(a)*.35,.065,0x637568);}box(ch,0,.57,0,.66,.16,.64,c,.1);box(ch,0,.91,.25,.66,.67,.15,c,.1);return ch;}
function couch(g,x,z,c,angle=0){const co=new THREE.Group();co.position.set(x,0,z);co.rotation.y=angle;g.add(co);box(co,0,.34,0,2.55,.47,1,c,.15);box(co,0,.83,-.4,2.6,.86,.26,c,.1);for(const xx of [-1.15,1.15])box(co,xx,.69,0,.28,.68,1.08,c,.09);for(const xx of [-.64,.05,.7])box(co,xx,.61,.04,.6,.16,.72,0xe3d9be,.07);return co;}
function whiteboard(g,x,z,creative=false){box(g,x,1.81,z,2.4,1.45,.1,0xc8c9b6);box(g,x,1.81,z+.06,2.27,1.32,.02,0xf3efd9,.01);for(let i=0;i<7;i++){box(g,x-.84+(i%4)*.52,2.07-Math.floor(i/4)*.42,z+.079,.34,.27,.012,[0xdfb487,0xb5c899,0xb5a8cc][i%3],.006);}if(creative){box(g,x+.72,1.52,z+.095,.27,.26,.02,0x8eb8bc,.03);}else{box(g,x-.5,1.52,z+.095,1.1,.025,.01,0x99b4a5,0);}}
function pendant(g,x,z,c){rod(g,[x,3.28,z],[x,2.83,z],.018,0x9aab96);cyl(g,x,2.8,z,.15,.38,.24,c);cyl(g,x,2.68,z,.31,.31,.018,glowing(0xffe3ac,.45));}
function art(g,x,y,z,w=1,h=1,color=0xd7a47e){box(g,x,y,z,w+.1,h+.1,.1,0xc4ae90,.015);box(g,x,y,z+.07,w,h,.02,0xf4e8cd,.01);const p=cyl(g,x,y,z+.09,w*.29,w*.29,.009,color,32);p.rotation.x=Math.PI/2;box(g,x+w*.18,y-h*.23,z+.1,w*.21,h*.48,.01,0x8ca894,0);}
function character(g,data,x,z,floor,index){
  const {id:actorId,name,type,state:activity,detail:message,href}=data; const color=type==='human'?0xd1ae8a:palettes[(floor+4)%4].color,root=new THREE.Group();root.position.set(x,.28,z);root.scale.setScalar(1.14);g.add(root);
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

// The tiny world sits on a generous, rounded piece of landscape.
box(landscape,0,-.22,0,24,.9,15,0xcbd4bb,.4);box(landscape,0,.18,0,23.6,.16,14.6,0xe5ddc5,.12);
box(landscape,-9.4,.34,-.2,3.35,.18,11.4,0xa8bf92,.25);box(landscape,9.85,.34,-.4,2.5,.18,10.4,0xa8bd93,.25);
for(let i=0;i<3;i++)box(landscape,0,-.06-i*.12,7.7+i*.4,8.3+i*.7,.2,.64,0xe7e2cc,.04);
for(let i=0;i<13;i++)box(landscape,-10.2+i*1.7,.3,6.22,1.5,.025,.85,i%2?0xd5d2bd:0xdbd8c4,.025);
for(let i=0;i<7;i++)box(landscape,-8.15,.3,-5.6+i*1.7,.9,.025,1.42,0xd0d1bb,.025);
[[-9.6,-4.8,1.25],[-10.1,.3,1.05],[-9.5,4.4,.85],[10,-4.5,1.15],[10.15,3.8,1.1]].forEach(([x,z,s])=>tree(landscape,x,.42,z,s));
for(let i=0;i<9;i++){const x=i<5?-9.4:10.1,z=-4+(i%5)*1.9;ball(landscape,x,.6,z,.49,[0x8ea773,0xb2c58d,0x9ab483][i%3],[1,.55,.8]);}
// A bike, a bench, stepping stones, and a suspiciously well-fed studio cat.
for(const x of [-5.6,5.5]){box(landscape,x,.85,6.0,2.45,.13,.57,0xc39971);box(landscape,x,1.16,5.82,2.45,.48,.11,0xc39971);for(const xx of [-.9,.9])rod(landscape,[x+xx,.35,5.83],[x+xx,.83,6.07],.065,0x6c8277);}
for(const x of [-7.6,8.3]){cyl(landscape,x,1.65,5.8,.045,.065,2.6,0x5e7f73);ball(landscape,x,3,5.8,.25,glowing(0xffe5a5,.4));cyl(landscape,x,3.21,5.8,.18,.29,.14,0x718e78);}
const bike=new THREE.Group();landscape.add(bike);bike.position.set(-7.4,.73,3.1);bike.rotation.y=.15;
for(const x of [-.55,.55]){const m=mesh(bike,new THREE.TorusGeometry(.34,.035,7,20),0x4b6862,x,0,0);m.castShadow=false;rod(bike,[x,0,0],[x+.12,.5,0],.03,0xbaa073);}rod(bike,[-.55,0,0],[0,.5,0],.03,0xceaa76);rod(bike,[0,.5,0],[.55,0,0],.03,0xceaa76);rod(bike,[-.55,0,0],[.32,.38,0],.03,0xceaa76);box(bike,0,.56,0,.27,.055,.13,0x5a7265);
const cat=new THREE.Group();landscape.add(cat);cat.position.set(4.8,.39,6.4);ball(cat,0,.14,0,.2,0xce9e6f,[1.5,.75,.9]);ball(cat,.24,.25,0,.14,0xce9e6f);for(const x of [.18,.31]){const e=mesh(cat,new THREE.ConeGeometry(.06,.15,4),0xc29569,x,.39,0);e.rotation.z=x<.2?.2:-.2;}rod(cat,[-.2,.15,0],[-.5,.25,.12],.046,0xd7ad80);
// A quiet studio horizon, not a dashboard background.
const ground=mesh(scene,new THREE.PlaneGeometry(2000,2000),new THREE.MeshBasicMaterial({color:0xdfe9e2,toneMapped:false}),0,-.76,0,false);ground.rotation.x=-Math.PI/2;ground.receiveShadow=false;
const groundShadow=mesh(scene,new THREE.PlaneGeometry(2000,2000),new THREE.ShadowMaterial({opacity:.17}),0,-.75,0,false);groundShadow.rotation.x=-Math.PI/2;
const cloudGroups=[];
for(let i=0;i<7;i++){const cl=new THREE.Group();scene.add(cl);cl.position.set(-38+i*13,13+(i%3)*5,-26-(i%2)*9);for(let j=0;j<4;j++){const puff=ball(cl,j*1.15,Math.sin(j)*.4,0,.9,material(0xf1f3e9,{roughness:1}),[1.9,.5,1]);puff.castShadow=false;}cloudGroups.push(cl);}

for(const dept of DEPTS){
  const layout=dept.id%4;
  const g=new THREE.Group();g.position.y=.62+dept.id*3.65;g.userData.floor=dept.id;world.add(g);floorGroups.push(g);
  box(g,0,0,0,14.5,.3,8.5,0xebe2cd,.09);
  box(g,0,.2,0,13.9,.08,7.9,0xe8d7b8,.02);
  // Fine board seams give the floors scale without noisy textures.
  for(let j=0;j<14;j++)box(g,-6.7+j*1.02,.245,0,.015,.008,7.8,0xdac9ac,0);
  box(g,0,1.85,-4,14.2,3.45,.25,dept.wall,.03);
  box(g,-7,1.83,0,.24,3.35,8,0xe4dcc6,.04);
  // The right side is a cutaway frame with a waist-high parapet.
  box(g,7,.48,0,.24,.73,8,0xded4bd,.03);
  for(const x of [-7,7])for(const z of [-4,4])box(g,x,1.8,z,.3,3.55,.3,0xece3ce,.04);
  const beam=box(g,0,3.5,4.08,14.5,.23,.27,0xe9dfc9,.035);beam.userData.keep=true;ceilingParts.push(beam);
  box(g,0,.22,3.95,14.1,.08,.11,dept.color,.02);
  // Three large rear windows frame pale green outdoors.
  for(const x of [-4.7,0,4.7]){box(g,x,2,-3.835,2.4,1.66,.1,0xb1c3b7,.035);box(g,x,2,-3.766,2.23,1.49,.015,glowing(0xd2e5da,.1),.015);box(g,x,2,-3.72,.045,1.5,.03,0xa3bbae,.005);box(g,x,1.2,-3.67,2.6,.1,.35,0xeae7d4,.02);}
  // A color accent, rug, and room-specific furniture give every floor an identity.
  box(g,-.1,.26,.65,11.9,.032,4.8,dept.rug,.15);
  box(g,-.1,.281,.65,11.45,.012,4.35,material(dept.rug,{roughness:1}),.12);
  plant(g,-6.08,.27,2.96,1.35);plant(g,6.02,.27,-2.8,1.22);
  sign(g,String(data.offset+dept.id+1).padStart(2,'0'),6.83,2.55,4.247,.22,.28,'#8c9b83');
  pendant(g,-3.7,.25,dept.color);pendant(g,3.7,.25,dept.color);
  const pl=new THREE.PointLight(0xffd5a5,1.2,13,2);pl.position.set(0,2.8,.5);g.add(pl);lights.push(pl);
  if(layout===0){
    desk(g,-3,.1,0xe7d1ac);desk(g,.25,.1,0xe7d1ac);chair(g,-3,1.18,0xc6a68b);chair(g,.25,1.18,0xc6a68b);
    box(g,4.75,.73,-1.42,2.7,1.45,.85,0xb1b79a);box(g,4.75,1.5,-1.42,2.85,.1,1.0,0xf0dfbf);for(const xx of [3.98,4.76,5.54])box(g,xx,.78,-.972,.7,1.13,.06,0xcdd0b4,.03);
    box(g,4.2,1.88,-1.42,.6,.7,.52,0x4f6e64,.1);box(g,4.2,1.91,-1.14,.38,.3,.025,0xaccbc0,.02);mug(g,4.2,1.57,-1.06);mug(g,5.1,1.57,-1.2,0xe1c596);plant(g,5.76,1.57,-1.6,.55);
    sign(g,'BUT FIRST, COFFEE.',4.55,2.67,-3.58,2.3,.4,'#9b9478');bookshelf(g,-5.7,-3.15);whiteboard(g,-1.9,-3.66);
    couch(g,4.55,2.48,0xcc9877);cyl(g,3, .59,2.85,.53,.53,.11,0xe9d1a8);cyl(g,3,.42,2.85,.08,.08,.3,0xbaa586);mug(g,3,.66,2.85);
  }else if(layout===1){
    desk(g,-3.9,.05,0xe8d7bd);desk(g,-.1,.05,0xe8d7bd,true);chair(g,-3.9,1.2,0xa28cb2);chair(g,-.1,1.2,0xa28cb2);
    whiteboard(g,-2.45,-3.6,true);art(g,2.4,2.03,-3.69,1.05,1.42,0xcea17b);art(g,3.65,2.03,-3.69,1.05,1.42,0x9ab5a9);
    couch(g,4.3,-1,0xbfa1c7);cyl(g,4.25,.63,.55,.88,.88,.12,0xe3cba9);for(const xx of [3.7,4.8])rod(g,[xx,.27,.55],[xx,.59,.55],.05,0xb8ac91);book(g,4.1,.71,.55,.55,.055,0x9cb9a5);mug(g,4.62,.7,.7,0xbb91b8);
    box(g,-5.93,1.16,-2.7,1.05,1.65,.52,0xc3af8b);for(let i=0;i<4;i++)box(g,-5.93,.52+i*.38,-2.4,.9,.26,.07,[0xe0be97,0xa8b5ce,0xb9c798,0xd6a89e][i]);
  }else if(layout===2){
    desk(g,-3.8,0,0xdfd3b6,true);desk(g,0,0,0xdfd3b6,true);desk(g,3.8,0,0xdfd3b6);[-3.8,0,3.8].forEach(x=>chair(g,x,1.2,0x90a99b));
    whiteboard(g,-2.45,-3.65);box(g,5.58,1.33,-2.72,1.15,2.35,.72,0x4a6461,.1);
    for(let i=0;i<6;i++){box(g,5.58,.44+i*.31,-2.31,.92,.25,.055,0x607b72,.02);for(let j=0;j<3;j++)ball(g,5.28+j*.12,.44+i*.31,-2.265,.025,glowing(j===1?0xe2c28b:0x9adab8,.8));}
    sign(g,'MAKE GOOD THINGS.',1.4,2.72,-3.67,2.7,.4,'#819b88');bookshelf(g,-5.8,-3.1);
  }else{
    // A collaboration table rather than another identical row of desks.
    box(g,-2.3,1.04,.0,4.7,.18,1.75,0xe1cbaa,.3);for(const x of [-3.8,-.9])for(const z of [-.55,.55])rod(g,[x,.27,z],[x,1,z],.065,0xb5a58c);
    for(const x of [-3.65,-1.05]){chair(g,x,1.18,0x96abb6);chair(g,x,-1.2,0x96abb6,Math.PI);mug(g,x,1.14,.25);}
    box(g,-2.5,1.17,0,.8,.05,.52,0xb3bfba,.03);const laptop=box(g,-2.5,1.49,-.23,.8,.58,.045,0x668c8e,.035);laptop.rotation.x=-.15;box(g,-2.49,1.5,-.19,.67,.43,.012,glowing(0xb4d6c5,.2),.025);
    whiteboard(g,-2.4,-3.64);couch(g,4.42,-.7,0x9db6b5);cyl(g,4.22,.65,.7,.75,.75,.14,0xddc4a3);cyl(g,4.22,.4,.7,.12,.17,.55,0xb8aa8c);plant(g,4.22,.75,.7,.45);bookshelf(g,5.48,-3.08);art(g,1.35,2.15,-3.67,1.1,1.3,0xdaa783);
    sign(g,'WHAT IF?',-5.0,2.95,-3.68,1.5,.28,'#849a99');
  }
  dept.room=g;
  // Each room displays a bounded page; no teammate is silently dropped from a large group.
  populate(dept);
  // The invisible floor surface is also a generous click target.
  const hit=box(g,0,1.65,0,13.8,3.2,8,material(0xffffff,{transparent:true,opacity:0,depthWrite:false}),0);hit.userData.pickFloor=dept.id;hit.userData.keep=true;hit.castShadow=false;hit.receiveShadow=false;hitMeshes.push(hit);
  const outline=mesh(g,new THREE.BoxGeometry(14.64,.04,8.63),new THREE.MeshBasicMaterial({color:0xffe5aa,transparent:true,opacity:0}),0,.19,0,false);outline.userData.keep=true;hoverFrames.push(outline);
}
// A tiny roof garden: pergola, solar panels, picnic table, and a garden robot.
roof.position.y=.62+numFloors*3.65;
box(roof,0,0,0,14.65,.35,8.62,0xe8dfca,.08);box(roof,0,.2,0,14.1,.08,8.1,0xd4d8b9,.035);
for(const z of [-4.08,4.08])box(roof,0,.46,z,14.4,.5,.18,0xe5dac1,.035);for(const x of [-7.08,7.08])box(roof,x,.46,0,.18,.5,8.25,0xe5dac1,.035);
box(roof,-4.7,.46,-.7,3.3,.43,4.8,0xb2be94,.16);tree(roof,-4.8,.66,-2.0,.84);tree(roof,-4.65,.66,.85,.69);plant(roof,-5.78,.68,.0,1.2);
for(const x of [-1.6,2.2])for(const z of [-2.7,1.5])box(roof,x,1.3,z,.13,2.28,.13,0xc6ad88,.02);for(let j=0;j<9;j++)box(roof,.3,2.47,-2.7+j*.52,4.23,.14,.14,0xd7bd94,.025);
box(roof,.25,.85,-.5,2.6,.12,1.2,0xd1ae7c,.07);for(const z of [-1.5,.5])box(roof,.25,.55,z,2.95,.13,.42,0xcaa476,.05);for(const x of [-.7,1.2])rod(roof,[x,.25,-1.5],[x,.8,-.5],.06,0x9d9b79);plant(roof,.3,.93,-.5,.52,0xd9b28c);
for(const z of [-2.3,-.4,1.5]){const panel=box(roof,4.65,.67,z,2.5,.09,1.4,0x6f9398,.04);panel.rotation.x=-.15;for(let k=0;k<5;k++){const r=box(roof,3.67+k*.49,.74,z,.017,.012,1.28,0x9ab6b0,0);r.rotation.x=-.15;}}
rod(roof,[6,.28,-3.2],[6,3.3,-3.2],.04,0x90a38e);const flag=box(roof,6.62,2.96,-3.2,1.23,.6,.035,0xdba679,.025);sign(roof,'t.',6.61,2.99,-3.17,.4,.37,'#f7edd6');
sign(roof,data.company.slice(0,24),0,-.02,4.33,2,.3,'#899a81');
// The transparent elevator lives outside the cutaway and carries a little light between floors.
const elevator=new THREE.Group();facade.add(elevator);elevator.position.set(8.05,0,.25);
for(const x of [-.7,.7])for(const z of [-1.3,1.3])box(elevator,x,(numFloors*3.65+.8)/2,z,.09,numFloors*3.65+.6,.09,0x9aafa3,.02);
box(elevator,.73,(numFloors*3.65+.8)/2,0,.045,numFloors*3.65+.5,2.6,material(0xb6d8d1,{transparent:true,opacity:.16,depthWrite:false}),0);
box(elevator,0,.84+numFloors*3.65,0,1.68,.25,2.8,0xc9d2b8,.05);for(let i=0;i<numFloors;i++)box(elevator,0,.63+i*3.65,0,1.68,.14,2.8,0xa1b5a7,.04);
const cabin=new THREE.Group();elevator.add(cabin);box(cabin,0,.1,0,1.4,.19,2.2,0xc5d1b7,.05);box(cabin,0,1.27,-1,1.4,2.3,.1,0x8eb4a9,.03);box(cabin,0,2.46,0,1.4,.13,2.2,0xc9d3b9,.04);box(cabin,0,1.25,1,.02,2.4,.04,0xb7cbbb,.01);box(cabin,0,2.39,0,.85,.025,1.25,glowing(0xffe2ab,.7),.015);
// The elevator is scenery, not an invented teammate.
box(cabin,0,.46,.2,.5,.55,.45,0xe1bd8d,.08);

// Furniture is drawn in batches; the characters and elevator remain independently animated.
function batchStatic(root){
  root.updateWorldMatrix(true,true);
  const inverse=root.matrixWorld.clone().invert(),batches=new Map(),originals=[];
  root.traverse(o=>{
    if(!o.isMesh||o.userData.character||o.userData.keep||o.material.transparent)return;
    const key=o.material.uuid+':'+o.castShadow;
    if(!batches.has(key))batches.set(key,{material:o.material,cast:o.castShadow,geos:[]});
    const geo=o.geometry.index?o.geometry.toNonIndexed():o.geometry.clone();
    geo.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inverse,o.matrixWorld));
    batches.get(key).geos.push(geo);originals.push(o);
  });
  for(const b of batches.values()){
    const geo=mergeGeometries(b.geos,false);if(!geo)continue;
    const m=new THREE.Mesh(geo,b.material);m.castShadow=b.cast;m.receiveShadow=true;root.add(m);
    b.geos.forEach(g=>g.dispose());
  }
  originals.forEach(o=>o.removeFromParent());
}
floorGroups.forEach(batchStatic);batchStatic(landscape);

function populate(dept) {
  for(let i=characters.length-1;i>=0;i--)if(characters[i].floor===dept.id){
    const ch=characters[i];ch.root.removeFromParent();
    // The halo is per character; the remaining geometry and materials belong to the shared caches.
    for(const resource of [ch.halo.geometry,ch.halo.material]){resource.dispose();resources.delete(resource);}
    characters.splice(i,1);
  }
  const members=dept.members.slice(dept.page*6,dept.page*6+6);
  members.forEach((member,i)=>{
    const row=Math.floor(i/3),x=-4+i%3*4,z=members.length>3?(row?3.05:1.7):2.4;
    const ch=character(dept.room,member,x,z,dept.id,i);
    if(members.length>3)ch.root.scale.setScalar(.88);
  });
}
// Raycasting and camera movement stay independent of the decorative animation clock.
const raycaster=new THREE.Raycaster(), pointer=new THREE.Vector2();
function desiredCamera(){const small=innerWidth<560,aspect=innerWidth/innerHeight;let scale,target,yaw,pitch;
  if(state.floor===null){target=new THREE.Vector3(small?-.6:0,(numFloors*3.65+1)/2,0);yaw=small?state.yaw*.55:state.yaw;pitch=state.pitch;scale=Math.max(numFloors*3.65+10,small?23/aspect:33/aspect)/state.zoom;}
  else {target=new THREE.Vector3(0,.88+state.floor*3.65,0);yaw=state.yaw;pitch=state.pitch;scale=Math.max(13,small?18/aspect:23/aspect)/state.zoom;}
  return {target,position:target.clone().add(new THREE.Vector3(Math.sin(yaw)*Math.cos(pitch)*42,Math.sin(pitch)*42,Math.cos(yaw)*Math.cos(pitch)*42)),scale};
}
function updateCamera(dt){const desired=desiredCamera(),lerp=reduced.matches?1:1-Math.exp(-dt*5.2);currentTarget.lerp(desired.target,lerp);currentPosition.lerp(desired.position,lerp);currentScale=THREE.MathUtils.lerp(currentScale,desired.scale,lerp);camera.position.copy(currentPosition);camera.lookAt(currentTarget);const aspect=innerWidth/innerHeight;camera.left=-currentScale*aspect/2;camera.right=currentScale*aspect/2;camera.top=currentScale/2;camera.bottom=-currentScale/2;camera.updateProjectionMatrix();}
function project(v){const p=v.clone().project(camera);return {x:(p.x+1)*innerWidth/2,y:(1-p.y)*innerHeight/2};}
function labels(){if(state.floor!==null)return;DEPTS.forEach(d=>{const p=project(new THREE.Vector3(-7.55,.62+d.id*3.65+1.8,4.1));const b=$(`[data-floor="${d.id}"]`);b.style.left=Math.max(innerWidth<560?38:166,p.x-(innerWidth<560?12:30))+'px';b.style.top=p.y+'px';});}
function personLabels(){if(state.floor===null)return;characters.filter(c=>c.floor===state.floor).forEach(ch=>{const p=project(ch.root.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,0,.43)));const b=$$('[data-person]').find(b=>b.dataset.person===ch.actorId);if(b){b.style.left=p.x+'px';b.style.top=(p.y+14)+'px';}});}
$('#floors').replaceChildren();
for(const d of [...DEPTS].reverse()){
  const button=document.createElement('button');button.className='floor-label';button.dataset.floor=d.id;
  button.setAttribute('aria-label',d.name+', '+d.members.length+' teammates');
  const number=document.createElement('span');number.className='floor-no';number.textContent=String(data.offset+d.id+1).padStart(2,'0');
  const copy=document.createElement('span');copy.className='floor-text';
  const strong=document.createElement('strong');strong.textContent=d.name;
  copy.append(strong);
  button.append(number,copy);$('#floors').append(button);
}
function memberLabels() {
  $('#people').replaceChildren();
  for(const ch of characters.filter(c=>c.floor===state.floor)){
    const b=document.createElement('button');b.className='person-label';b.dataset.person=ch.actorId;b.dataset.state=ch.activity;b.textContent=ch.name;
    b.setAttribute('aria-label',ch.name+' · '+ch.message);b.onclick=()=>sayHi(ch);$('#people').append(b);
  }
}
function setHover(id){state.hover=id;$$('[data-floor]').forEach(b=>b.classList.toggle('hovered',Number(b.dataset.floor)===id));}
function closeSpeech(){state.selected=null;$('#speech').hidden=true;}
function setFloor(id){
  state.floor=id;state.zoom=1;state.yaw=id===null?.36:.07;state.pitch=id===null?.2:1.03;setHover(null);closeSpeech();$('#hover-label').hidden=true;
  $('#floors').hidden=id!==null;$('#floor-heading').hidden=id===null;$('#back').hidden=id===null;document.body.classList.toggle('inside',id!==null);
  $('#people').hidden=id===null;
  memberLabels();
  if(id!==null){const d=DEPTS[id];$('#floor-title').textContent=d.name;$('#floor-number').textContent=`Floor ${data.offset+id+1}`;$('#floor-subtitle').textContent=d.members.length+' teammates · '+d.members.filter(m=>m.state==='running').length+' bots running';}
  floorGroups.forEach((g,i)=>{g.visible=id===null||i===id;});roof.visible=id===null;facade.visible=id===null;landscape.visible=id===null;
  cloudGroups.forEach(c=>c.visible=id===null);ceilingParts.forEach(b=>b.visible=id===null);
  ground.position.y=id===null?-.76:.43+id*3.65;
  groundShadow.position.y=ground.position.y+.01;
  renderer.shadowMap.needsUpdate=true;
  if(id!==null)preferences.floorId=DEPTS[id].key;else preferences.floorId=null;
  $('#department-picker').value=preferences.floorId||'';
  updatePaging();
  if(id!==null)$('#back').focus({preventScroll:true});
}
$$('[data-floor]').forEach(b=>{b.onclick=()=>setFloor(+b.dataset.floor);b.onpointerenter=()=>setHover(+b.dataset.floor);b.onpointerleave=()=>setHover(null);b.onfocus=()=>setHover(+b.dataset.floor);b.onblur=()=>setHover(null);});
$('#back').onclick=()=>{const id=state.floor;setFloor(null);$(`[data-floor="${id}"]`).focus();};
function sayHi(ch){if(state.floor===null&&ch.floor>=0){setFloor(ch.floor);}state.selected=ch;ch.wave=3;$('#speech-type').textContent=ch.type==='human'?'Person':'Bot';$('#speech-name').textContent=ch.name;$('#speech-message').textContent=ch.type==='human'?'Presence is not tracked.':(!data.fresh?'Status is unavailable. Reconnecting…':ch.message);$('#speech-open').hidden=!ch.href;$('#speech-open').onclick=()=>openMember(ch.actorId);$('#speech').hidden=false;}
$('#speech-close').onclick=closeSpeech;
function pick(ev){pointer.set(ev.clientX/innerWidth*2-1,-ev.clientY/innerHeight*2+1);raycaster.setFromCamera(pointer,camera);if(state.floor===null){const hits=raycaster.intersectObjects(hitMeshes,false);return hits.length?{floor:hits[0].object.userData.pickFloor}:null;}const hits=raycaster.intersectObjects(floorGroups[state.floor].children,true);for(const h of hits){if(h.object.userData.character)return {character:h.object.userData.character};if(!h.object.material?.transparent)return null;}return null;}
let down=null,lastPointer=null;
on(renderer.domElement,'pointerdown',e=>{down={x:e.clientX,y:e.clientY,yaw:state.yaw,pitch:state.pitch,id:e.pointerId};lastPointer=e;state.drag=false;renderer.domElement.setPointerCapture(e.pointerId);});
on(renderer.domElement,'pointermove',e=>{lastPointer=e;if(down){const dx=e.clientX-down.x,dy=e.clientY-down.y;if(Math.hypot(dx,dy)>5)state.drag=true;if(state.drag){state.yaw=THREE.MathUtils.clamp(down.yaw-dx*.004,-.65,.85);state.pitch=THREE.MathUtils.clamp(down.pitch+dy*.003,state.floor===null?.06:.55,state.floor===null?.55:1.43);$('#hover-label').hidden=true;}}else{const hit=pick(e);if(state.floor===null)setHover(hit?.floor??null);renderer.domElement.style.cursor=hit?'pointer':'grab';if(hit?.character){$('#hover-label').textContent=hit.character.name+' · '+hit.character.message;$('#hover-label').style.left=e.clientX+'px';$('#hover-label').style.top=e.clientY+'px';$('#hover-label').hidden=false;}else $('#hover-label').hidden=true;}});
on(renderer.domElement,'pointerup',e=>{if(down&&!state.drag){const hit=pick(e);if(hit?.floor!==undefined)setFloor(hit.floor);else if(hit?.character)sayHi(hit.character);else closeSpeech();}down=null;state.drag=false;});
on(renderer.domElement,'pointercancel',()=>{down=null;state.drag=false;});on(renderer.domElement,'pointerleave',()=>{$('#hover-label').hidden=true;if(!down)setHover(null);});
on(renderer.domElement,'wheel',e=>{e.preventDefault();state.zoom=THREE.MathUtils.clamp(state.zoom*Math.exp(-e.deltaY*.0008),.7,1.8);},{passive:false});
$('#zoom-in').onclick=()=>state.zoom=Math.min(1.8,state.zoom*1.15);$('#zoom-out').onclick=()=>state.zoom=Math.max(.7,state.zoom/1.15);$('#reset').onclick=()=>{state.zoom=1;state.yaw=state.floor===null?.36:.07;state.pitch=state.floor===null?.2:1.03;};
function pause(value){state.paused=value;preferences.paused=value;$('#pause').innerHTML=value?icons.play:icons.pause;$('#pause').setAttribute('aria-label',value?'Let the world play':'Pause the world');}
$('#pause').onclick=()=>pause(!state.paused);on(reduced,'change',e=>{if(e.matches)pause(true);});
function night(){state.night=!state.night;preferences.night=state.night;document.body.classList.toggle('night',state.night);$('#light').innerHTML=state.night?icons.moon:icons.sun;$('#light').setAttribute('aria-label',state.night?'Switch to daytime':'Switch to nighttime');renderer.shadowMap.needsUpdate=true;}
$('#light').onclick=night;
$('#fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{}};
on(document,'fullscreenchange',()=>$('#fullscreen').setAttribute('aria-label',document.fullscreenElement?'Exit fullscreen':'Enter fullscreen'));
on(document,'keydown',e=>{if(e.ctrlKey||e.metaKey||e.altKey||e.target?.tagName==='SELECT'||$('#help-panel').matches(':popover-open'))return;if(e.key==='Escape'){if(state.selected)closeSpeech();else if(state.floor!==null)setFloor(null);}if(/^[1-5]$/.test(e.key)&&+e.key<=numFloors)setFloor(+e.key-1);if(e.key==='0')setFloor(null);if(e.key.toLowerCase()==='n')night();});
on(window,'resize',()=>{renderer.setSize(innerWidth,innerHeight);});

on(renderer.domElement,'webglcontextlost',e=>{e.preventDefault();controller.abort();cancelAnimationFrame(frameId);window.dispatchEvent(new Event('overview-context-lost'));});


let last=0,frameId=0,nightMix=state.night?1:0,frames=0,loadingTimer=0;
const dayColor=new THREE.Color(0xdfe9e2),nightColor=new THREE.Color(0x142932);
function animate(now){frameId=0;if(document.hidden){last=0;return;}const dt=last?Math.min(.05,(now-last)/1000):.016;last=now;
  if(!state.paused)state.t+=dt;const t=state.t;
  updateCamera(dt);
  const prevNight=nightMix;nightMix=reduced.matches?(state.night?1:0):THREE.MathUtils.lerp(nightMix,state.night?1:0,1-Math.exp(-dt*2.5));
  scene.background.copy(dayColor).lerp(nightColor,nightMix);scene.fog.color.copy(scene.background);ground.material.color.copy(scene.background);
  hemi.color.set(0xf4f5e4).lerp(new THREE.Color(0xabc9f0),nightMix);hemi.groundColor.set(0x8caa9b).lerp(new THREE.Color(0x344c63),nightMix);sun.color.set(0xffedd5).lerp(new THREE.Color(0xa6c9ef),nightMix);
  hemi.intensity=1.5-nightMix*.95;sun.intensity=2.3-nightMix*2.05;fill.intensity=.65-nightMix*.25;warmLight.intensity=.1+nightMix*.08;renderer.toneMappingExposure=1.12-nightMix*.03;
  lights.forEach(l=>l.intensity=1.2+nightMix*17);emissives.forEach(m=>m.emissiveIntensity=.12+nightMix*.65);
  if(Math.abs(prevNight-nightMix)>.002)renderer.shadowMap.needsUpdate=true;
  hoverFrames.forEach((m,i)=>{m.material.opacity=THREE.MathUtils.lerp(m.material.opacity,state.hover===i?.48:0,.14);});
  cabin.position.y=.7+(Math.sin(t*.23-1.5)+1)*Math.max(0,(numFloors-1)*3.65/2);
  characters.forEach((ch,i)=>{
    if(state.paused||!data.fresh)return;
    ch.wave=Math.max(0,ch.wave-dt);
    const bob=ch.type==='bot'&&ch.activity==='running'?Math.sin(t*2.5+i)*.035:0;
    ch.body.position.y=bob;
    // A few bots wander between their desk and the aisle; their world remains small and legible.
    if(ch.type==='bot'&&ch.activity==='running'&&ch.floor>=0){const phase=t*.24+i*2.8;ch.root.position.x=ch.home.x+Math.sin(phase)*.36;ch.root.position.z=ch.home.z+Math.sin(phase*.7)*.23;ch.root.rotation.y=Math.sin(phase)*.18;}
    if(ch.type==='human'){ch.head.rotation.y=0;if(ch.arm)ch.arm.rotation.z=ch.wave>0?-.9+Math.sin(t*12)*.3:Math.sin(t+i)*.06;}
    else if(ch.arm)ch.arm.rotation.z=ch.wave>0?-.9+Math.sin(t*13)*.3:ch.activity==='running'?Math.sin(t*2+i)*.13:0;
    ch.halo.material.opacity=state.selected===ch?.7:0;
  });
  cloudGroups.forEach((c,i)=>c.position.x=-38+i*13+Math.sin(t*.018+i)*2.5);
  flag.rotation.y=Math.sin(t*1.2)*.11;
  if(state.selected){const p=project(state.selected.root.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,1.9,0)));$('#speech').style.left=THREE.MathUtils.clamp(p.x,125,innerWidth-125)+'px';$('#speech').style.top=Math.max(230,p.y)+'px';}
  labels();personLabels();renderer.render(scene,camera);frames++;
  if(frames===3){$('#loading').classList.add('gone');loadingTimer=setTimeout(()=>$('#loading').hidden=true,700);document.body.dataset.sceneReady='true';}
  frameId=requestAnimationFrame(animate);
}
on(document,'visibilitychange',()=>{if(!document.hidden&&!frameId){last=0;frameId=requestAnimationFrame(animate);}});
const remembered=DEPTS.findIndex(d=>d.key===preferences.floorId);
setFloor(remembered>=0?remembered:null);pause(state.paused);
document.body.classList.toggle('night',state.night);$('#light').innerHTML=state.night?icons.moon:icons.sun;
function updatePaging(){
  const dept=state.floor===null?null:DEPTS[state.floor];const count=dept?.members.length||0;
  $('#occupant-pages').hidden=!dept||count<=6;
  $('#occupant-range').textContent=dept?`${dept.page*6+1}–${Math.min(count,dept.page*6+6)} of ${count}`:'';
  $('#occupants-prev').disabled=!dept||dept.page===0;$('#occupants-next').disabled=!dept||(dept.page+1)*6>=count;
}
function pageMembers(delta){const dept=DEPTS[state.floor];if(!dept)return;dept.page=Math.max(0,Math.min(Math.ceil(dept.members.length/6)-1,dept.page+delta));closeSpeech();populate(dept);memberLabels();updatePaging();renderer.shadowMap.needsUpdate=true;}
$('#occupants-prev').onclick=()=>pageMembers(-1);$('#occupants-next').onclick=()=>pageMembers(1);
frameId=requestAnimationFrame(animate);
return {
  select(key){if(key===null){setFloor(null);return;}const id=DEPTS.findIndex(d=>d.key===key);if(id>=0)setFloor(id);},
  update(next){data=next;for(const dept of DEPTS){const current=next.groups.find(g=>g.key===dept.key);if(current)dept.members=current.members;}
    for(const ch of characters){const member=next.groups.flatMap(g=>g.members).find(m=>m.id===ch.actorId);if(member){ch.activity=member.state;ch.message=member.detail;ch.href=member.href;}}
    for(const ch of characters){const b=$$('[data-person]').find(b=>b.dataset.person===ch.actorId);if(b){b.dataset.state=ch.activity;b.setAttribute('aria-label',ch.name+' · '+ch.message);}}
    if(state.floor!==null){const d=DEPTS[state.floor];$('#floor-subtitle').textContent=d.members.length+' teammates · '+d.members.filter(m=>m.state==='running').length+' bots running';}
    if(state.selected)sayHi(state.selected);
  },
  dispose(){controller.abort();clearTimeout(loadingTimer);cancelAnimationFrame(frameId);scene.traverse(o=>{if(o.geometry)resources.add(o.geometry);if(o.material){resources.add(o.material);if(o.material.map)resources.add(o.material.map);}});geos.forEach(g=>resources.add(g));mats.forEach(m=>resources.add(m));resources.forEach(r=>r.dispose?.());renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();}
};
}
