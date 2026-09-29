// Isolated regression test for tablet page session ownership (no renderer/device).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const elements = new Map(), events = {}, timers = new Map();
let timerId = 0;
const element = () => ({hidden:true,style:{},classList:{toggle(){}},addEventListener(){},
  setAttribute(){},querySelectorAll(){return []},getContext(){return {}},textContent:''});
const document = {hidden:false, querySelector(s){if(!elements.has(s)) elements.set(s,element());return elements.get(s)},
  addEventListener(k,fn){events[k]=fn}};
class Socket {
  static OPEN=1; static CLOSING=2;
  constructor(){this.readyState=0;this.sent=[];Socket.all.push(this)}
  send(x){this.sent.push(x)} close(){this.readyState=3}
}
Socket.all=[];
const context = vm.createContext({document,WebSocket:Socket,window:{devicePixelRatio:1,innerWidth:1280,innerHeight:800,
  isSecureContext:true,addEventListener(){}},navigator:{getGamepads:()=>[]},location:{protocol:'https:',host:'test'},
  performance:{now:()=>0},setInterval(){},setTimeout(fn){timers.set(++timerId,fn);return timerId},
  clearTimeout(id){timers.delete(id)},console});
vm.runInContext(fs.readFileSync(process.argv[2] || path.join(__dirname,'../static/tablet.js'),'utf8'),context);
const first=Socket.all[0];first.readyState=1;
document.hidden=true;events.visibilitychange();
assert.equal(first.readyState,3);
assert.ok(first.sent.includes('{"t":"move","f":0,"r":0}'));
assert.equal(vm.runInContext('ws',context),null);
document.hidden=false;events.visibilitychange();
const second=Socket.all[1];second.readyState=1;
first.onclose({code:1000}); // stale close must not clear the new socket
assert.equal(vm.runInContext('ws',context),second);
second.onclose({code:4001});
assert.equal(timers.size,0,'a replaced tab must not retry');
document.hidden=true;events.visibilitychange();document.hidden=false;events.visibilitychange();
const third=Socket.all[2];third.readyState=1;third.onclose({code:1006});
assert.equal(timers.size,1,'network failures should still retry');
document.hidden=true;events.visibilitychange();
assert.equal(timers.size,0,'hidden tab cancels a scheduled retry');
console.log('Tablet lifecycle: hide/resume, takeover, stale close and network retry passed');
