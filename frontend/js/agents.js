/* ============================================================
   RuPi — Agent Page JavaScript
   ============================================================ */

'use strict';

// ── Tax Agent ─────────────────────────────────────────────────
function initTaxAgent() {
  if (!document.querySelector('.agent-page.tax')) return;

  const calculateBtn = document.getElementById('calculate-tax-btn');
  const resultSection = document.getElementById('tax-result');

  if (calculateBtn) {
    calculateBtn.addEventListener('click', () => {
      const grossIncome = parseFloat(document.getElementById('gross-income')?.value) || 0;
      const taxRegime = document.getElementById('tax-regime')?.value || 'new';
      const form16 = document.getElementById('form16-upload');

      if (!grossIncome) {
        showToast('Please enter your gross income to proceed.', 'warning');
        return;
      }

      // Show loader
      calculateBtn.disabled = true;
      calculateBtn.innerHTML = `
        <div class="loader" style="padding:0;gap:6px;">
          <div class="loader-dot"></div>
          <div class="loader-dot"></div>
          <div class="loader-dot"></div>
        </div>
        Analyzing...
      `;

      // Simulate AI computation
      setTimeout(() => {
        calculateBtn.disabled = false;
        calculateBtn.textContent = 'Calculate Tax Liability';

        const taxData = computeTax(grossIncome, taxRegime);
        renderTaxResult(taxData, resultSection);

        resultSection?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        showToast('Tax analysis complete. Review your breakdown below.', 'success');
      }, 2200);
    });
  }

  // Chat interface
  initAgentChat('tax-chat', 'tax');

  // Deduction suggestions
  initDeductionSuggestions();
}

function computeTax(gross, regime) {
  let tax = 0, effectiveRate = 0;

  if (regime === 'new') {
    const slabs = [
      [300000, 0],
      [600000, 0.05],
      [900000, 0.10],
      [1200000, 0.15],
      [1500000, 0.20],
      [Infinity, 0.30]
    ];
    let remaining = gross;
    let prev = 0;
    for (const [limit, rate] of slabs) {
      const taxable = Math.min(remaining, limit - prev);
      if (taxable <= 0) break;
      tax += taxable * rate;
      remaining -= taxable;
      prev = limit;
    }
  } else {
    // Old regime with standard deduction
    const standardDeduction = 50000;
    const taxable = Math.max(0, gross - standardDeduction);
    if (taxable <= 250000) tax = 0;
    else if (taxable <= 500000) tax = (taxable - 250000) * 0.05;
    else if (taxable <= 1000000) tax = 12500 + (taxable - 500000) * 0.20;
    else tax = 112500 + (taxable - 1000000) * 0.30;
  }

  // Cess 4%
  const cess = tax * 0.04;
  const totalTax = tax + cess;
  effectiveRate = (totalTax / gross) * 100;

  const hra80C = Math.min(gross * 0.15, 150000);
  const potential80D = 25000;
  const potentialSaving = (hra80C + potential80D) * (effectiveRate / 100);

  return {
    gross,
    regime,
    baseTax: tax,
    cess,
    totalTax,
    effectiveRate,
    inHandSalary: gross - totalTax,
    hra80C,
    potentialSaving
  };
}

function renderTaxResult(data, container) {
  if (!container) return;

  const fmt = (n) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n);
  const cur = (n) => '₹' + fmt(n);

  container.style.display = 'block';
  container.innerHTML = `
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">
          <span class="icon-wrap icon-wrap-yellow" style="width:32px;height:32px;font-size:1rem;">&#9881;</span>
          Tax Analysis Result
        </div>
        <button class="btn btn-sm btn-secondary" onclick="window.print()">Export Report</button>
      </div>
      <div class="panel-body">
        <div class="grid-4" style="gap:12px;margin-bottom:24px;">
          <div class="agent-stat-item">
            <div class="agent-stat-num" style="color:var(--tax-color);">${cur(data.totalTax)}</div>
            <div class="agent-stat-label">Total Tax Payable</div>
          </div>
          <div class="agent-stat-item">
            <div class="agent-stat-num">${cur(data.inHandSalary)}</div>
            <div class="agent-stat-label">Annual In-Hand</div>
          </div>
          <div class="agent-stat-item">
            <div class="agent-stat-num">${data.effectiveRate.toFixed(2)}%</div>
            <div class="agent-stat-label">Effective Tax Rate</div>
          </div>
          <div class="agent-stat-item">
            <div class="agent-stat-num" style="color:var(--accent);">${cur(data.potentialSaving)}</div>
            <div class="agent-stat-label">Potential Savings</div>
          </div>
        </div>

        <h4 style="margin-bottom:12px;font-family:var(--font-display);">Detailed Breakdown</h4>
        <table class="breakdown-table">
          <thead>
            <tr>
              <th>Component</th>
              <th style="text-align:right;">Amount</th>
              <th style="text-align:right;">Notes</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="td-label">Gross Annual Income</td>
              <td class="td-neutral">${cur(data.gross)}</td>
              <td style="text-align:right;font-size:0.78rem;color:var(--text-muted);">Per annum</td>
            </tr>
            <tr>
              <td class="td-label">Base Income Tax</td>
              <td class="td-neutral" style="color:var(--tax-color);">${cur(data.baseTax)}</td>
              <td style="text-align:right;font-size:0.78rem;color:var(--text-muted);">${data.regime === 'new' ? 'New' : 'Old'} Regime</td>
            </tr>
            <tr>
              <td class="td-label">Health & Education Cess</td>
              <td class="td-neutral" style="color:var(--tax-color);">${cur(data.cess)}</td>
              <td style="text-align:right;font-size:0.78rem;color:var(--text-muted);">4% of tax</td>
            </tr>
            <tr>
              <td class="td-label"><strong>Total Tax Payable</strong></td>
              <td class="td-value">${cur(data.totalTax)}</td>
              <td style="text-align:right;font-size:0.78rem;color:var(--text-muted);">Base + Cess</td>
            </tr>
            <tr>
              <td class="td-label">80C Estimated Deduction</td>
              <td class="td-value" style="color:var(--accent);">${cur(data.hra80C)}</td>
              <td style="text-align:right;font-size:0.78rem;color:var(--text-muted);">Applicable</td>
            </tr>
          </tbody>
        </table>

        <div class="result-panel" style="margin-top:16px;background:var(--accent-muted);border-color:var(--border-accent);">
          <div class="result-header">
            <span class="result-title" style="color:var(--accent);">AI Recommendation</span>
          </div>
          <div class="result-content">
            Based on your income of <span class="result-highlight">${cur(data.gross)}</span> under
            the <strong>${data.regime}</strong> regime, you can save up to
            <span class="result-highlight">${cur(data.potentialSaving)}</span> by maximizing
            Section 80C deductions (ELSS, PPF, NPS) and 80D medical insurance.
            Consider switching to the ${data.regime === 'new' ? 'old' : 'new'} regime for comparison.
          </div>
        </div>
      </div>
    </div>
  `;
}

function initDeductionSuggestions() {
  const items = $$('.deduction-item');
  items.forEach(item => {
    item.addEventListener('click', () => {
      item.classList.toggle('selected');
      const label = item.dataset.label;
      const amt = item.dataset.amount;
      if (item.classList.contains('selected')) {
        showToast(`Added ${label}: ₹${amt} to deductions`, 'success', 2000);
      }
    });
  });
}

// ── Investment Agent ───────────────────────────────────────────
function initInvestAgent() {
  if (!document.querySelector('.agent-page.invest')) return;

  const analyzeBtn = document.getElementById('analyze-portfolio-btn');
  const resultSection = document.getElementById('invest-result');

  if (analyzeBtn) {
    analyzeBtn.addEventListener('click', () => {
      const amount = parseFloat(document.getElementById('invest-amount')?.value) || 0;
      const horizon = document.getElementById('invest-horizon')?.value || '5';
      const risk = document.getElementById('risk-profile')?.value || 'moderate';
      const goal = document.getElementById('invest-goal')?.value || '';

      if (!amount) {
        showToast('Please enter an investment amount to continue.', 'warning');
        return;
      }

      analyzeBtn.disabled = true;
      analyzeBtn.innerHTML = `
        <div class="loader" style="padding:0;gap:6px;display:inline-flex;">
          <div class="loader-dot"></div>
          <div class="loader-dot"></div>
          <div class="loader-dot"></div>
        </div>
        Analyzing market data...
      `;

      setTimeout(() => {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = 'Generate Investment Plan';

        const plan = computeInvestmentPlan(amount, parseInt(horizon), risk, goal);
        renderInvestResult(plan, resultSection);

        resultSection?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        showToast('Investment plan generated successfully.', 'success');
      }, 2600);
    });
  }

  // Portfolio sparklines
  initPortfolioSparklines();

  // Chat
  initAgentChat('invest-chat', 'invest');
}

function computeInvestmentPlan(amount, horizonYears, risk, goal) {
  const allocations = {
    conservative: { equity: 25, debt: 55, gold: 10, liquid: 10 },
    moderate:     { equity: 50, debt: 35, gold: 10, liquid: 5  },
    aggressive:   { equity: 70, debt: 20, gold: 5,  liquid: 5  }
  };

  const returns = {
    conservative: 0.085,
    moderate:     0.115,
    aggressive:   0.145
  };

  const alloc = allocations[risk] || allocations.moderate;
  const expectedReturn = returns[risk] || returns.moderate;
  const monthly = amount;
  const months = horizonYears * 12;
  const r = expectedReturn / 12;

  // SIP future value
  const fv = monthly * ((Math.pow(1 + r, months) - 1) / r) * (1 + r);
  const totalInvested = monthly * months;
  const estimatedGain = fv - totalInvested;

  const recommendations = [
    { name: 'Nifty 50 Index Fund', type: 'Equity', alloc: alloc.equity * 0.6, return: '14-16%', risk: 'High' },
    { name: 'Flexi Cap Fund',      type: 'Equity', alloc: alloc.equity * 0.4, return: '12-15%', risk: 'High' },
    { name: 'Corporate Bond Fund', type: 'Debt',   alloc: alloc.debt * 0.5,   return: '7-9%',   risk: 'Low'  },
    { name: 'Liquid Fund',         type: 'Liquid', alloc: alloc.liquid,        return: '4-6%',   risk: 'Very Low' },
    { name: 'Gold ETF',            type: 'Gold',   alloc: alloc.gold,          return: '8-10%',  risk: 'Medium' },
  ];

  return { amount, horizonYears, risk, alloc, expectedReturn, fv, totalInvested, estimatedGain, recommendations };
}

function renderInvestResult(data, container) {
  if (!container) return;

  const fmt = (n) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n);
  const cur = (n) => '₹' + fmt(n);
  const pct = (n) => n.toFixed(0) + '%';

  const recHTML = data.recommendations.map(r => `
    <tr>
      <td class="td-label">${r.name}</td>
      <td><span class="badge ${r.type === 'Equity' ? 'badge-blue' : r.type === 'Gold' ? 'badge-yellow' : 'badge-green'}" style="font-size:0.7rem;">${r.type}</span></td>
      <td class="td-value">${pct(r.alloc)}</td>
      <td class="td-neutral">${r.return} p.a.</td>
    </tr>
  `).join('');

  container.style.display = 'block';
  container.innerHTML = `
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">
          <span class="icon-wrap" style="width:32px;height:32px;font-size:1rem;background:var(--invest-color-muted);color:var(--invest-color);">&#9650;</span>
          Investment Plan
        </div>
        <span class="badge badge-blue">${data.risk.charAt(0).toUpperCase() + data.risk.slice(1)} Risk</span>
      </div>
      <div class="panel-body">
        <div class="grid-4" style="gap:12px;margin-bottom:24px;">
          <div class="agent-stat-item">
            <div class="agent-stat-num" style="color:var(--invest-color);">${cur(data.fv)}</div>
            <div class="agent-stat-label">Estimated Corpus</div>
          </div>
          <div class="agent-stat-item">
            <div class="agent-stat-num">${cur(data.totalInvested)}</div>
            <div class="agent-stat-label">Total Invested</div>
          </div>
          <div class="agent-stat-item">
            <div class="agent-stat-num" style="color:var(--accent);">${cur(data.estimatedGain)}</div>
            <div class="agent-stat-label">Est. Wealth Gain</div>
          </div>
          <div class="agent-stat-item">
            <div class="agent-stat-num">${(data.expectedReturn * 100).toFixed(1)}%</div>
            <div class="agent-stat-label">Expected CAGR</div>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px;">
          <div>
            <h4 style="margin-bottom:12px;font-family:var(--font-display);">Asset Allocation</h4>
            <div style="display:flex;flex-direction:column;gap:8px;">
              ${[
                { label: 'Equity', val: data.alloc.equity, color: 'var(--invest-color)' },
                { label: 'Debt', val: data.alloc.debt, color: 'var(--accent)' },
                { label: 'Gold', val: data.alloc.gold, color: 'var(--tax-color)' },
                { label: 'Liquid', val: data.alloc.liquid, color: 'var(--text-muted)' },
              ].map(a => `
                <div>
                  <div class="flex-between" style="margin-bottom:4px;">
                    <span style="font-size:0.8rem;color:var(--text-secondary);">${a.label}</span>
                    <span style="font-size:0.8rem;font-weight:600;color:${a.color};">${a.val}%</span>
                  </div>
                  <div style="height:6px;border-radius:3px;background:var(--bg-surface);overflow:hidden;">
                    <div style="height:100%;width:${a.val}%;background:${a.color};border-radius:3px;transition:width 0.8s ease;"></div>
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
          <div>
            <h4 style="margin-bottom:12px;font-family:var(--font-display);">Growth Projection</h4>
            <canvas id="growth-sparkline" width="200" height="100" style="width:100%;height:100px;border-radius:8px;"></canvas>
          </div>
        </div>

        <h4 style="margin-bottom:12px;font-family:var(--font-display);">Recommended Funds</h4>
        <table class="breakdown-table">
          <thead>
            <tr><th>Fund</th><th>Type</th><th style="text-align:right;">Allocation</th><th style="text-align:right;">Est. Return</th></tr>
          </thead>
          <tbody>${recHTML}</tbody>
        </table>
      </div>
    </div>
  `;

  // Draw sparkline
  setTimeout(() => {
    const canvas = document.getElementById('growth-sparkline');
    if (canvas) {
      const years = data.horizonYears;
      const points = Array.from({ length: years + 1 }, (_, i) => {
        const m = i * 12;
        const r = data.expectedReturn / 12;
        return data.amount * ((Math.pow(1 + r, m) - 1) / r) * (1 + r);
      });
      drawSparkline(canvas, points, 'var(--invest-color)');
    }
  }, 100);
}

function initPortfolioSparklines() {
  $$('canvas[data-sparkline]').forEach(canvas => {
    const vals = canvas.dataset.sparkline.split(',').map(Number);
    const color = canvas.dataset.color || '#3ddc52';
    drawSparkline(canvas, vals, color);
  });
}

// ── Security Agent ─────────────────────────────────────────────
function initSecurityAgent() {
  if (!document.querySelector('.agent-page.security')) return;

  // Scan button
  const scanBtn = document.getElementById('run-security-scan');
  const resultSection = document.getElementById('security-result');

  if (scanBtn) {
    scanBtn.addEventListener('click', () => {
      scanBtn.disabled = true;
      const progressBar = document.getElementById('scan-progress');
      const progressText = document.getElementById('scan-progress-text');
      let progress = 0;

      const interval = setInterval(() => {
        progress += Math.random() * 18 + 4;
        if (progress >= 100) {
          progress = 100;
          clearInterval(interval);

          setTimeout(() => {
            scanBtn.disabled = false;
            renderSecurityResult(resultSection);
            resultSection?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            showToast('Security scan complete. View your report below.', 'success');
          }, 400);
        }

        if (progressBar) progressBar.style.width = progress.toFixed(0) + '%';
        if (progressText) progressText.textContent = getProgressLabel(progress);
      }, 280);
    });
  }

  // Document vault
  initDocumentVault();

  // Chat
  initAgentChat('security-chat', 'security');

  // Risk score animation
  animateRiskScore();
}

function getProgressLabel(p) {
  if (p < 20) return 'Scanning document integrity...';
  if (p < 40) return 'Checking blockchain verification...';
  if (p < 60) return 'Analyzing access patterns...';
  if (p < 80) return 'Running anomaly detection...';
  if (p < 95) return 'Generating security report...';
  return 'Complete.';
}

function renderSecurityResult(container) {
  if (!container) return;

  container.style.display = 'block';
  container.innerHTML = `
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">
          <span class="icon-wrap" style="width:32px;height:32px;font-size:1rem;background:var(--security-color-muted);color:var(--security-color);">&#128274;</span>
          Security Scan Report
        </div>
        <span class="badge badge-green">
          <span class="glow-dot" style="width:6px;height:6px;"></span>
          All Clear
        </span>
      </div>
      <div class="panel-body">
        <div class="grid-4" style="gap:12px;margin-bottom:24px;">
          <div class="agent-stat-item">
            <div class="agent-stat-num" style="color:var(--accent);">A+</div>
            <div class="agent-stat-label">Security Score</div>
          </div>
          <div class="agent-stat-item">
            <div class="agent-stat-num">3</div>
            <div class="agent-stat-label">Docs Verified</div>
          </div>
          <div class="agent-stat-item">
            <div class="agent-stat-num" style="color:var(--accent);">0</div>
            <div class="agent-stat-label">Anomalies Found</div>
          </div>
          <div class="agent-stat-item">
            <div class="agent-stat-num">256-bit</div>
            <div class="agent-stat-label">AES Encryption</div>
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:8px;">
          ${[
            { label: 'Document Integrity', status: 'Passed', icon: '&#10003;', color: 'var(--accent)' },
            { label: 'Blockchain Hash Verification', status: 'Passed', icon: '&#10003;', color: 'var(--accent)' },
            { label: 'MFA Authentication', status: 'Active', icon: '&#10003;', color: 'var(--accent)' },
            { label: 'Unusual Access Patterns', status: 'None Detected', icon: '&#10003;', color: 'var(--accent)' },
            { label: 'Data Encryption at Rest', status: 'AES-256 Active', icon: '&#128274;', color: 'var(--security-color)' },
            { label: 'GDPR Compliance', status: 'Compliant', icon: '&#10003;', color: 'var(--accent)' },
          ].map(item => `
            <div class="security-feature-item">
              <span style="color:${item.color};font-size:1rem;flex-shrink:0;">${item.icon}</span>
              <div style="flex:1;">
                <div style="font-size:0.875rem;font-weight:600;color:var(--text-primary);">${item.label}</div>
              </div>
              <span class="badge badge-green" style="font-size:0.72rem;">${item.status}</span>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `;
}

function initDocumentVault() {
  const vaultItems = $$('.vault-item');
  vaultItems.forEach(item => {
    const verifyBtn = item.querySelector('.verify-btn');
    if (verifyBtn) {
      verifyBtn.addEventListener('click', () => {
        const fileName = item.querySelector('.vault-file-name')?.textContent;
        verifyBtn.textContent = 'Verifying...';
        verifyBtn.disabled = true;
        setTimeout(() => {
          verifyBtn.textContent = 'Verified';
          verifyBtn.classList.add('verified');
          item.querySelector('.vault-status')?.classList.add('verified');
          showToast(`${fileName} verified on blockchain.`, 'success');
        }, 1800);
      });
    }
  });
}

function animateRiskScore() {
  const scoreEl = document.getElementById('risk-score-num');
  if (!scoreEl) return;
  let val = 0;
  const target = parseInt(scoreEl.dataset.score || '92');
  const interval = setInterval(() => {
    val += 3;
    if (val >= target) { val = target; clearInterval(interval); }
    scoreEl.textContent = val;
  }, 16);
}

// ── Agent Chat ─────────────────────────────────────────────────
function initAgentChat(containerId, agentType) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const chatMessages = container.querySelector('.chat-container');
  const chatInput    = container.querySelector('.chat-input');
  const sendBtn      = container.querySelector('.chat-send-btn');

  const agentReplies = {
    tax: [
      'Based on your income bracket, I recommend exploring Section 80C investments to reduce liability.',
      'You may be eligible for HRA exemption if you are a salaried individual paying rent.',
      'New vs Old regime comparison: with standard deduction of ₹50,000, the old regime often benefits those with higher 80C investments.',
      'I can automatically pre-fill your ITR form once you upload Form 16. Would you like to proceed?',
    ],
    invest: [
      'Based on your risk profile, a 60:40 equity-to-debt allocation could give you optimal risk-adjusted returns.',
      'For your 5-year horizon, ELSS funds offer both tax benefits and equity growth potential.',
      'Consider starting an SIP of at least ₹5,000/month to build a corpus efficiently over time.',
      'Current market conditions suggest increasing gold allocation slightly as a hedge.',
    ],
    security: [
      'All your uploaded documents are secured with AES-256 encryption and verified on the blockchain.',
      'I detected no unusual login patterns in the last 30 days. Your account security is excellent.',
      'Your Form 16 was successfully notarized. Its blockchain hash is immutable and tamper-proof.',
      'MFA is active on your account. I recommend enabling biometric login for additional security.',
    ],
  };

  const send = () => {
    const text = chatInput?.value.trim();
    if (!text) return;

    appendMessage(chatMessages, text, 'user');
    chatInput.value = '';

    // Typing indicator
    const typingEl = document.createElement('div');
    typingEl.className = 'chat-message agent';
    typingEl.innerHTML = `
      <div class="chat-avatar">AI</div>
      <div class="loader" style="padding:10px 14px;background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:4px var(--radius-lg) var(--radius-lg) var(--radius-lg);">
        <div class="loader-dot"></div>
        <div class="loader-dot"></div>
        <div class="loader-dot"></div>
      </div>
    `;
    chatMessages.appendChild(typingEl);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    const replies = agentReplies[agentType] || agentReplies.tax;
    const reply = replies[Math.floor(Math.random() * replies.length)];

    setTimeout(() => {
      typingEl.remove();
      appendMessage(chatMessages, reply, 'agent');
    }, 1400 + Math.random() * 800);
  };

  if (sendBtn) sendBtn.addEventListener('click', send);
  if (chatInput) {
    chatInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
  }
}

function appendMessage(container, text, role) {
  if (!container) return;
  const el = document.createElement('div');
  el.className = `chat-message ${role}`;
  el.innerHTML = `
    <div class="chat-avatar">${role === 'agent' ? 'AI' : 'U'}</div>
    <div class="chat-bubble">${text}</div>
  `;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
}

// ── Init All Agent Pages ──────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initTaxAgent();
  initInvestAgent();
  initSecurityAgent();
});
