"""Cloud job preparation, validation and Git delivery. No model or sending calls."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from datetime import datetime
from zoneinfo import ZoneInfo

RUN = Path('.radar-run')
COMMAND = Path('.claude/commands/run-analysis.md')


def git(*args, check=True):
    return subprocess.run(['git', *args], check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def report(text):
    print(text, flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as out:
            out.write(text + '\n')


def plan_for(day, text):
    section = re.search(r'## Шаг 1:.*?(?=## Шаг 2:)', text, re.S)
    if not section:
        raise ValueError('Analysis step not found')
    tasks = re.findall(r'\*\*Задание для (analyst-[a-z0-9-]+):\*\*\s*\n((?:>[^\n]*(?:\n|$))+)', section[0])
    if not tasks or len({name for name, _ in tasks}) != len(tasks):
        raise ValueError('Missing or duplicate analyst tasks')
    analysts = []
    for name, task in tasks:
        instruction = Path(f'.claude/agents/{name}.md')
        if not instruction.is_file():
            raise ValueError(f'Missing instruction: {name}')
        outputs = re.findall(r'data/analysis/(?:ДАТА|YYYY-MM-DD)-([a-z0-9-]+)\.md', task)
        if len(set(outputs)) != 1:
            raise ValueError(f'Ambiguous output: {name}')
        analysts.append({'name': name, 'task': task.replace('ДАТА', day),
                         'path': f'data/analysis/{day}-{outputs[0]}.md'})
    if not Path('.claude/agents/digest-composer.md').is_file():
        raise ValueError('Missing composer instruction')
    return {'date': day, 'analysts': analysts, 'digest': f'digests/{day}-digest.md'}


def prepare():
    day = datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()
    RUN.mkdir(exist_ok=True)
    ready = False
    for attempt in range(21):
        git('pull', '--ff-only', 'origin', 'master')
        if Path(f'digests/{day}-digest.md').is_file():
            (RUN / 'plan.json').write_text(json.dumps({'date': day, 'skip': True}), encoding='utf-8')
            report(f'{day}: digest already exists in master; skipped.')
            break
        if list(Path('data/processed').glob(f'{day}-*-processed.json')):
            plan = plan_for(day, COMMAND.read_text(encoding='utf-8'))
            plan['base'] = git('rev-parse', 'HEAD').stdout.strip()
            (RUN / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
            ready = True
            report(f'{day}: input ready, {len(plan["analysts"])} analysts.')
            break
        if attempt == 20:
            raise RuntimeError(f'{day}: no processed files after 100 minutes')
        print(f'{day}: waiting for input ({attempt + 1}/20)', flush=True)
        time.sleep(300)
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
        out.write(f'ready={str(ready).lower()}\n')


def paths_for(plan):
    return [a['path'] for a in plan['analysts']] + [plan['digest']]


def validate():
    plan = json.loads((RUN / 'plan.json').read_text(encoding='utf-8'))
    expected = set(paths_for(plan))
    if git('rev-parse', 'HEAD').stdout.strip() != plan['base']:
        raise RuntimeError('Agent changed commit history')
    tracked = git('diff', 'HEAD', '--name-only').stdout.splitlines()
    untracked = git('ls-files', '--others', '--exclude-standard').stdout.splitlines()
    unexpected = {p for p in tracked + untracked if p not in expected and not p.startswith('.radar-run/')}
    if unexpected:
        raise RuntimeError(f'Unexpected changes: {sorted(unexpected)}')
    counts = {}
    for path in expected:
        src = Path(path)
        if src.is_symlink() or not src.is_file() or not src.read_text(encoding='utf-8').strip():
            raise RuntimeError(f'Missing, empty or unsafe output: {path}')
        target = RUN / 'result' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    for analyst in plan['analysts']:
        content = Path(analyst['path']).read_text(encoding='utf-8')
        counts[analyst['name']] = len(set(re.findall(r'https://t\.me/[^\s)]+', content)))
    plan['counts'] = counts
    (RUN / 'validated.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    report(f'Validated {plan["date"]}: {counts}. Digest: {plan["digest"]}')


def save():
    plan = json.loads((RUN / 'plan.json').read_text(encoding='utf-8'))
    if plan.get('skip'):
        report(f'{plan["date"]}: already present; nothing to save.')
        return
    plan = json.loads((RUN / 'validated.json').read_text(encoding='utf-8'))
    # Rebuild the allowlist from trusted instructions in the fresh checkout.
    expected = plan_for(plan['date'], COMMAND.read_text(encoding='utf-8'))
    if paths_for(plan) != paths_for(expected):
        raise RuntimeError('Output plan differs from current instructions')
    token = os.environ['GH_TOKEN']
    auth = base64.b64encode(f'x-access-token:{token}'.encode()).decode()
    os.environ.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
                      GIT_CONFIG_VALUE_0=f'AUTHORIZATION: basic {auth}')
    git('pull', '--ff-only', 'origin', 'master')
    if Path(plan['digest']).is_file():
        report(f'{plan["date"]}: another run already saved digest to master; skipped.')
        return
    for path in paths_for(plan):
        if Path(path).exists():
            raise RuntimeError(f'Refusing to overwrite existing section: {path}')
        src = RUN / 'result' / path
        if src.is_symlink() or not src.is_file() or not src.read_text(encoding='utf-8').strip():
            raise RuntimeError(f'Invalid artifact: {path}')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, path)
    git('config', 'user.name', 'github-actions[bot]')
    git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    git('add', '--', *paths_for(plan))
    git('commit', '-m', f'Analysis and digest for {plan["date"]}')
    original = git('rev-parse', 'HEAD').stdout.strip()
    try:
        git('pull', '--rebase', 'origin', 'master')
        git('push', 'origin', 'HEAD:master')
    except subprocess.CalledProcessError:
        branch = f'codex/radar-{plan["date"]}-{os.environ.get("GITHUB_RUN_ID", "manual")}'
        fallback = git('push', 'origin', f'{original}:refs/heads/{branch}', check=False)
        report(f'master NOT updated. Backup branch {branch}: {"saved" if fallback.returncode == 0 else "failed"}.')
        raise RuntimeError('Delivery to master failed; inspect GitHub permissions or conflicts') from None
    git('fetch', 'origin', 'master')
    commit = git('rev-parse', 'HEAD').stdout.strip()
    git('merge-base', '--is-ancestor', commit, 'origin/master')
    git('cat-file', '-e', f'origin/master:{plan["digest"]}')
    report(f'Date: {plan["date"]}\nIncluded posts by analyst: {plan["counts"]}\nDigest: {plan["digest"]}\nCommit: {commit}\nBranch: master (verified in origin/master).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['prepare', 'validate', 'save'])
    args = parser.parse_args()
    try:
        globals()[args.phase]()
    except subprocess.CalledProcessError as error:
        # Git diagnostics may contain authentication details; do not print stderr.
        report(f'Git operation failed (exit {error.returncode}).')
        raise SystemExit(1)
