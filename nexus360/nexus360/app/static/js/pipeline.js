/* CRM & Pipeline frontend controller (WP2) */
(function () {
  const STAGE_LABELS = {
    qualification: 'Qualification',
    discovery: 'Discovery',
    proposal: 'Proposal',
    negotiation: 'Negotiation',
    contract_review: 'Contract Review',
    closed_won: 'Closed Won',
    closed_lost: 'Closed Lost',
  };

  let meta = null;
  let allOpps = [];
  let allLeads = [];
  let currentOppDetail = null;
  let stageChart = null;
  let maturityChart = null;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const money = (n) => '$' + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });

  function showToast(msg, type = 'success') {
    const el = $('pipeline-toast');
    el.textContent = msg;
    el.className = `p3-toast ${type}`;
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add('hidden'), 4500);
  }

  function openModal(id) { $(id).classList.remove('hidden'); }
  function closeModal(id) { $(id).classList.add('hidden'); }

  function fillSelect(selectEl, items, valueKey, labelKey, emptyLabel) {
    const opts = emptyLabel !== undefined ? [`<option value="">${esc(emptyLabel)}</option>`] : [];
    for (const item of items) {
      opts.push(`<option value="${esc(item[valueKey])}">${esc(item[labelKey])}</option>`);
    }
    selectEl.innerHTML = opts.join('');
  }

  async function init() {
    meta = await api('/pipeline/api/meta');
    populateMetaControls();
    bindEvents();
    await refreshAll();
  }

  function populateMetaControls() {
    fillSelect($('filter-opp-owner'), meta.users, 'id', 'full_name', 'All Owners');
    fillSelect($('opp-account'), meta.accounts, 'id', 'company_name');
    fillSelect($('opp-product'), meta.products, 'id', 'name', '-- Optional --');
    fillSelect($('opp-owner'), meta.users, 'id', 'full_name');
    fillSelect($('lead-vertical'), meta.verticals, 'id', 'name', '-- Select --');
    fillSelect($('lead-owner'), meta.users, 'id', 'full_name');
    fillSelect($('convert-existing-account'), meta.accounts, 'id', 'company_name', '+ Create new Account from Lead');
    fillSelect($('convert-product'), meta.products, 'id', 'name', '-- Optional --');

    const stageOpts = meta.stages.map((s) => `<option value="${s}">${STAGE_LABELS[s] || s}</option>`).join('');
    $('opp-stage').innerHTML = stageOpts;
    $('detail-stage-select').innerHTML = stageOpts;

    if (meta.current_user && meta.current_user.id) {
      $('opp-owner').value = meta.current_user.id;
      $('lead-owner').value = meta.current_user.id;
    }
  }

  function bindEvents() {
    document.querySelectorAll('.p3-tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.p3-tab').forEach((b) => b.classList.remove('active'));
        document.querySelectorAll('.p3-tab-panel').forEach((p) => p.classList.remove('active'));
        btn.classList.add('active');
        $(`tab-${btn.dataset.tab}`).classList.add('active');
      });
    });

    document.querySelectorAll('[data-close]').forEach((btn) => {
      btn.addEventListener('click', () => closeModal(btn.dataset.close));
    });

    $('filter-opp-q').addEventListener('input', renderKanban);
    $('filter-opp-maturity').addEventListener('change', renderKanban);
    $('filter-opp-owner').addEventListener('change', renderKanban);
    $('btn-reset-opp-filters').addEventListener('click', () => {
      $('filter-opp-q').value = '';
      $('filter-opp-maturity').value = '';
      $('filter-opp-owner').value = '';
      renderKanban();
    });

    $('filter-lead-q').addEventListener('input', renderLeads);
    $('filter-lead-status').addEventListener('change', renderLeads);
    $('filter-lead-source').addEventListener('change', renderLeads);

    $('btn-new-opp').addEventListener('click', () => openOppModal(null));
    $('btn-new-lead').addEventListener('click', () => openLeadModal(null));
    $('btn-run-dormancy').addEventListener('click', runDormancyCheck);

    $('form-opp').addEventListener('submit', saveOppForm);
    $('form-lead').addEventListener('submit', saveLeadForm);
    $('form-convert').addEventListener('submit', submitConvertForm);
    $('convert-existing-account').addEventListener('change', () => {
      $('convert-new-account-fields').classList.toggle('hidden', Boolean($('convert-existing-account').value));
    });

    $('detail-stage-select').addEventListener('change', async () => {
      if (!currentOppDetail) return;
      await moveStage(currentOppDetail.id, $('detail-stage-select').value);
      await openOppDetail(currentOppDetail.id);
    });
    $('btn-detail-recalc').addEventListener('click', async () => {
      if (!currentOppDetail) return;
      try {
        const res = await api(`/pipeline/api/opportunities/${currentOppDetail.id}/recalculate`, { method: 'POST', body: {} });
        showToast(`Maturity recalculated: ${res.maturity.toUpperCase()} (${res.maturity_score}/100, ${res.win_probability}%)`);
        await refreshAll();
        await openOppDetail(currentOppDetail.id);
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
    $('btn-detail-edit').addEventListener('click', () => {
      if (!currentOppDetail) return;
      const opp = currentOppDetail;
      closeModal('modal-opp-detail');
      openOppModal(opp);
    });
    $('btn-detail-delete').addEventListener('click', async () => {
      if (!currentOppDetail) return;
      if (!confirm(`Delete opportunity "${currentOppDetail.name}"?`)) return;
      try {
        await api(`/pipeline/api/opportunities/${currentOppDetail.id}`, { method: 'DELETE' });
        closeModal('modal-opp-detail');
        showToast('Opportunity deleted');
        await refreshAll();
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }

  async function refreshAll() {
    try {
      const [opps, leads, analytics] = await Promise.all([
        api('/pipeline/api/opportunities'),
        api('/pipeline/api/leads'),
        api('/pipeline/api/analytics'),
      ]);
      allOpps = opps;
      allLeads = leads;
      renderKPIs(analytics.kpis);
      renderKanban();
      renderLeads();
      renderAnalytics(analytics);
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function renderKPIs(kpis) {
    $('kpi-total-pipeline').textContent = money(kpis.total_pipeline);
    $('kpi-open-count').textContent = `${kpis.open_count} active deal${kpis.open_count === 1 ? '' : 's'}`;
    $('kpi-weighted-pipeline').textContent = money(kpis.weighted_pipeline);
    $('kpi-win-rate').textContent = `${kpis.win_rate}%`;
    $('kpi-won-value').textContent = `${money(kpis.won_value)} closed won (${kpis.won_count})`;
    $('kpi-dormant-count').textContent = kpis.dormant_count;
    $('kpi-lead-conv').textContent = `Lead conversion: ${kpis.lead_conversion_rate}% (${kpis.converted_lead_count}/${kpis.lead_count})`;
    $('leads-tab-count').textContent = allLeads.length;
  }

  function filteredOpps() {
    const q = $('filter-opp-q').value.trim().toLowerCase();
    const mat = $('filter-opp-maturity').value;
    const owner = $('filter-opp-owner').value;
    return allOpps.filter((o) => {
      if (mat && o.maturity !== mat) return false;
      if (owner && String(o.owner_id || '') !== owner) return false;
      if (q && !`${o.name} ${o.company_name}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  function renderKanban() {
    const board = $('kanban-board');
    const opps = filteredOpps();
    board.innerHTML = '';

    for (const stage of meta.stages) {
      const stageOpps = opps.filter((o) => o.stage === stage);
      const total = stageOpps.reduce((s, o) => s + Number(o.amount || 0), 0);
      const weighted = stageOpps.reduce((s, o) => s + Number(o.weighted_amount || 0), 0);

      const col = document.createElement('div');
      col.className = 'kanban-col';
      col.dataset.stage = stage;
      col.innerHTML = `
        <div class="kanban-col-head">
          <div class="kanban-col-title">
            <span>${esc(STAGE_LABELS[stage] || stage)}</span>
            <span class="badge">${stageOpps.length}</span>
          </div>
          <div class="kanban-col-totals">${money(total)} &middot; Wtd ${money(weighted)}</div>
        </div>
        <div class="kanban-cards"></div>
      `;

      col.addEventListener('dragover', (e) => {
        e.preventDefault();
        col.classList.add('drag-over');
      });
      col.addEventListener('dragleave', () => col.classList.remove('drag-over'));
      col.addEventListener('drop', async (e) => {
        e.preventDefault();
        col.classList.remove('drag-over');
        const oppId = e.dataTransfer.getData('text/plain');
        if (oppId) await moveStage(oppId, stage);
      });

      const cardsWrap = col.querySelector('.kanban-cards');
      for (const o of stageOpps) {
        const card = document.createElement('div');
        card.className = 'kanban-card';
        card.draggable = true;
        card.dataset.id = o.id;
        card.innerHTML = `
          <div class="kanban-card-title">${esc(o.name)}</div>
          <div class="kanban-card-company">${esc(o.company_name)}${o.product_name ? ' &middot; ' + esc(o.product_name) : ''}</div>
          <div class="kanban-card-meta">
            <span class="kanban-card-amt">${money(o.amount)}</span>
            <span class="badge ${esc(o.maturity)}">${esc(o.maturity)} (${Math.round(o.win_probability)}%)</span>
          </div>
          <div class="kanban-card-foot">
            <span>${esc(o.owner_name || 'Unassigned')}</span>
            ${o.is_dormant ? `<span class="badge dormant">Dormant ${o.days_since_activity}d</span>` : `<span>Score ${o.maturity_score}</span>`}
          </div>
        `;
        card.addEventListener('dragstart', (e) => {
          card.classList.add('dragging');
          e.dataTransfer.setData('text/plain', o.id);
        });
        card.addEventListener('dragend', () => card.classList.remove('dragging'));
        card.addEventListener('click', () => openOppDetail(o.id));
        cardsWrap.appendChild(card);
      }

      board.appendChild(col);
    }
  }

  async function moveStage(oppId, newStage) {
    const current = allOpps.find((o) => o.id === oppId);
    if (current && current.stage === newStage) return;
    let lostReason = null;
    if (newStage === 'closed_lost') {
      lostReason = prompt('Optional lost reason:') || null;
    }
    try {
      const updated = await api(`/pipeline/api/opportunities/${oppId}/stage`, {
        method: 'PATCH',
        body: { stage: newStage, lost_reason: lostReason },
      });
      showToast(`Moved "${updated.name}" to ${STAGE_LABELS[newStage] || newStage} (${updated.maturity.toUpperCase()} ${updated.win_probability}%)`);
      await refreshAll();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function openOppDetail(oppId) {
    try {
      const opp = await api(`/pipeline/api/opportunities/${oppId}`);
      currentOppDetail = opp;
      $('detail-opp-name').textContent = opp.name;
      $('detail-opp-account').textContent = `${opp.company_name} (${opp.account_tier || 'standard'})`;
      $('detail-stage-select').value = opp.stage;
      $('btn-detail-delete').classList.toggle('hidden', !['admin', 'sales_manager'].includes(meta.current_user.role));

      $('detail-opp-stats').innerHTML = `
        <div><div class="p3-detail-stat-label">Amount</div><div class="p3-detail-stat-val">${money(opp.amount)}</div></div>
        <div><div class="p3-detail-stat-label">Weighted</div><div class="p3-detail-stat-val">${money(opp.weighted_amount)}</div></div>
        <div><div class="p3-detail-stat-label">Maturity</div><div class="p3-detail-stat-val"><span class="badge ${esc(opp.maturity)}">${esc(opp.maturity)}</span> (${opp.maturity_score})</div></div>
        <div><div class="p3-detail-stat-label">Win Prob</div><div class="p3-detail-stat-val">${opp.win_probability}%</div></div>
        <div><div class="p3-detail-stat-label">Expected Close</div><div class="p3-detail-stat-val">${esc(opp.expected_close || 'TBD')}</div></div>
      `;

      $('detail-history-list').innerHTML = (opp.history || []).length
        ? opp.history.map((h) => `
            <div class="p3-mini-item">
              <strong>${esc(h.from_stage || 'new')} &rarr; ${esc(h.to_stage || '-')}</strong>
              (${esc(h.from_maturity || '-')} &rarr; ${esc(h.to_maturity || '-')})<br>
              <span class="p3-subtitle">${esc(h.reason || '')} &middot; ${esc(h.changed_by_name || 'System')}</span>
            </div>`).join('')
        : '<p class="p3-subtitle">No transitions logged yet.</p>';

      $('detail-engagements-list').innerHTML = (opp.engagements || []).length
        ? opp.engagements.map((e) => `
            <div class="p3-mini-item">
              <strong>${esc(e.title || e.type)}</strong>
              ${e.is_qualifying ? `<span class="badge active">+${e.maturity_impact} pts</span>` : ''}<br>
              <span class="p3-subtitle">${esc((e.event_date || '').slice(0, 10))} &middot; ${esc(e.facilitator_name || '')}</span>
            </div>`).join('')
        : '<p class="p3-subtitle">No engagements linked yet. Log a tour in Journey Tracker!</p>';

      openModal('modal-opp-detail');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function openOppModal(opp) {
    $('modal-opp-title').textContent = opp ? 'Edit Opportunity' : 'New Opportunity';
    $('opp-id').value = opp ? opp.id : '';
    $('opp-account').value = opp ? opp.account_id : (meta.accounts[0]?.id || '');
    $('opp-name').value = opp ? opp.name : '';
    $('opp-product').value = opp && opp.product_id ? opp.product_id : '';
    $('opp-stage').value = opp ? opp.stage : 'qualification';
    $('opp-stage').disabled = Boolean(opp);
    $('opp-amount').value = opp ? opp.amount : 50000;
    $('opp-close').value = opp && opp.expected_close ? opp.expected_close.slice(0, 10) : '';
    $('opp-owner').value = opp && opp.owner_id ? opp.owner_id : (meta.current_user?.id || '');
    openModal('modal-opp');
  }

  async function saveOppForm(e) {
    e.preventDefault();
    const id = $('opp-id').value;
    const payload = {
      account_id: $('opp-account').value,
      name: $('opp-name').value.trim(),
      product_id: $('opp-product').value || null,
      stage: $('opp-stage').value,
      amount: Number($('opp-amount').value || 0),
      expected_close: $('opp-close').value || null,
      owner_id: $('opp-owner').value || null,
    };
    try {
      if (id) {
        await api(`/pipeline/api/opportunities/${id}`, { method: 'PUT', body: payload });
        showToast('Opportunity updated');
      } else {
        await api('/pipeline/api/opportunities', { method: 'POST', body: payload });
        showToast('Opportunity created');
      }
      closeModal('modal-opp');
      await refreshAll();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function renderLeads() {
    const q = $('filter-lead-q').value.trim().toLowerCase();
    const status = $('filter-lead-status').value;
    const source = $('filter-lead-source').value;

    const filtered = allLeads.filter((l) => {
      if (status && l.status !== status) return false;
      if (source && l.source !== source) return false;
      if (q && !`${l.company_name} ${l.contact_name || ''} ${l.contact_email || ''}`.toLowerCase().includes(q)) return false;
      return true;
    });

    const tbody = $('leads-tbody');
    if (!filtered.length) {
      tbody.innerHTML = '<tr><td colspan="8">No leads match your filters. Create one with "+ New Lead".</td></tr>';
      return;
    }

    tbody.innerHTML = filtered.map((l) => `
      <tr>
        <td><strong>${esc(l.company_name)}</strong>${l.converted_account_name ? `<br><span class="p3-subtitle">&rarr; ${esc(l.converted_account_name)}</span>` : ''}</td>
        <td>${esc(l.contact_name || '-')}<br><span class="p3-subtitle">${esc(l.contact_email || '')}</span></td>
        <td>${esc(l.vertical_name || '-')}</td>
        <td>${esc(l.source || '-')}</td>
        <td><strong>${l.score ?? 0}</strong></td>
        <td><span class="badge ${esc(l.status)}">${esc(l.status)}</span></td>
        <td>${esc(l.owner_name || '-')}</td>
        <td>
          ${l.status !== 'converted' ? `<button class="btn btn-sm" data-convert="${l.id}" type="button">Convert</button>` : ''}
          <button class="btn btn-outline btn-sm" data-edit-lead="${l.id}" type="button">Edit</button>
          ${['admin', 'sales_manager', 'account_manager'].includes(meta.current_user.role)
            ? `<button class="btn btn-danger btn-sm" data-del-lead="${l.id}" type="button">&times;</button>`
            : ''}
        </td>
      </tr>
    `).join('');

    tbody.querySelectorAll('[data-edit-lead]').forEach((b) => {
      b.addEventListener('click', () => openLeadModal(allLeads.find((x) => x.id === b.dataset.editLead)));
    });
    tbody.querySelectorAll('[data-convert]').forEach((b) => {
      b.addEventListener('click', () => openConvertModal(allLeads.find((x) => x.id === b.dataset.convert)));
    });
    tbody.querySelectorAll('[data-del-lead]').forEach((b) => {
      b.addEventListener('click', async () => {
        if (!confirm('Delete this lead?')) return;
        try {
          await api(`/pipeline/api/leads/${b.dataset.delLead}`, { method: 'DELETE' });
          showToast('Lead deleted');
          await refreshAll();
        } catch (err) {
          showToast(err.message, 'error');
        }
      });
    });
  }

  function openLeadModal(lead) {
    $('modal-lead-title').textContent = lead ? 'Edit Lead' : 'New Lead';
    $('lead-id').value = lead ? lead.id : '';
    $('lead-company').value = lead ? lead.company_name : '';
    $('lead-contact-name').value = lead ? (lead.contact_name || '') : '';
    $('lead-contact-email').value = lead ? (lead.contact_email || '') : '';
    $('lead-contact-phone').value = lead ? (lead.contact_phone || '') : '';
    $('lead-vertical').value = lead && lead.vertical_id ? lead.vertical_id : '';
    $('lead-source').value = lead && lead.source ? lead.source : 'website';
    $('lead-status').value = lead ? (lead.status === 'converted' ? 'qualified' : lead.status) : 'new';
    $('lead-score').value = lead ? (lead.score ?? 50) : 50;
    $('lead-owner').value = lead && lead.owner_id ? lead.owner_id : (meta.current_user?.id || '');
    $('lead-notes').value = lead ? (lead.notes || '') : '';
    openModal('modal-lead');
  }

  async function saveLeadForm(e) {
    e.preventDefault();
    const id = $('lead-id').value;
    const payload = {
      company_name: $('lead-company').value.trim(),
      contact_name: $('lead-contact-name').value.trim(),
      contact_email: $('lead-contact-email').value.trim(),
      contact_phone: $('lead-contact-phone').value.trim(),
      vertical_id: $('lead-vertical').value || null,
      source: $('lead-source').value,
      status: $('lead-status').value,
      score: Number($('lead-score').value || 0),
      owner_id: $('lead-owner').value || null,
      notes: $('lead-notes').value.trim(),
    };
    try {
      if (id) {
        await api(`/pipeline/api/leads/${id}`, { method: 'PUT', body: payload });
        showToast('Lead updated');
      } else {
        await api('/pipeline/api/leads', { method: 'POST', body: payload });
        showToast('Lead created');
      }
      closeModal('modal-lead');
      await refreshAll();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function openConvertModal(lead) {
    $('convert-lead-id').value = lead.id;
    $('convert-company-label').textContent = lead.company_name;
    $('convert-existing-account').value = '';
    $('convert-new-account-fields').classList.remove('hidden');
    $('convert-opp-name').value = `${lead.company_name} - Commercial Deal`;
    $('convert-amount').value = 75000;
    openModal('modal-convert');
  }

  async function submitConvertForm(e) {
    e.preventDefault();
    const lid = $('convert-lead-id').value;
    const payload = {
      existing_account_id: $('convert-existing-account').value || null,
      tier: $('convert-tier').value,
      region: $('convert-region').value.trim(),
      opportunity_name: $('convert-opp-name').value.trim(),
      product_id: $('convert-product').value || null,
      amount: Number($('convert-amount').value || 0),
      stage: $('convert-stage').value,
    };
    try {
      const res = await api(`/pipeline/api/leads/${lid}/convert`, { method: 'POST', body: payload });
      closeModal('modal-convert');
      showToast(`Converted! Created opportunity "${res.opportunity.name}"`);
      meta = await api('/pipeline/api/meta');
      populateMetaControls();
      await refreshAll();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function runDormancyCheck() {
    try {
      const res = await api('/pipeline/api/dormancy/run', { method: 'POST', body: {} });
      showToast(`Checked ${res.checked} open deals: ${res.dormant_found} dormant, ${res.degraded} degraded.`);
      await refreshAll();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function renderAnalytics(data) {
    const dormantTbody = $('dormant-tbody');
    dormantTbody.innerHTML = data.dormant_opportunities.length
      ? data.dormant_opportunities.map((d) => `
          <tr>
            <td><strong>${esc(d.name)}</strong></td>
            <td>${esc(d.company_name)}</td>
            <td><span class="badge ${esc(d.maturity)}">${esc(d.maturity)} (${d.maturity_score})</span></td>
            <td>${money(d.amount)}</td>
            <td><span class="badge dormant">${d.days_since_activity}d</span></td>
          </tr>`).join('')
      : '<tr><td colspan="5">No dormant open deals right now.</td></tr>';

    const histTbody = $('history-tbody');
    histTbody.innerHTML = data.recent_history.length
      ? data.recent_history.map((h) => `
          <tr>
            <td><strong>${esc(h.opportunity_name)}</strong><br><span class="p3-subtitle">${esc(h.company_name)}</span></td>
            <td>${esc(h.from_stage || 'new')} &rarr; ${esc(h.to_stage || '-')}<br>
                <span class="p3-subtitle">${esc(h.from_maturity || '-')} &rarr; ${esc(h.to_maturity || '-')}</span></td>
            <td>${esc(h.reason || '-')}</td>
            <td>${esc((h.changed_at || '').slice(0, 10))}</td>
          </tr>`).join('')
      : '<tr><td colspan="4">No opportunity history recorded yet.</td></tr>';

    if (typeof Chart === 'undefined') return;

    const stageCtx = $('chart-stage-funnel').getContext('2d');
    if (stageChart) stageChart.destroy();
    stageChart = new Chart(stageCtx, {
      type: 'bar',
      data: {
        labels: data.by_stage.map((s) => STAGE_LABELS[s.stage] || s.stage),
        datasets: [
          { label: 'Total ($)', data: data.by_stage.map((s) => s.total_amount), backgroundColor: '#1a2b5e' },
          { label: 'Weighted ($)', data: data.by_stage.map((s) => s.weighted_amount), backgroundColor: '#00b4d8' },
        ],
      },
      options: { responsive: true, maintainAspectRatio: false },
    });

    const matCtx = $('chart-maturity-dist').getContext('2d');
    if (maturityChart) maturityChart.destroy();
    maturityChart = new Chart(matCtx, {
      type: 'doughnut',
      data: {
        labels: data.by_maturity.map((m) => m.maturity.toUpperCase()),
        datasets: [{
          data: data.by_maturity.map((m) => m.deals),
          backgroundColor: ['#d4a373', '#9aa5b1', '#f4c430', '#00b4d8'],
        }],
      },
      options: { responsive: true, maintainAspectRatio: false },
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
