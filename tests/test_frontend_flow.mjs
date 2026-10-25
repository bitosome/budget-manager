import assert from 'node:assert/strict';
import {browser,tick} from './dom.mjs';
import {exampleState} from './fixtures.mjs';
await import('../custom_components/budget_manager/frontend/budget-manager-panel.js');
const Panel=customElements.get('budget-manager-panel-dev');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
let count=0;
function check(value,message){assert.ok(value,message);count++;}
function panel(){
 const p=new Panel();p._initialized=true;p._defaultViewApplied=true;p._year=2026;p._month='2026-09';p._state=exampleState();
 p.calls=[];p._hass={user:{is_admin:true},locale:{language:'en'},config:{time_zone:'UTC'},callWS:async msg=>{p.calls.push(structuredClone(msg));return structuredClone(p._state);}};
 p._load=async()=>{};document.body.append(p);return p;
}
const p=panel();const d=p._dialogs;
const current=()=>d.pages.get(d.flow.current);
const close=()=>p.shadowRoot.querySelector('.family-dialog-header button:last-child').click();
const submit=()=>current().form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
const back=()=>p.shadowRoot.querySelector('[aria-label="Back"]').click();
// Retained nested forms and one native top-layer dialog. No copied form state.
p.shadowRoot.querySelector('[data-action=settings]').focus();p._openSettings();await tick();
const parent=current(),native=p.shadowRoot.querySelector('dialog');
parent.form.querySelector('[name=cycle_end_day]').value='8';
parent.root.querySelector('#electricity-settings').click();await tick();
check(p.shadowRoot.querySelector('dialog')===native,'Nested settings retain the native dialog');
const electricity=current();electricity.root.querySelector('#electricity-history').click();await tick();
check(d.flow.stack.length===3,'Settings, electricity, and history form one navigation stack');
back();await tick();check(current()===electricity,'Back returns to retained electricity form');
back();await tick();check(current()===parent,'Back returns to retained settings');
assert.equal(parent.form.querySelector('[name=cycle_end_day]').value,'8');count++;
// A panel refresh does not destroy the modal, scroll container or focused draft field.
const input=parent.form.querySelector('[name=cycle_end_day]');input.focus();p._render();
check(p.shadowRoot.querySelector('dialog')===native,'Telemetry/panel rendering preserves dialog node');
check(p.shadowRoot.activeElement===input,'Telemetry rendering preserves editor focus');
close();check(Boolean(d.flow.confirmation),'X guards dirty whole flow');
d.flow.keepEditing();check(current()===parent,'Keep editing retains the same form');
input.focus();close();native.dispatchEvent(new Event('cancel',{cancelable:true}));
check(!d.flow.confirmation&&current()===parent,'Escape from confirmation returns to editing');
close();d.flow.discardAndContinue();await tick();check(!d.flow.active,'Discard closes entire flow');
check(p.shadowRoot.activeElement?.dataset.action==='settings','Close restores refreshed opener');
// A child save stays in its flow and does not erase unsaved parent settings.
p._openSettings();await tick();const parent2=current();parent2.form.querySelector('[name=cycle_end_day]').value='9';
parent2.root.querySelector('#electricity-settings').click();await tick();
submit();await tick();
check(current()===parent2,'Saving child returns to parent');
check(parent2.form.querySelector('[name=cycle_end_day]').value==='9','Child save preserves parent draft');
const fees=p.calls.find(msg=>msg.type==='budget_manager/update_settings')?.changes.electricity.fees;
assert.deepEqual(fees,[{name:'Grid fee',amount:5,from_month:'2026-01',to_month:'2026-12'}]);count++;
d.flow.forceClose();
// Slow saves are isolated from duplicate input and subsequently opened flows.
const slow=deferred();p._hass.callWS=async msg=>{p.calls.push(structuredClone(msg));return slow.promise;};
p._openBalanceEditor();await tick();const balance=current();balance.form.querySelector('input').value='321.25';
submit();submit();check(p._pendingWrite,'Pending write is explicit');
check(balance.form.querySelector('input').disabled,'Draft controls lock during write');
check(balance.footer.querySelector('button[type=submit]').disabled,'Duplicate save is disabled');
check(balance.form.getAttribute('aria-busy')==='true','Pending form is announced');
check(p.calls.filter(msg=>msg.type==='budget_manager/update_month').length===1,'Only one balance command dispatched');
close();check(!d.flow.active,'An already dispatched save can be dismissed');
p._openSettings();await tick();const reopened=current();
check(reopened.form.querySelector('input').disabled,'A new form explains and locks while a previous write finishes');
check(d.flow.notice.includes('Saving'),'Pending state is visible in reopened flow');
slow.resolve({});await tick();await tick();
check(current()===reopened,'Old completion cannot close a newly opened flow');
check(!reopened.form.querySelector('input').disabled,'New form unlocks after response');
assert.deepEqual(p.calls.find(msg=>msg.type==='budget_manager/update_month'),{type:'budget_manager/update_month',month:'2026-09',changes:{account_balance:321.25}});count++;
d.flow.forceClose();
// Asynchronous errors stay visible even when the originating modal was closed.
const fail=deferred();p._hass.callWS=async()=>fail.promise;p._openBalanceEditor();await tick();submit();close();p._openSettings();await tick();
fail.reject(new Error('Example save rejected'));await tick();await tick();
check(current().form.querySelector('.form-status').textContent==='Example save rejected','Late error is visible in current dialog');
d.flow.forceClose();
// Destructive and recurrence scope cancellation performs no mutation.
p.calls=[];p._hass.callWS=async msg=>{p.calls.push(msg);return{};};
p._openItemEditor('example-item');await tick();
current().root.querySelector('#delete-item').click();await tick();
check(d.flow.stack.length===2,'Delete uses shared child confirmation');
back();await tick();check(p.calls.length===0,'Cancel destructive choice sends no deletion');
current().form.querySelector('[name=amount]').value='42';submit();await tick();
check(current().title==='Save changes','Recurring save requests exact scope before write');
close();check(d.flow.confirmation,'X from a scope choice guards the dirty parent');
d.flow.discardAndContinue();await tick();check(p.calls.length===0,'Closing scope selection cancels write');
check(!d.flow.active,'Canceled operation does not reopen dialog');
// File reads cannot insert a confirmation into a subsequently opened flow.
p._openSettings();await tick();const importPage=current(), fileRead=deferred();
const importTask=p._importData({size:2,text:()=>fileRead.promise},{isActive:()=>current()===importPage,close:()=>d.flow.forceClose()});
d.flow.forceClose();p._openBalanceEditor();await tick();const untouched=current();
fileRead.resolve(JSON.stringify({format:'budget-manager',version:1}));await importTask;
check(current()===untouched&&d.flow.stack.length===1,'Late budget file read cannot change a newer flow');
check(p.calls.length===0,'Late budget file read cannot dispatch an import');d.flow.forceClose();
p._openElectricityHistory();await tick();const historyFile=current().root.querySelector('#electricity-history-file'), historyRead=deferred();
Object.defineProperty(historyFile,'files',{value:[{size:2,text:()=>historyRead.promise}]});
const historyTask=historyFile.onchange();d.flow.forceClose();p._openBalanceEditor();await tick();const newer=current();
historyRead.resolve(JSON.stringify({format:'budget-manager-electricity-history',version:1,records:[]}));await historyTask;
check(current()===newer&&d.flow.stack.length===1,'Late history import cannot replace a newer form');d.flow.forceClose();
// Native cancellation is owned by shared controller, teardown releases native layer.
p._openSettings();await tick();const cancel=new Event('cancel',{cancelable:true});p.shadowRoot.querySelector('dialog').dispatchEvent(cancel);
check(cancel.defaultPrevented&&!d.flow.active,'Native Escape closes a clean form through controller');
p._openSettings();await tick();p.remove();check(!d.flow.active,'Panel teardown clears active flow');
await browser.happyDOM.abort();
console.log(`${count} Budget shared-flow checks passed`);
