/* Experiential Journey Tracker frontend controller (WP3) */
(function () {
  let meta = null;
  let typeChart = null;
  let roleChart = null;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function showToast(msg, type = 'success') {
    const el = $('journey-toast');
    el.textContent = msg;
    el.className = `j-toast ${type}`;
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.add('hidden'), 4500);
  }

  function nowLocalInput() {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  }

  async function init() {
    meta = await api('/journey/api/meta');
    populateMeta();
    bindEvents();
    $('eng-date').value = nowLocalInput();
    applyTypeDefaults();
    if (meta.accounts.length) {
      await loadAccountContext(meta.accounts[0].id);
    }
    await refreshAll();
  }

  function populateMeta() {
    const accOpts = meta.accounts.map((a) => `<option value="${esc(a.id)}">${esc(a.company_name)}</option>`).join('');
    $('eng-account').innerHTML = accOpts;
    $('filter-eng-account').innerHTML = '<option value="">All Accounts</option>' + accOpts;
    $('task-account').innerHTML = '<option value="">-- Optional --</option>' + accOpts;

    const userOpts = meta.users.map((u) => `<option value="${esc(u.id)}">${esc(u.full_name)} (${esc(u.role)})</option>`).join('');
    $('task-assignee').innerHTML = userOpts;
    if (meta.current_user?.id) $('task-assignee').value = meta.current_user.id;
  }

  function applyTypeDefaults() {
    const def = meta.engagement_defaults[$('eng-type').value];
    if (!def) return;
    $('eng-qualifying').checked = Boolean(def.qualifying);
    $('eng-impact').value = def.impact;
    $('eng-sla').value = def.sla_hours;
  }

  function bindEvents() {
    document.querySelectorAll('.j-tab').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.j-tab').forEach((b) => b.classList.remove('active'));
        document.querySelectorAll('.j-tab-panel').forEach((p) => p.classList.remove('active'));
        btn.classList.add('active');
        $(`tab-${btn.dataset.tab}`).classList.add('active');
      });
    });

    $('eng-account').addEventListener('change', () => loadAccountContext($('eng-account').value));
    $('eng-type').addEventListener('change', applyTypeDefaults);
    $('form-engagement').addEventListener('submit', submitEngagement);

    $('filter-eng-account').addEventListener('change', loadEngagements);
    $('filter-eng-type').addEventListener('change', loadEngagements);

    $('filter-task-status').addEventListener('change', loadTasks);
    $('filter-task-mine').addEventListener('change', loadTasks);

    $('btn-new-task').addEventListener('click', () => $('modal-task').classList.remove('hidden'));
    document.querySelectorAll('[data-close]').forEach((b) => {
      b.addEventListener('click', () => $(b.dataset.close).classList.add('hidden'));
    });
    $('form-task').addEventListener('submit', submitNewTask);

    $('btn-close-trigger').addEventListener('click', () => $('trigger-banner').classList.add('hidden'));

    $('btn-notif-bell').addEventListener('click', (e) => {
      e.stopPropagation();
      $('notif-popover').classList.toggle('hidden');
    });
    document.addEventListener('click', (e) => {
      if (!$('notif-popover').contains(e.target) && e.target !== $('btn-notif-bell')) {
        $('notif-popover').classList.add('hidden');
      }
    });
    $('btn-read-all').addEventListener('click', async () => {
      try {
        await api('/journey/api/notifications/read-all', { method: 'POST', body: {} });
        await loadNotifications();
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }

  async function loadAccountContext(accountId) {
    if (!accountId) return;
    try {
      const ctx = await api(`/journey/api/accounts/${accountId}/context`);
      const oppSel = $('eng-opp');
      if (ctx.opportunities.length) {
        oppSel.innerHTML = '<option value="">-- Optional / No Linked Deal --</option>' +
          ctx.opportunities.map((o) =>
            `<option value="${esc(o.id)}">${esc(o.name)} [${esc(o.maturity.toUpperCase())} ${o.maturity_score}/100]</option>`
          ).join('');
        oppSel.value = ctx.opportunities[0].id;
      } else {
        oppSel.innerHTML = '<option value="">No open opportunities on this account</option>';
      }

      const attBox = $('eng-attendees-box');
      if (ctx.contacts.length) {
        attBox.innerHTML = ctx.contacts.map((c) => `
          <label class="j-checkbox">
            <input type="checkbox" class="eng-att-cb" value="${esc(c.id)}">
            <span><strong>${esc(c.full_name)}</strong> &middot; <span class="badge">${esc(c.decision_role)}</span></span>
          </label>
        `).join('');
      } else {
        attBox.innerHTML = '<span class="j-subtitle">No contacts found for this account.</span>';
      }
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function submitEngagement(e) {
    e.preventDefault();
    const attendeeIds = Array.from(document.querySelectorAll('.eng-att-cb:checked')).map((cb) => cb.value);
    const payload = {
      account_id: $('eng-account').value,
      opportunity_id: $('eng-opp').value || null,
      type: $('eng-type').value,
      title: $('eng-title').value.trim(),
      event_date: $('eng-date').value,
      attendee_ids: attendeeIds,
      is_qualifying: $('eng-qualifying').checked,
      maturity_impact: Number($('eng-impact').value || 0),
      sla_hours: Number($('eng-sla').value || 24),
      outcome_notes: $('eng-outcome').value.trim(),
      follow_up_actions: $('eng-followup').value.trim(),
    };

    try {
      const res = await api('/journey/api/engagements', { method: 'POST', body: payload });
      $('eng-title').value = '';
      $('eng-outcome').value = '';
      $('eng-followup').value = '';
      renderTriggerBanner(res);
      showToast('Engagement logged!');
      await loadAccountContext($('eng-account').value);
      await refreshAll();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  function renderTriggerBanner(res) {
    const t = res.trigger;
    if (!t || !t.fired) {
      $('trigger-banner').classList.add('hidden');
      return;
    }
    const m = t.maturity_update;
    const matHtml = m
      ? `<div class="j-trigger-pill">
           <strong>Pipeline Maturity</strong><br>
           ${esc(m.name)}<br>
           <span class="badge ${esc(m.previous_maturity)}">${esc(m.previous_maturity)} (${m.previous_score})</span>
           &rarr;
           <span class="badge ${esc(m.maturity)}">${esc(m.maturity)} (${m.maturity_score})</span>
           (${m.win_probability}% win)
         </div>`
      : `<div class="j-trigger-pill"><strong>Pipeline Maturity</strong><br>No opportunity linked to event.</div>`;

    const taskHtml = t.task
      ? `<div class="j-trigger-pill">
           <strong>Follow-Up Task Created</strong><br>
           ${esc(t.task.title)}<br>
           SLA: ${t.task.sla_hours}h &middot; Status: <span class="badge open">${esc(t.task.status)}</span>
         </div>`
      : '';

    const notifHtml = `
      <div class="j-trigger-pill">
        <strong>Manager Notification</strong><br>
        Sent to ${t.notifications_sent} sales manager(s).<br>
        <em>Next: ${esc(t.next_best_action)}</em>
      </div>`;

    $('trigger-banner-body').innerHTML = `<div class="j-trigger-grid">${matHtml}${taskHtml}${notifHtml}</div>`;
    $('trigger-banner').classList.remove('hidden');
  }

  async function refreshAll() {
    await Promise.all([
      loadEngagements(),
      loadTasks(),
      loadNotifications(),
      loadAnalytics(),
    ]);
  }

  async function loadEngagements() {
    const params = new URLSearchParams();
    if ($('filter-eng-account').value) params.set('account_id', $('filter-eng-account').value);
    if ($('filter-eng-type').value) params.set('type', $('filter-eng-type').value);
    const qs = params.toString() ? `?${params.toString()}` : '';

    try {
      const events = await api(`/journey/api/engagements${qs}`);
      const box = $('eng-timeline');
      if (!events.length) {
        box.innerHTML = '<p class="j-subtitle">No engagements logged yet. Use the form to log a DC tour or demo!</p>';
        return;
      }
      box.innerHTML = events.map((ev) => {
        const label = meta.engagement_defaults[ev.type]?.label || ev.type;
        const atts = (ev.attendees || []).map((a) =>
          `<span class="badge">${esc(a.full_name)} (${esc(a.decision_role)})</span>`
        ).join('');
        return `
          <div class="j-event-card ${ev.is_qualifying ? 'qualifying' : ''}">
            <div class="j-event-top">
              <span class="j-event-title">${esc(ev.title || label)}</span>
              <div>
                <span class="badge">${esc(label)}</span>
                ${ev.is_qualifying ? `<span class="badge qualifying">Qualifying +${ev.maturity_impact} pts</span>` : ''}
              </div>
            </div>
            <div class="j-event-meta">
              <strong>${esc(ev.company_name)}</strong>
              ${ev.opportunity_name ? ` &middot; Deal: ${esc(ev.opportunity_name)} (${esc(ev.opportunity_maturity || '')})` : ''}
              &middot; ${esc((ev.event_date || '').replace('T', ' ').slice(0, 16))}
              &middot; By ${esc(ev.facilitator_name || 'Staff')}
            </div>
            ${ev.outcome_notes ? `<p style="margin:4px 0; font-size:.86rem;">${esc(ev.outcome_notes)}</p>` : ''}
            ${ev.follow_up_actions ? `<p style="margin:4px 0; font-size:.82rem; color:var(--brand);"><strong>Follow-up:</strong> ${esc(ev.follow_up_actions)}</p>` : ''}
            ${atts ? `<div class="j-attendee-pills">${atts}</div>` : ''}
          </div>
        `;
      }).join('');
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function loadTasks() {
    const params = new URLSearchParams();
    if ($('filter-task-status').value) params.set('status', $('filter-task-status').value);
    if ($('filter-task-mine').checked) params.set('mine', '1');
    const qs = params.toString() ? `?${params.toString()}` : '';

    try {
      const tasks = await api(`/journey/api/tasks${qs}`);
      $('tasks-tab-count').textContent = tasks.length;
      const tbody = $('tasks-tbody');
      if (!tasks.length) {
        tbody.innerHTML = '<tr><td colspan="7">No tasks match your filters.</td></tr>';
        return;
      }
      tbody.innerHTML = tasks.map((t) => `
        <tr>
          <td><strong>${esc(t.title)}</strong>${t.description ? `<br><span class="j-subtitle">${esc(t.description)}</span>` : ''}</td>
          <td>${esc(t.company_name || '-')}${t.opportunity_name ? `<br><span class="j-subtitle">${esc(t.opportunity_name)}</span>` : ''}</td>
          <td>${esc(t.assignee_name || '-')}</td>
          <td>${t.sla_hours ? `${t.sla_hours}h` : '-'}</td>
          <td>${esc((t.due_at || '').replace('T', ' ').slice(0, 16) || '-')}</td>
          <td><span class="badge ${esc(t.status)}">${esc(t.status)}</span></td>
          <td>
            ${t.status === 'open' || t.status === 'overdue'
              ? `<button class="btn btn-outline btn-sm" data-task-id="${t.id}" data-task-status="in_progress" type="button">Start</button>`
              : ''}
            ${t.status !== 'done'
              ? `<button class="btn btn-sm" data-task-id="${t.id}" data-task-status="done" type="button">Mark Done</button>`
              : '<span class="j-subtitle">Completed</span>'}
          </td>
        </tr>
      `).join('');

      tbody.querySelectorAll('[data-task-id]').forEach((b) => {
        b.addEventListener('click', async () => {
          try {
            await api(`/journey/api/tasks/${b.dataset.taskId}`, {
              method: 'PATCH',
              body: { status: b.dataset.taskStatus },
            });
            showToast(`Task marked ${b.dataset.taskStatus.replace('_', ' ')}`);
            await refreshAll();
          } catch (err) {
            showToast(err.message, 'error');
          }
        });
      });
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function submitNewTask(e) {
    e.preventDefault();
    const payload = {
      title: $('task-title').value.trim(),
      account_id: $('task-account').value || null,
      assigned_to: $('task-assignee').value || null,
      sla_hours: Number($('task-sla').value || 48),
      description: $('task-desc').value.trim(),
    };
    try {
      await api('/journey/api/tasks', { method: 'POST', body: payload });
      $('modal-task').classList.add('hidden');
      $('form-task').reset();
      showToast('Follow-up task created');
      await refreshAll();
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function loadNotifications() {
    try {
      const data = await api('/journey/api/notifications');
      const badge = $('notif-unread-badge');
      badge.textContent = data.unread_count;
      badge.classList.toggle('hidden', data.unread_count === 0);

      const list = $('notif-list');
      if (!data.items.length) {
        list.innerHTML = '<p class="j-subtitle">No notifications for your account yet.</p>';
        return;
      }
      list.innerHTML = data.items.map((n) => `
        <div class="j-notif-item ${n.is_read ? '' : 'unread'}">
          <div class="j-notif-title">${esc(n.title)}</div>
          <div class="j-notif-body">${esc(n.body || '')}</div>
          <div class="j-notif-foot">
            <span>${esc((n.created_at || '').replace('T', ' ').slice(0, 16))}</span>
            ${n.is_read
              ? '<span>Read</span>'
              : `<button class="btn btn-outline btn-sm" data-read-notif="${n.id}" type="button">Mark read</button>`}
          </div>
        </div>
      `).join('');

      list.querySelectorAll('[data-read-notif]').forEach((b) => {
        b.addEventListener('click', async () => {
          try {
            await api(`/journey/api/notifications/${b.dataset.readNotif}/read`, { method: 'PATCH', body: {} });
            await loadNotifications();
          } catch (err) {
            showToast(err.message, 'error');
          }
        });
      });
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  async function loadAnalytics() {
    try {
      const data = await api('/journey/api/analytics');
      const k = data.kpis;
      $('jkpi-total').textContent = k.total_engagements;
      $('jkpi-qualifying').textContent = `${k.qualifying_engagements} qualifying events`;
      $('jkpi-contacts').textContent = k.unique_contacts_engaged;
      $('jkpi-attendees').textContent = `${k.total_attendees} total check-ins`;
      $('jkpi-tasks').textContent = k.open_tasks + k.overdue_tasks;
      $('jkpi-overdue').textContent = `${k.overdue_tasks} overdue`;
      $('jkpi-done').textContent = k.completed_tasks;

      $('top-accounts-tbody').innerHTML = data.top_accounts.length
        ? data.top_accounts.map((a) => `
            <tr>
              <td><strong>${esc(a.company_name)}</strong></td>
              <td>${a.events}</td>
              <td>${a.qualifying_events}</td>
              <td>${a.attendees}</td>
            </tr>`).join('')
        : '<tr><td colspan="4">No engagement data yet.</td></tr>';

      if (typeof Chart === 'undefined') return;

      const tCtx = $('chart-eng-types').getContext('2d');
      if (typeChart) typeChart.destroy();
      typeChart = new Chart(tCtx, {
        type: 'bar',
        data: {
          labels: data.by_type.map((x) => x.label),
          datasets: [{ label: 'Events', data: data.by_type.map((x) => x.count), backgroundColor: '#1a2b5e' }],
        },
        options: { responsive: true, maintainAspectRatio: false },
      });

      const rCtx = $('chart-att-roles').getContext('2d');
      if (roleChart) roleChart.destroy();
      roleChart = new Chart(rCtx, {
        type: 'doughnut',
        data: {
          labels: data.by_decision_role.length ? data.by_decision_role.map((x) => x.role) : ['No attendees yet'],
          datasets: [{
            data: data.by_decision_role.length ? data.by_decision_role.map((x) => x.count) : [1],
            backgroundColor: ['#1a2b5e', '#00b4d8', '#e8192c', '#f4c430', '#6b7490', '#2a9d8f'],
          }],
        },
        options: { responsive: true, maintainAspectRatio: false },
      });
    } catch (err) {
      showToast(err.message, 'error');
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
