// Interactive walkthrough controller for ABC synthesis operators.
// Loads a per-operator JSON describing a sequence of "steps", each of which
// applies CSS classes to base-SVG elements and renders side-pane state.

'use strict';

const state = {
    op: null,        // current operator JSON
    svg: null,       // SVG root element
    step: 0,         // current step index
};

const HIGHLIGHT_CLASSES = [
    'cut-leaf', 'in-mffc', 'considering', 'replacement-new',
    'fanout-protected', 'dimmed', 'active'
];

async function loadOperator(name) {
    try {
        const op = await fetch(`operators/${name}.json`).then(r => {
            if (!r.ok) throw new Error(`fetch ${name}.json: ${r.status}`);
            return r.json();
        });
        const svgText = await fetch(`diagrams/${op.circuit}.svg`).then(r => {
            if (!r.ok) throw new Error(`fetch ${op.circuit}.svg: ${r.status}`);
            return r.text();
        });
        document.getElementById('svg-container').innerHTML = svgText;
        state.svg = document.querySelector('#svg-container svg');
        state.op = op;
        state.step = 0;
        render();
    } catch (e) {
        document.getElementById('svg-container').textContent = `Error: ${e.message}`;
        console.error(e);
    }
}

function render() {
    const op = state.op;
    if (!op) return;
    const step = op.steps[state.step];

    document.getElementById('step-indicator').textContent =
        `Step ${state.step + 1} / ${op.steps.length}`;
    document.getElementById('step-title').textContent = step.title || '';
    document.getElementById('btn-prev').disabled = state.step === 0;
    document.getElementById('btn-next').disabled = state.step === op.steps.length - 1;

    // Clear all dynamic classes from SVG elements
    state.svg.querySelectorAll('[id^="node-"], [id^="edge-"]').forEach(el => {
        el.classList.remove(...HIGHLIGHT_CLASSES);
    });

    // Apply step's highlights
    for (const [id, cls] of Object.entries(step.highlights || {})) {
        const el = state.svg.querySelector(`[id="${id}"]`);
        if (!el) {
            console.warn(`No SVG element with id="${id}"`);
            continue;
        }
        const classes = Array.isArray(cls) ? cls : [cls];
        el.classList.add(...classes);
    }

    // Narrative
    const narrEl = document.getElementById('narrative');
    narrEl.innerHTML = step.narrative || '';

    // Side panes
    const panesEl = document.getElementById('state-panes');
    panesEl.innerHTML = '';
    for (const pane of step.panes || []) {
        panesEl.appendChild(renderPane(pane));
    }
}

function renderPane(pane) {
    const div = document.createElement('div');
    div.className = 'pane';
    if (pane.title) {
        const h = document.createElement('h3');
        h.textContent = pane.title;
        div.appendChild(h);
    }
    switch (pane.type) {
        case 'table':       return renderTable(div, pane);
        case 'list':        return renderList(div, pane);
        case 'kv':          return renderKV(div, pane);
        case 'text':        return renderText(div, pane);
        case 'formula':     return renderFormula(div, pane);
        default:
            div.appendChild(document.createTextNode(`[unknown pane type: ${pane.type}]`));
            return div;
    }
}

function renderTable(div, pane) {
    const t = document.createElement('table');
    if (pane.header) {
        const thead = document.createElement('thead');
        const tr = document.createElement('tr');
        for (const h of pane.header) {
            const th = document.createElement('th');
            th.innerHTML = h;
            tr.appendChild(th);
        }
        thead.appendChild(tr);
        t.appendChild(thead);
    }
    const tbody = document.createElement('tbody');
    for (const row of pane.rows) {
        const tr = document.createElement('tr');
        if (row._cls) tr.className = row._cls;
        const cells = row._cells || row;
        for (const cell of cells) {
            const td = document.createElement('td');
            td.innerHTML = cell;
            tr.appendChild(td);
        }
        tbody.appendChild(tr);
    }
    t.appendChild(tbody);
    div.appendChild(t);
    return div;
}

function renderList(div, pane) {
    const ul = document.createElement('ul');
    if (!pane.items || pane.items.length === 0) ul.classList.add('empty');
    for (const item of (pane.items || [])) {
        const li = document.createElement('li');
        li.innerHTML = item;
        ul.appendChild(li);
    }
    div.appendChild(ul);
    return div;
}

function renderKV(div, pane) {
    const dl = document.createElement('dl');
    for (const [k, v] of Object.entries(pane.entries || {})) {
        const dt = document.createElement('dt');
        dt.textContent = k;
        const dd = document.createElement('dd');
        dd.innerHTML = v;
        dl.appendChild(dt);
        dl.appendChild(dd);
    }
    div.appendChild(dl);
    return div;
}

function renderText(div, pane) {
    const p = document.createElement('div');
    p.innerHTML = pane.body || '';
    div.appendChild(p);
    return div;
}

function renderFormula(div, pane) {
    const p = document.createElement('div');
    p.className = 'formula';
    p.innerHTML = pane.body || '';
    div.appendChild(p);
    return div;
}

// Wire up controls
document.getElementById('btn-prev').addEventListener('click', () => {
    if (state.step > 0) { state.step--; render(); }
});
document.getElementById('btn-next').addEventListener('click', () => {
    if (state.op && state.step < state.op.steps.length - 1) { state.step++; render(); }
});
document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    if (e.key === 'ArrowLeft')  document.getElementById('btn-prev').click();
    if (e.key === 'ArrowRight') document.getElementById('btn-next').click();
});
document.getElementById('operator-select').addEventListener('change', (e) => {
    loadOperator(e.target.value);
});

// Initial load
loadOperator('rewrite');
