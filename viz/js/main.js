// Interactive walkthrough controller for ABC synthesis operators.
// Loads a per-operator JSON describing a sequence of "steps", each of which
// applies CSS classes to base-SVG elements and renders side-pane state.

'use strict';

const state = {
    op: null,        // current operator JSON
    svg: null,       // main SVG root element
    auxSvg: null,    // optional aux SVG root element
    auxOriginalText: null,  // map: id -> original textContent for restoring
    step: 0,         // current step index
};

const HIGHLIGHT_CLASSES = [
    'cut-leaf', 'in-mffc', 'considering', 'replacement-new',
    'fanout-protected', 'dimmed', 'active', 'hidden', 'fresh',
    'const-true', 'const-false',
    'verdict-miss', 'verdict-hit', 'verdict-fold', 'verdict-text',
    'survives'
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

        // Optional aux SVG
        const auxContainer = document.getElementById('aux-container');
        if (op.auxCircuit) {
            const auxText = await fetch(`diagrams/${op.auxCircuit}.svg`).then(r => {
                if (!r.ok) throw new Error(`fetch ${op.auxCircuit}.svg: ${r.status}`);
                return r.text();
            });
            auxContainer.innerHTML = auxText;
            auxContainer.hidden = false;
            state.auxSvg = auxContainer.querySelector('svg');
            // Snapshot original text content of every <text> with an id, so we
            // can restore on step change.
            state.auxOriginalText = new Map();
            state.auxSvg.querySelectorAll('text').forEach(t => {
                // find ancestor <g> with id (graphviz puts ids on the group)
                const g = t.closest('g[id]');
                if (g) state.auxOriginalText.set(g.id, t.textContent);
            });
        } else {
            auxContainer.innerHTML = '';
            auxContainer.hidden = true;
            state.auxSvg = null;
            state.auxOriginalText = null;
        }

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

    // Clear all dynamic classes from both SVGs
    [state.svg, state.auxSvg].filter(Boolean).forEach(svg => {
        svg.querySelectorAll('.node, .edge').forEach(el => {
            el.classList.remove(...HIGHLIGHT_CLASSES);
        });
    });

    // Restore aux text content (so a step can have textReplace and the next
    // step starts from a clean slate).
    if (state.auxSvg && state.auxOriginalText) {
        state.auxOriginalText.forEach((origText, gid) => {
            const g = state.auxSvg.querySelector(`g[id="${gid}"]`);
            if (g) {
                const t = g.querySelector('text');
                if (t) t.textContent = origText;
            }
        });
    }

    // Apply step's highlights — search both SVGs for the id
    for (const [id, cls] of Object.entries(step.highlights || {})) {
        const el = (state.svg && state.svg.querySelector(`[id="${id}"]`))
            || (state.auxSvg && state.auxSvg.querySelector(`[id="${id}"]`));
        if (!el) {
            console.warn(`No SVG element with id="${id}"`);
            continue;
        }
        const classes = Array.isArray(cls) ? cls : [cls];
        el.classList.add(...classes);
    }

    // Apply per-step text replacement on aux SVG (e.g. update request labels)
    if (step.textReplace && state.auxSvg) {
        for (const [id, newText] of Object.entries(step.textReplace)) {
            const g = state.auxSvg.querySelector(`g[id="${id}"]`);
            if (!g) {
                console.warn(`No aux SVG element with id="${id}"`);
                continue;
            }
            const t = g.querySelector('text');
            if (t) t.textContent = newText;
        }
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
        case 'tt-grid':     return renderTtGrid(div, pane);
        case 'bitvec':      return renderBitvec(div, pane);
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
    for (let row of pane.rows) {
        // Tolerate single-element wrapping: [{ _cells:[...], _cls:"..." }]
        if (Array.isArray(row) && row.length === 1 && row[0] && typeof row[0] === 'object' && !Array.isArray(row[0])) {
            row = row[0];
        }
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

// Render a 4-input truth table (16 bits) as a 4×4 grid of 0/1 cells.
// pane.tt = string of 16 chars '0' or '1' (LSB first; or reversed if pane.order=='msb-first')
// pane.label = optional caption (e.g. "0xFA88")
function renderTtGrid(div, pane) {
    if (pane.label) {
        const lab = document.createElement('div');
        lab.style.fontFamily = 'monospace';
        lab.style.fontSize = '0.85rem';
        lab.style.marginBottom = '0.3rem';
        lab.innerHTML = pane.label;
        div.appendChild(lab);
    }
    const tt = pane.tt || ''.padEnd(16, '0');
    const grid = document.createElement('div');
    grid.style.display = 'grid';
    grid.style.gridTemplateColumns = 'repeat(4, 1fr)';
    grid.style.gap = '2px';
    grid.style.maxWidth = '160px';
    for (let i = 0; i < 16; i++) {
        const idx = pane.order === 'msb-first' ? 15 - i : i;
        const bit = tt[idx];
        const cell = document.createElement('div');
        cell.textContent = bit;
        cell.style.fontFamily = 'monospace';
        cell.style.fontSize = '0.9rem';
        cell.style.padding = '4px 0';
        cell.style.textAlign = 'center';
        cell.style.background = bit === '1' ? '#b3ffc4' : '#f0f0f0';
        cell.style.color = bit === '1' ? '#1a4d22' : '#999';
        cell.style.borderRadius = '2px';
        grid.appendChild(cell);
    }
    div.appendChild(grid);
    return div;
}

// Render a bitvector as a row of cells.
// pane.bits = string of '0'/'1'
// pane.width = optional width (default fills container)
function renderBitvec(div, pane) {
    const bits = pane.bits || '';
    const wrap = document.createElement('div');
    wrap.style.fontFamily = 'monospace';
    wrap.style.fontSize = '0.75rem';
    wrap.style.letterSpacing = '0';
    wrap.style.wordBreak = 'break-all';
    wrap.style.padding = '0.4rem';
    wrap.style.background = '#f7f7f7';
    wrap.style.borderRadius = '3px';
    for (let i = 0; i < bits.length; i++) {
        const span = document.createElement('span');
        span.textContent = bits[i];
        span.style.color = bits[i] === '1' ? '#2a8b46' : '#aaa';
        span.style.fontWeight = bits[i] === '1' ? '700' : '400';
        wrap.appendChild(span);
        // group every 4 bits
        if ((i + 1) % 4 === 0 && i !== bits.length - 1) {
            wrap.appendChild(document.createTextNode(' '));
        }
    }
    div.appendChild(wrap);
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
