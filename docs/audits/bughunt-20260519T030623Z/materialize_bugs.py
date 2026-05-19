#!/usr/bin/env python3
from __future__ import annotations
import json, subprocess, pathlib, shutil, sys
ROOT = pathlib.Path('/home/hermes/code/trade-trace')
BASE = ROOT / 'docs/audits/bughunt-20260519T030623Z'
EPIC = 'trade-trace-2d3'
bd = shutil.which('bd')
if not bd:
    raise SystemExit('bd not found')
with open(BASE / 'candidate_matrix.json') as f:
    matrix = json.load(f)
accepted = [c for c in matrix['candidates'] if c.get('coordinator_disposition') == 'accept']
body_dir = BASE / 'bead-bodies'
body_dir.mkdir(parents=True, exist_ok=True)
id_map = {}
commands = []

def run(args):
    commands.append(args)
    p = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if p.returncode != 0:
        print('COMMAND FAILED:', args, file=sys.stderr)
        print(p.stdout, file=sys.stderr)
        print(p.stderr, file=sys.stderr)
        raise SystemExit(p.returncode)
    return p.stdout.strip()

for c in accepted:
    title = c['proposed_bead_title']
    lookup = subprocess.run([bd, 'list', '--title', title, '--status', 'open,in_progress,blocked', '--flat', '--limit', '0', '--sort', 'id'], cwd=ROOT, text=True, capture_output=True)
    existing = None
    for line in lookup.stdout.splitlines():
        for part in line.split():
            if part.startswith('trade-trace-'):
                existing = part
                break
        if existing:
            break
    if existing:
        issue_id = existing
    else:
        body = (
            'Context:\n' + c['source_lane'] + ' / ' + ', '.join(c.get('subsystem_paths', [])) + '\n\n'
            'Observed behavior:\n' + c['observed_behavior'] + '\n\n'
            'Expected behavior:\n' + c['expected_behavior'] + '\n\n'
            'Evidence:\n' + c['evidence'] + '\n\n'
            'Failure mode / impact:\n' + c['impact'] + '\n\n'
            '## Steps to Reproduce\n' + c['validation_command'] + '\n\n'
            'Duplicate check:\nCompared against existing open Beads and the exhaustive bughunt candidate matrix after `bd find-duplicates` preflight. Not a duplicate because this candidate has a distinct root cause/failure mode/fix surface. Possible overlap: ' + str(c.get('duplicate_of') or 'none') + '.\n\n'
            'Suggested fix direction:\nImplement the smallest fix that makes observed behavior match the stated contract. For static-only candidates, first add a failure-injection or targeted regression test proving the risk.\n\n'
            'Validation:\n' + c['validation_command'] + '\n\n'
            'Acceptance criteria:\n' + ''.join('- ' + a + '\n' for a in c.get('acceptance_criteria', [])) + '\n'
            'Provenance:\nDiscovered by repo-bughunt candidate ' + c['id'] + ' in domain ' + c['source_lane'] + '.\n'
            'Advisor gate: ' + str(c.get('advisor_gate', 'n/a')) + '.\n'
            'Disposition reason: ' + str(c.get('disposition_reason', '')) + '.\n'
        )
        body_path = body_dir / (c['id'] + '.md')
        body_path.write_text(body)
        labels = ','.join(c['proposed_labels'])
        acceptance = '; '.join(c.get('acceptance_criteria', []))[:2000]
        issue_id = run([bd, 'create', title, '--type', 'bug', '--priority', c['severity'], '--labels', labels, '--body-file', str(body_path), '--acceptance', acceptance, '--silent'])
    id_map[c['id']] = issue_id
    rel = subprocess.run([bd, 'dep', 'relate', EPIC, issue_id], cwd=ROOT, text=True, capture_output=True)
    commands.append([bd, 'dep', 'relate', EPIC, issue_id])
    if rel.returncode != 0 and 'already' not in (rel.stdout + rel.stderr).lower() and 'exists' not in (rel.stdout + rel.stderr).lower():
        print('RELATE FAILED:', rel.stdout, rel.stderr, file=sys.stderr)
        raise SystemExit(rel.returncode)
rel = subprocess.run([bd, 'dep', 'relate', EPIC, 'trade-trace-w9r'], cwd=ROOT, text=True, capture_output=True)
commands.append([bd, 'dep', 'relate', EPIC, 'trade-trace-w9r'])
(BASE / 'candidate_to_bead_map.json').write_text(json.dumps(id_map, indent=2) + '\n')
(BASE / 'materialization_commands.json').write_text(json.dumps(commands, indent=2) + '\n')
for c in matrix['candidates']:
    if c.get('id') in id_map:
        c['materialized_bead_id'] = id_map[c['id']]
    if c.get('merged_into_bead_id') in id_map:
        c['merged_into_bead_id'] = id_map[c['merged_into_bead_id']]
(BASE / 'candidate_matrix.json').write_text(json.dumps(matrix, indent=2) + '\n')
print(json.dumps(id_map, indent=2))
