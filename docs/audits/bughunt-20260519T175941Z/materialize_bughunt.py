#!/usr/bin/env python3
import json, subprocess, pathlib, shlex, sys
repo=pathlib.Path("/home/hermes/code/trade-trace")
run="20260519T175941Z"
run_dir=repo/f"docs/audits/bughunt-{run}"
rows=json.loads((run_dir/'candidate_matrix.json').read_text())
label='bughunt:exhaustive-refresh-20260519'

def bd(*args, check=True):
    res=subprocess.run(['bd', *args], cwd=repo, text=True, capture_output=True)
    print('$ bd ' + ' '.join(shlex.quote(str(a)) for a in args))
    if res.stdout: print(res.stdout.rstrip())
    if res.stderr: print(res.stderr.rstrip(), file=sys.stderr)
    if check and res.returncode != 0:
        raise SystemExit(f'bd failed {res.returncode}: {args}')
    return res.stdout.strip()

def relate(a,b):
    bd('dep','relate',a,b,check=False)

epic=bd('create','EPIC: exhaustive repo bughunt refresh 2026-05-19T175941Z','--type','epic','--priority','P2','--labels','bughunt,bughunt:exhaustive-refresh-20260519','--body-file',str(run_dir/'epic_body.md'),'--acceptance','Relation-based bughunt epic remains open while related bug findings are open; artifacts and final verification readbacks are durable.','--silent')
(run_dir/'epic_id.txt').write_text(epic+'\n')
gate=bd('create','Final verification: exhaustive bughunt refresh 2026-05-19T175941Z','--type','task','--priority','P2','--labels','bughunt,bughunt-gate,bughunt:exhaustive-refresh-20260519','--body-file',str(run_dir/'final_gate_body.md'),'--acceptance','Candidate disposition, Beads readbacks, duplicate scan, cycles/lint/orphans, artifact disposition, and final report are saved.','--silent')
(run_dir/'final_gate_id.txt').write_text(gate+'\n')
relate(epic, gate)
ids={'EPIC':epic,'FINAL':gate}
merge_note=(
    f"Repo-bughunt refresh {run}: CAND-003 merged here instead of creating a duplicate. "
    f"Additional evidence saved in docs/audits/bughunt-{run}/primary_evidence.txt: "
    "default_registry has 66 tools, 55 missing registry json_schema / empty MCP inputSchema; "
    "`tt tool schema --tool memory.recall` returns json_schema null. "
    "This is the systemic version of the same tool.schema/CLI-help failure already described here. "
    f"Related epic: {epic}."
)
bd('update','trade-trace-3i33','--add-label','bug','--add-label','bughunt','--add-label',label,'--add-label','domain:cli-contracts','--append-notes',merge_note)
relate(epic,'trade-trace-3i33')
ids['CAND-003']='trade-trace-3i33'
for r in rows:
    if r['coordinator_disposition']!='accept' or r['id']=='CAND-003':
        continue
    body=run_dir/'bead-bodies'/(r['id']+'.md')
    labels=','.join(r['proposed_labels'])
    acc='; '.join(r['acceptance_criteria'])
    new_id=bd('create',r['proposed_bead_title'],'--type','bug','--priority',r['severity'],'--labels',labels,'--body-file',str(body),'--acceptance',acc,'--silent')
    ids[r['id']]=new_id
    relate(epic,new_id)
    for rel in r.get('related_to') or []:
        if str(rel).startswith('trade-trace-'):
            relate(new_id, rel)
(run_dir/'candidate_to_bead_map.json').write_text(json.dumps(ids, indent=2)+'\n')
for r in rows:
    if r['id'] in ids:
        if r['id']=='CAND-003': r['merged_into_bead_id']=ids[r['id']]
        else: r['materialized_bead_id']=ids[r['id']]
(run_dir/'candidate_matrix.json').write_text(json.dumps(rows, indent=2)+'\n')
print(json.dumps(ids, indent=2))
