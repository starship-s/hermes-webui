"""Execute the shipped draft helpers across navigation/reload and request races."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(scenario):
    node = shutil.which('node')
    if not node:
        pytest.skip('node not available')
    source = (ROOT / 'static/sessions.js').read_text(encoding='utf-8')
    helpers = source[source.index('let _draftSaveTimer = null;'):
                     source.index('const SESSION_VIEWED_COUNTS_KEY =')]
    script = r'''
const vm = require('node:vm');
const storage = new Map();
const storageAPI = {
  getItem: k => storage.get(k) || null,
  setItem: (k,v) => storage.set(k,v),
  removeItem: k => storage.delete(k),
};
function page(profile='default') {
  const input = {value: ''};
  const S = {activeProfile: profile, session: {session_id:'old',profile}, pendingFiles:[]};
  const calls = [];
  const ctx = vm.createContext({S, sessionStorage:storageAPI, localStorage:storageAPI,
    $:()=>input, window:{}, _loadingSessionId:null, clearTimeout,setTimeout,
    console:{warn(){}}, autoResize(){}, updateSendBtn(){}, renderTray(){},
    api:(path,opts)=>new Promise((resolve,reject)=>calls.push({resolve,reject,opts})),
  });
  vm.runInContext(HELPERS,ctx);
  return {ctx,S,input,calls,run:code=>vm.runInContext(code,ctx)};
}
function restore(p,text='server old') {
  p.input.value='';
  p.run('_restoreComposerDraft('+JSON.stringify({text,files:[]})+',"old")');
  return p.input.value;
}
(async()=>{
const p=page();
const output={};
''' + scenario + r'''
process.stdout.write(JSON.stringify(output));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run([node, '-e', 'const HELPERS='+json.dumps(helpers)+';\n'+script],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('reload', [False, True])
def test_failed_save_survives_return_or_reload_without_cross_profile_leak(reload):
    result = _run('''
const pending=p.run('_saveComposerDraftNow("old","unsaved text",[{name:"a.txt",path:"/uploaded/a.txt"}])');
p.calls[0].reject(Object.assign(new Error('offline'),{status:503}));
try{await pending}catch(e){p.ctx.failure=e;p.run('_handleComposerDraftPostFailure(failure,"old","unsaved text",[])')}
// A different session's composer must not inherit this pending payload.
p.S.session={session_id:'target',profile:'default'};
p.input.value='target draft';
p.run('_restoreComposerDraft({text:"target draft",files:[]},"target")');
output.target=p.input.value;
p.S.session={session_id:'old',profile:'default'};
const returning=''' + ('page()' if reload else 'p') + ''';
output.restored=restore(returning);
output.files=returning.S.pendingFiles;
output.foreign=restore(page('foreign'));
output.otherFiles=page('foreign').S.pendingFiles;
''')
    assert result['target'] == 'target draft'
    assert result['restored'] == 'unsaved text'
    assert result['files'][0]['path'] == '/uploaded/a.txt'
    assert result['foreign'] == 'server old'
    assert result['otherFiles'] == []


def test_stale_success_cannot_erase_newer_failed_recovery():
    result = _run('''
const first=p.run('_saveComposerDraftNow("old","older",[])');
const second=p.run('_saveComposerDraftNow("old","newer",[])');
p.calls[1].reject(new Error('offline'));
try{await second}catch(e){}
p.calls[0].resolve({session_id:'old'});await first;
output.restored=restore(page());
''')
    assert result['restored'] == 'newer'


def test_confirmed_success_removes_local_override_and_clear_does_not_revive_sent_text():
    result = _run('''
const pending=p.run('_saveComposerDraftNow("old","accepted",[])');
p.calls[0].resolve({session_id:'old'});await pending;
output.afterSuccess=restore(page(),'external newer draft');
const failed=p.run('_saveComposerDraftNow("old","to send",[])');
p.calls[1].reject(new Error('offline'));try{await failed}catch(e){}
const clearing=p.run('_clearComposerDraft("old","to send",[])');
p.calls[2].resolve({session_id:'old'});await clearing;
output.afterClear=restore(page(),'');
''')
    assert result['afterSuccess'] == 'external newer draft'
    assert result['afterClear'] == ''


def test_late_failed_request_does_not_overwrite_a_newer_confirmed_draft():
    result = _run('''
const first=p.run('_saveComposerDraftNow("old","older",[])');
const second=p.run('_saveComposerDraftNow("old","newer",[])');
p.calls[1].resolve({session_id:'old'});await second;
p.calls[0].reject(new Error('late failure'));
try{await first}catch(e){p.ctx.failure=e;p.run('_handleComposerDraftPostFailure(failure,"old","older",[])')}
output.metadata=p.S.session.composer_draft.text;
output.restored=restore(page(),'newer');
''')
    assert result['metadata'] == 'newer'
    assert result['restored'] == 'newer'


def test_late_clear_ack_keeps_newer_failed_input():
    result = _run('''
const clear=p.run('_clearComposerDraft("old","sent",[])');
const newer=p.run('_saveComposerDraftNow("old","typed after send",[])');
p.calls[1].reject(new Error('offline'));try{await newer}catch(e){}
p.calls[0].resolve({session_id:'old'});await clear;
output.restored=restore(page());
''')
    assert result['restored'] == 'typed after send'


def test_denied_storage_keeps_in_memory_recovery_and_reports_refresh_limit():
    result = _run('''
let warnings=[];p.ctx.showToast=message=>warnings.push(message);
storageAPI.setItem=()=>{throw new Error('quota denied')};
const pending=p.run('_saveComposerDraftNow("old","memory only",[])');
p.calls[0].reject(new Error('offline'));try{await pending}catch(e){}
output.restored=restore(p);
output.warnings=warnings;
''')
    assert result['restored'] == 'memory only'
    assert len(result['warnings']) == 1
    assert 'refresh' in result['warnings'][0].lower()


@pytest.mark.parametrize('debounced', [False, True])
def test_in_tab_recovery_preserves_actual_unuploaded_file_bytes(debounced):
    result = _run('''
const attachment=new (require('node:buffer').File)(['attachment bytes'],'note.txt',{type:'text/plain'});
p.ctx.attachment=attachment;
''' + ('''p.run('_saveComposerDraft("old","with attachment",[attachment])');
await new Promise(resolve=>setTimeout(resolve,500));
''' if debounced else '''const pending=p.run('_saveComposerDraftNow("old","with attachment",[attachment])');
pending.catch(()=>{});
''') + '''p.calls[0].reject(new Error('offline'));
await new Promise(resolve=>setTimeout(resolve,0));
restore(p);
output.sameFile=p.S.pendingFiles[0]===attachment;
output.bytes=typeof p.S.pendingFiles[0]?.text==='function' ? await p.S.pendingFiles[0].text() : null;
output.wire=JSON.parse(p.calls[0].opts.body).files;
''')
    assert result['sameFile'] is True
    assert result['bytes'] == 'attachment bytes'
    assert result['wire'][0]['name'] == 'note.txt'
    assert 'localFiles' not in result['wire'][0]


def test_reload_warns_for_unuploaded_attachment_instead_of_faking_file_bytes():
    result = _run('''
const pending=p.run('_saveComposerDraftNow("old","with attachment",[{name:"note.txt",size:16,type:"text/plain"}])');
p.calls[0].reject(new Error('offline'));try{await pending}catch(e){}
const refreshed=page();let warnings=[];refreshed.ctx.showToast=message=>warnings.push(message);
output.restored=restore(refreshed);
output.files=refreshed.S.pendingFiles;
output.warnings=warnings;
''')
    assert result['restored'] == 'with attachment'
    assert result['files'] == []
    assert any('attachments' in message for message in result['warnings'])


@pytest.mark.parametrize('outcome', ['success', 'failure', 'clear'])
def test_request_completion_cannot_mutate_same_sid_in_a_different_profile(outcome):
    result = _run('''
const pending=p.run(''' + json.dumps('_clearComposerDraft("old","sent",[])' if outcome == 'clear'
                                    else '_saveComposerDraftNow("old","default input",[])') + ''');
p.S.activeProfile='foreign';
p.S.session={session_id:'old',profile:'foreign',composer_draft:{text:'foreign input',files:[]}};
''' + ('''p.calls[0].reject(new Error('late failure'));
try{await pending}catch(e){p.ctx.failure=e;p.run('_handleComposerDraftPostFailure(failure,"old","default input",[])')}
''' if outcome == 'failure' else '''p.calls[0].resolve({session_id:'old'});await pending;
''') + '''output.current=p.S.session.composer_draft.text;
output.foreign=restore(page('foreign'));
''')
    assert result['current'] == 'foreign input'
    assert result['foreign'] == 'server old'
