from flask import Flask, render_template, request, jsonify, session
import random
import json

app = Flask(__name__)
app.secret_key = 'wumpus-secret-key'


def get_neighbors(r, c, R, C):
    n = []
    if r > 0:
        n.append((r - 1, c))
    if r < R - 1:
        n.append((r + 1, c))
    if c > 0:
        n.append((r, c - 1))
    if c < C - 1:
        n.append((r, c + 1))
    random.shuffle(n)
    return n


def get_percepts(r, c, pits, wumpus, R, C):
    percepts = []

    for nr, nc in get_neighbors(r, c, R, C):
        if (nr, nc) in pits:
            percepts.append('Breeze')
            break

    for nr, nc in get_neighbors(r, c, R, C):
        if (nr, nc) == wumpus:
            percepts.append('Stench')
            break

    return percepts


def tell_kb(kb, clauses):
    steps = 0
    for cl in clauses:
        kb.append(list(cl))
        steps += 1
    return steps


def resolve_two(c1, c2):
    results = []
    for lit in c1:
        comp = lit[1:] if lit.startswith('!') else '!' + lit
        if comp in c2:
            new_clause = list(set(
                [l for l in c1 if l != lit] +
                [l for l in c2 if l != comp]
            ))
            results.append(new_clause)
    return results


def resolve(clauses):
    clause_set = ['|'.join(sorted(c)) for c in clauses]
    clause_arr = [list(c) for c in clauses]

    while True:
        new_clauses = []

        for i in range(len(clause_arr)):
            for j in range(i + 1, len(clause_arr)):
                resolvents = resolve_two(clause_arr[i], clause_arr[j])

                for r in resolvents:
                    if len(r) == 0:
                        return True

                    rs = '|'.join(sorted(r))
                    if rs not in clause_set:
                        new_clauses.append(r)
                        clause_set.append(rs)

        if not new_clauses:
            return False

        clause_arr += new_clauses

        if len(clause_arr) > 800:
            return False


def ask_kb(kb, literal):
    neg = literal[1:] if literal.startswith('!') else '!' + literal
    test = [list(c) for c in kb]
    test.append([neg])
    return resolve(test)


def init_episode(R, C, num_pits):
    cells = [(r, c) for r in range(R) for c in range(C) if not (r == 0 and c == 0)]
    random.shuffle(cells)

    wumpus = cells[0]
    pits = set()

    for i in range(1, num_pits + 1):
        if i < len(cells):
            pits.add(cells[i])

    cell_states = {
        f"{r},{c}": 'unknown'
        for r in range(R)
        for c in range(C)
    }

    return wumpus, list(pits), cell_states


def enter_cell(r, c, state):
    R, C = state['R'], state['C']
    pits = [tuple(p) for p in state['pits']]
    wumpus = tuple(state['wumpus'])
    kb = state['kb']

    if (r, c) in pits:
        state['cell_states'][f"{r},{c}"] = 'danger'
        state['alive'] = False
        state['status'] = f'Episode over — Agent fell into a Pit at ({r},{c}).'
        return state

    if (r, c) == wumpus:
        state['cell_states'][f"{r},{c}"] = 'danger'
        state['alive'] = False
        state['status'] = f'Episode over — Agent was eaten by the Wumpus at ({r},{c}).'
        return state

    visited = [tuple(v) for v in state['visited']]

    if (r, c) not in visited:
        state['visited'].append([r, c])
        state['cell_states'][f"{r},{c}"] = 'safe'
        state['moves'] += 1

    percepts = get_percepts(r, c, pits, wumpus, R, C)
    state['percepts'] = percepts

    nbrs = get_neighbors(r, c, R, C)

    if 'Breeze' not in percepts:
        for nr, nc in nbrs:
            steps = tell_kb(kb, [[f'!P_{nr}_{nc}']])
            state['inference_steps'] += steps

            if state['cell_states'].get(f"{nr},{nc}") == 'unknown':
                state['cell_states'][f"{nr},{nc}"] = 'inferred'
    else:
        clause = [f'P_{nr}_{nc}' for nr, nc in nbrs]
        state['inference_steps'] += tell_kb(kb, [clause])

    if 'Stench' not in percepts:
        for nr, nc in nbrs:
            steps = tell_kb(kb, [[f'!W_{nr}_{nc}']])
            state['inference_steps'] += steps

            if state['cell_states'].get(f"{nr},{nc}") == 'unknown':
                state['cell_states'][f"{nr},{nc}"] = 'inferred'
    else:
        clause = [f'W_{nr}_{nc}' for nr, nc in nbrs]
        state['inference_steps'] += tell_kb(kb, [clause])

    visited_keys = [f"{v[0]},{v[1]}" for v in state['visited']]

    for nr, nc in nbrs:
        if f"{nr},{nc}" not in visited_keys:
            state['inference_steps'] += 1
            sp = ask_kb(kb, f'!P_{nr}_{nc}')
            state['inference_steps'] += 1
            sw = ask_kb(kb, f'!W_{nr}_{nc}')

            if sp and sw and state['cell_states'].get(f"{nr},{nc}") != 'safe':
                state['cell_states'][f"{nr},{nc}"] = 'inferred'

    state['agent'] = [r, c]
    state['status'] = f'Agent at ({r},{c}). Percepts: {", ".join(percepts) if percepts else "None"}'

    return state


def step_agent(state):
    if not state['running'] or not state['alive']:
        return state

    r, c = state['agent']
    R, C = state['R'], state['C']
    kb = state['kb']

    visited_keys = [f"{v[0]},{v[1]}" for v in state['visited']]
    nbrs = get_neighbors(r, c, R, C)

    unvisited = [(nr, nc) for nr, nc in nbrs if f"{nr},{nc}" not in visited_keys]

    if not unvisited:
        all_inferred = [
            (int(k.split(',')[0]), int(k.split(',')[1]))
            for k, v in state['cell_states'].items()
            if v == 'inferred' and k not in visited_keys
        ]

        if not all_inferred:
            state['status'] = 'Episode complete — no more safe cells to explore.'
            state['running'] = False
            return state

        nr, nc = all_inferred[0]
        state['agent'] = [nr, nc]
        return enter_cell(nr, nc, state)

    safe = [(nr, nc) for nr, nc in unvisited if state['cell_states'].get(f"{nr},{nc}") == 'inferred']

    if safe:
        nr, nc = safe[0]
        state['agent'] = [nr, nc]
        return enter_cell(nr, nc, state)

    proven = []

    for nr, nc in unvisited:
        state['inference_steps'] += 1
        sp = ask_kb(kb, f'!P_{nr}_{nc}')
        state['inference_steps'] += 1
        sw = ask_kb(kb, f'!W_{nr}_{nc}')

        if sp and sw:
            proven.append((nr, nc))

    if proven:
        nr, nc = proven[0]
        state['agent'] = [nr, nc]
        return enter_cell(nr, nc, state)

    state['status'] = 'Agent halted — no provably safe move available.'
    state['running'] = False
    return state


def safe_response(state):
    danger_cells = [k for k, v in state['cell_states'].items() if v == 'danger']
    visible_pits = [p for p in state['pits'] if f"{p[0]},{p[1]}" in danger_cells]

    w = state['wumpus']
    visible_wumpus = state['wumpus'] if f"{w[0]},{w[1]}" in danger_cells else None

    return {
        'R': state['R'],
        'C': state['C'],
        'agent': state['agent'],
        'alive': state['alive'],
        'running': state['running'],
        'cell_states': state['cell_states'],
        'visited': state['visited'],
        'percepts': state['percepts'],
        'inference_steps': state['inference_steps'],
        'moves': state['moves'],
        'status': state['status'],
        'pits': visible_pits,
        'wumpus': visible_wumpus
    }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/start', methods=['POST'])
def start():
    data = request.json

    R = max(3, int(data.get('rows', 4)))
    C = max(3, int(data.get('cols', 4)))
    num_pits = max(1, min(R * C - 3, int(data.get('pits', 3))))

    wumpus, pits, cell_states = init_episode(R, C, num_pits)

    state = {
        'R': R,
        'C': C,
        'wumpus': list(wumpus),
        'pits': [list(p) for p in pits],
        'cell_states': cell_states,
        'kb': [],
        'visited': [],
        'agent': [0, 0],
        'percepts': [],
        'inference_steps': 0,
        'moves': 0,
        'alive': True,
        'running': True,
        'status': 'Episode started. Agent enters (0,0).'
    }

    state = enter_cell(0, 0, state)
    session['state'] = json.dumps(state)

    return jsonify(safe_response(state))


@app.route('/step', methods=['POST'])
def step():
    state = json.loads(session.get('state', '{}'))

    if not state:
        return jsonify({'error': 'No episode running'}), 400

    state = step_agent(state)
    session['state'] = json.dumps(state)

    return jsonify(safe_response(state))

import os

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)