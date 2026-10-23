let priceChartInstance = null;
let currentConfig = null;
let configLoadedOnce = false;
let activeCurrency = "USD";
let fetchRequestSeq = 0;

const simAmountsByCurrency = {
  USD: 1000,
  EUR: 1000,
  ARS: 100000,
};

function fmtBRL(val, decimals = 4) {
  if (val === null || val === undefined || isNaN(val)) return "R$ --";
  return (
    "R$ " +
    Number(val).toLocaleString("pt-BR", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })
  );
}

function fmtNumBR(val, decimals = 4) {
  if (val === null || val === undefined || isNaN(val)) return "--";
  return Number(val).toLocaleString("pt-BR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function renderCurrenciesBar(currencies) {
  if (!currencies) return;
  const usd = currencies.USD;
  const eur = currencies.EUR;
  const ars = currencies.ARS;

  if (usd) {
    document.getElementById("barUsdPrice").textContent = fmtBRL(usd.price, 4);
    const ch = document.getElementById("barUsdChange");
    ch.textContent = `${usd.pct_change >= 0 ? "+" : ""}${Number(usd.pct_change).toFixed(2)}%`;
    ch.className = "cur-change " + (usd.pct_change <= 0 ? "change-down" : "change-up");
    document.getElementById("barUsdSub").textContent = `Wise: ${fmtBRL(usd.vet_wise, 4)}`;
  }

  if (eur) {
    document.getElementById("barEurPrice").textContent = fmtBRL(eur.price, 4);
    const ch = document.getElementById("barEurChange");
    ch.textContent = `${eur.pct_change >= 0 ? "+" : ""}${Number(eur.pct_change).toFixed(2)}%`;
    ch.className = "cur-change " + (eur.pct_change <= 0 ? "change-down" : "change-up");
    document.getElementById("barEurSub").textContent = `Wise: ${fmtBRL(eur.vet_wise, 4)}`;
  }

  if (ars) {
    document.getElementById("barArsPrice").textContent = fmtBRL(ars.price, 5);
    const ch = document.getElementById("barArsChange");
    ch.textContent = `${ars.pct_change >= 0 ? "+" : ""}${Number(ars.pct_change).toFixed(2)}%`;
    ch.className = "cur-change " + (ars.pct_change <= 0 ? "change-down" : "change-up");
    const arsPerBrl = Number(ars.units_per_1_brl || (ars.price > 0 ? 1 / ars.price : 0)).toLocaleString("pt-BR", {
      maximumFractionDigits: 0,
    });
    const brlPer1k = fmtBRL((ars.price || 0) * 1000, 2);
    document.getElementById("barArsSub").textContent = `R$ 1 = ${arsPerBrl} ARS • 1k = ${brlPer1k}`;
  }
}

async function fetchDashboardData(force = false) {
  const reqSeq = ++fetchRequestSeq;
  const reqCurrency = activeCurrency;
  const simInput = document.getElementById("simUsdInput");
  const defaultAmt = simAmountsByCurrency[reqCurrency] || (reqCurrency === "ARS" ? 100000 : 1000);
  const usdAmt = simInput ? parseFloat(simInput.value) || defaultAmt : defaultAmt;
  simAmountsByCurrency[reqCurrency] = usdAmt;

  const badge = document.getElementById("lastUpdateBadge");
  if (badge) badge.textContent = "Atualizando...";

  try {
    const resp = await fetch(
      `/api/analysis?force=${force ? "true" : "false"}&usd_amount=${usdAmt}&currency=${reqCurrency}`
    );
    if (!resp.ok) throw new Error("Falha ao carregar análise");
    const data = await resp.json();
    // Ignora resposta antiga se o usuário já trocou de aba
    if (reqSeq !== fetchRequestSeq) return;

    if (data.currencies) {
      renderCurrenciesBar(data.currencies);
    }
    renderAnalysis(data.analysis);
    renderHistory(data.history || []);
    if (!configLoadedOnce && data.config) {
      populateConfigForm(data.config);
      configLoadedOnce = true;
    }
    const nowStr = new Date().toLocaleTimeString("pt-BR");
    if (badge) badge.textContent = `Atualizado às ${nowStr}`;
  } catch (err) {
    console.error(err);
    if (badge) badge.textContent = "Erro ao atualizar";
  }
}

function renderAnalysis(a) {
  const spot = a.spot;
  const sc = a.score;
  const ind = a.indicators;
  const st = a.statistics;
  const tm = a.timing;
  const sim = a.simulator;
  const curCode = a.currency || spot.currency || "USD";
  const curSym = spot.symbol || (curCode === "EUR" ? "€" : curCode === "ARS" ? "ARS" : "US$");
  const dec = curCode === "ARS" ? 5 : 4;
  const fineDec = curCode === "ARS" ? 6 : 4;

  // Atualiza rótulos dinâmicos da moeda ativa
  const topLogo = document.getElementById("topLogoBadge");
  if (topLogo) topLogo.textContent = curSym;

  const simLabel = document.getElementById("simInputLabel");
  if (simLabel) simLabel.textContent = `Valor ${curSym}:`;

  const vetHeader = document.getElementById("vetRateHeader");
  if (vetHeader) vetHeader.textContent = `VET (R$/${curSym})`;

  const chartTitle = document.getElementById("chartCardTitle");
  if (chartTitle) {
    chartTitle.textContent = `HISTÓRICO DE 90 DIAS — ${(spot.name || curCode).toUpperCase()} + BANDAS DE BOLLINGER (20,2) + MÉDIAS MÓVEIS`;
  }

  const btnZap = document.getElementById("btnSendZapNow");
  if (btnZap && !btnZap.disabled) {
    btnZap.textContent = `📲 Enviar Raio-X (${curCode}) no Zap`;
  }

  // 1. Spot Card
  const titleEl = document.getElementById("spotCardTitle");
  if (titleEl) {
    titleEl.textContent = `${spot.flag || "💵"} ${(spot.name || "DÓLAR COMERCIAL").toUpperCase()} (SPOT)`;
  }
  document.getElementById("spotPrice").textContent = fmtBRL(spot.price, dec);
  document.getElementById("spotSource").textContent = spot.source || "Tempo Real";

  const arsBanner = document.getElementById("arsConversionBanner");
  if (arsBanner) {
    if (curCode === "ARS" && spot.price > 0) {
      arsBanner.classList.remove("hidden");
      document.getElementById("arsPerReal").textContent = `${(1.0 / spot.price).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} ARS`;
      document.getElementById("brlPer1000Ars").textContent = fmtBRL(spot.price * 1000, 2);
    } else {
      arsBanner.classList.add("hidden");
    }
  }

  const pct = Number(spot.pct_change || 0);
  const chEl = document.getElementById("spotChange");
  chEl.textContent = `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
  chEl.className = "spot-change " + (pct <= 0 ? "change-down" : "change-up");

  document.getElementById("spotLow").textContent = fmtBRL(spot.low, dec);
  document.getElementById("spotHigh").textContent = fmtBRL(spot.high, dec);
  document.getElementById("statMin30").textContent = fmtBRL(st.min30, dec);
  document.getElementById("statMean30").textContent = fmtBRL(st.mean30, dec);

  // Reasons list
  const rList = document.getElementById("reasonsList");
  rList.innerHTML = "";
  (a.reasons.pro || []).forEach((txt) => {
    const li = document.createElement("li");
    li.className = "pro";
    li.textContent = "✅ " + txt;
    rList.appendChild(li);
  });
  (a.reasons.con || []).forEach((txt) => {
    const li = document.createElement("li");
    li.className = "con";
    li.textContent = "⚠️ " + txt;
    rList.appendChild(li);
  });

  // 2. Score Card
  document.getElementById("scoreTotal").textContent = sc.total;
  document.getElementById("alertThresholdTag").textContent = `Alerta >= ${sc.min_alert_threshold} pts`;

  const circle = document.getElementById("scoreCircle");
  const banner = document.getElementById("verdictBanner");
  banner.textContent = `${sc.verdict_emoji} ${sc.verdict}`;

  if (sc.total >= sc.min_alert_threshold) {
    circle.style.borderColor = "#10b981";
    banner.style.background = "rgba(16, 185, 129, 0.16)";
    banner.style.color = "#34d399";
  } else if (sc.total >= 52) {
    circle.style.borderColor = "#f59e0b";
    banner.style.background = "rgba(245, 158, 11, 0.16)";
    banner.style.color = "#fbbf24";
  } else {
    circle.style.borderColor = "#ef4444";
    banner.style.background = "rgba(239, 68, 68, 0.16)";
    banner.style.color = "#f87171";
  }

  const p = sc.pillars;
  setPillar("pStat", p.statistical.score, p.statistical.max);
  setPillar("pTech", p.technical.score, p.technical.max);
  setPillar("pTrend", p.trend_timing.score, p.trend_timing.max);
  setPillar("pEcon", p.real_economy.score, p.real_economy.max);

  // 3. Timing & Anti-Faca Caindo
  const tStatus = document.getElementById("timingStatus");
  tStatus.textContent = tm.status;
  tStatus.style.color = tm.is_falling_knife
    ? "#fbbf24"
    : tm.is_bottoming_out
    ? "#34d399"
    : "#38bdf8";

  document.getElementById("timingAdvice").textContent = tm.advice;
  document.getElementById("dcaPrice1").textContent = fmtBRL(tm.dca_tranche_1_price, dec);
  document.getElementById("dcaPrice2").textContent = fmtBRL(tm.dca_tranche_2_price, dec);
  document.getElementById("dcaSupport").textContent = fmtBRL(tm.support_30d, dec);

  // 4. Raio-X Indicadores
  document.getElementById("indRsi").textContent = ind.rsi14.toFixed(1);
  document.getElementById("indRsiDesc").textContent =
    ind.rsi14 < 38
      ? "🟢 Sobrevenda (Barato)"
      : ind.rsi14 > 60
      ? "🔴 Sobrecomprado (Caro)"
      : "🟡 Zona Neutra (38 a 60)";

  document.getElementById("indBbPct").textContent = `${ind.bb_pct_b.toFixed(0)}% da banda`;
  document.getElementById("indBbRange").textContent = `Inf: ${fmtBRL(ind.bb_lower, dec)} | Sup: ${fmtBRL(ind.bb_upper, dec)}`;

  document.getElementById("indCheap30").textContent = `Mais barato que ${st.cheaper_than_30d_pct.toFixed(0)}%`;
  document.getElementById("indCheap90").textContent = `Mais barato que ${st.cheaper_than_90d_pct.toFixed(0)}%`;

  document.getElementById("indZscore").textContent = `${st.zscore30 >= 0 ? "+" : ""}${st.zscore30.toFixed(2)}σ / ${st.zscore90 >= 0 ? "+" : ""}${st.zscore90.toFixed(2)}σ`;
  document.getElementById("indSmaDiff").textContent = `${ind.diff_sma20_pct >= 0 ? "+" : ""}${ind.diff_sma20_pct.toFixed(2)}% (20d)`;
  document.getElementById("indSmaVals").textContent = `SMA20: ${fmtBRL(ind.sma20, dec)} | SMA50: ${fmtBRL(ind.sma50, dec)}`;

  document.getElementById("indMacd").textContent = fmtNumBR(ind.macd_hist, fineDec);
  document.getElementById("indMacdSlope").textContent =
    ind.macd_hist_slope >= 0
      ? "Queda perdendo força / Subindo"
      : "Pressão de venda acelerando";

  document.getElementById("indAtr").textContent = `${fmtBRL(ind.atr14, fineDec)} (${ind.atr_pct.toFixed(2)}%)`;

  // 5. Tabela Simulador VET
  const tbody = document.getElementById("vetTableBody");
  tbody.innerHTML = "";
  const unitsDec = curCode === "ARS" ? 0 : 2;
  sim.options.forEach((opt) => {
    const tr = document.createElement("tr");
    if (opt.recommended) tr.className = "recommended-row";
    const taxStr = opt.tax_per_usd ? `+${fmtBRL(opt.tax_per_usd, fineDec)}/${curSym}` : "";
    const per1000Str = opt.usd_per_1000_brl
      ? `<div style="font-size:0.74rem;color:#34d399">R$ 1.000 = <strong>${curSym} ${opt.usd_per_1000_brl.toLocaleString("pt-BR", { minimumFractionDigits: unitsDec, maximumFractionDigits: unitsDec })}</strong></div>`
      : "";
    const vetSubStr =
      curCode === "ARS"
        ? `<div style="font-size:0.72rem;color:#94a3b8">1.000 ARS = ${fmtBRL(opt.vet_rate * 1000, 2)}</div>`
        : "";
    tr.innerHTML = `
      <td>
        <strong>${opt.name}</strong>
        ${per1000Str}
      </td>
      <td>
        <div>${opt.spread_pct.toFixed(2)}% + ${opt.iof_pct.toFixed(2)}% IOF</div>
        <small style="color:#94a3b8">${taxStr}</small>
      </td>
      <td>
        <strong>${fmtBRL(opt.vet_rate, dec)}</strong>
        ${vetSubStr}
      </td>
      <td><strong>${fmtBRL(opt.total_brl, 2)}</strong></td>
    `;
    tbody.appendChild(tr);
  });

  const callout = document.getElementById("savingsCallout");
  const savMean = sim.savings_vs_mean30_brl;
  const savMax = sim.savings_vs_max30_brl;
  const savCard = sim.savings_global_vs_card_brl;
  if (savMean >= 0) {
    callout.style.borderLeftColor = "#10b981";
    callout.innerHTML = `
      💰 <strong>Compensa no bolso:</strong> Comprando <strong>${curSym} ${sim.usd_amount.toLocaleString("pt-BR")}</strong> hoje via Conta Global, você economiza <strong>${fmtBRL(savMean, 2)}</strong> em relação à média dos últimos 30 dias (e <strong>${fmtBRL(savMax, 2)}</strong> vs topo do mês). Além disso, economiza <strong>${fmtBRL(savCard, 2)}</strong> comparado ao Cartão de Crédito tradicional!
    `;
  } else {
    callout.style.borderLeftColor = "#f59e0b";
    callout.innerHTML = `
      ⏳ <strong>Atenção ao preço:</strong> Hoje <strong>${curSym} ${sim.usd_amount.toLocaleString("pt-BR")}</strong> sai <strong>${fmtBRL(Math.abs(savMean), 2)} mais caro</strong> que a média dos últimos 30 dias. Ainda assim, usar Conta Global economiza <strong>${fmtBRL(savCard, 2)}</strong> vs Cartão de Crédito.
    `;
  }

  // 6. Chart
  renderChart(a.chart || [], spot, dec);
}

function setPillar(prefix, score, max) {
  document.getElementById(`${prefix}Text`).textContent = `${score.toFixed(1)} / ${max}`;
  const pct = Math.min(100, Math.max(0, (score / max) * 100));
  document.getElementById(`${prefix}Bar`).style.width = `${pct}%`;
}

function renderChart(chartData, spot = {}, dec = 4) {
  const ctx = document.getElementById("priceChart").getContext("2d");
  const labels = chartData.map((d) => d.date.slice(5)); // MM-DD
  const closeVals = chartData.map((d) => d.close);
  const sma20Vals = chartData.map((d) => d.sma20);
  const bbUpperVals = chartData.map((d) => d.bb_upper);
  const bbLowerVals = chartData.map((d) => d.bb_lower);
  const mainLabel = `${spot?.name || "Dólar Comercial"} (R$)`;

  if (priceChartInstance) {
    priceChartInstance.data.labels = labels;
    priceChartInstance.data.datasets[0].label = mainLabel;
    priceChartInstance.data.datasets[0].data = closeVals;
    priceChartInstance.data.datasets[1].data = sma20Vals;
    priceChartInstance.data.datasets[2].data = bbUpperVals;
    priceChartInstance.data.datasets[3].data = bbLowerVals;
    priceChartInstance.options.scales.y.ticks.callback = (val) =>
      "R$ " + Number(val).toLocaleString("pt-BR", { minimumFractionDigits: dec, maximumFractionDigits: dec });
    priceChartInstance.update();
    return;
  }

  priceChartInstance = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: mainLabel,
          data: closeVals,
          borderColor: "#38bdf8",
          backgroundColor: "rgba(56, 189, 248, 0.1)",
          borderWidth: 2.5,
          tension: 0.25,
          pointRadius: 1.5,
        },
        {
          label: "Média 20d (SMA20)",
          data: sma20Vals,
          borderColor: "#f59e0b",
          borderWidth: 1.5,
          borderDash: [5, 5],
          tension: 0.25,
          pointRadius: 0,
        },
        {
          label: "Bollinger Superior",
          data: bbUpperVals,
          borderColor: "rgba(239, 68, 68, 0.45)",
          borderWidth: 1.2,
          tension: 0.25,
          pointRadius: 0,
        },
        {
          label: "Bollinger Inferior (Zona de Compra)",
          data: bbLowerVals,
          borderColor: "rgba(16, 185, 129, 0.65)",
          borderWidth: 1.5,
          tension: 0.25,
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "#cbd5e1" } },
      },
      scales: {
        x: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(255,255,255,0.04)" } },
        y: {
          ticks: {
            color: "#94a3b8",
            callback: (val) =>
              "R$ " + Number(val).toLocaleString("pt-BR", { minimumFractionDigits: dec, maximumFractionDigits: dec }),
          },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
      },
    },
  });
}

function maskPhoneDisplay(raw) {
  if (!raw) return "(19) •••••-1973";
  const str = String(raw);
  if (str.includes("1973")) return "(19) •••••-1973";
  const digits = str.replace(/\D/g, "");
  if (digits.length >= 8) {
    return `(••) •••••-${digits.slice(-4)}`;
  }
  return str;
}

function populateConfigForm(cfg) {
  currentConfig = cfg;
  const baseSim = cfg.simulation_amount_usd && cfg.simulation_amount_usd < 50000 ? cfg.simulation_amount_usd : 1000;
  simAmountsByCurrency.USD = baseSim;
  simAmountsByCurrency.EUR = baseSim;
  document.getElementById("cfgPhone").value = cfg.target_phone || "bot de dolar";
  document.getElementById("cfgMinScore").value = cfg.min_score_alert ?? 72;
  document.getElementById("cfgTargetPrice").value = cfg.target_price_brl ?? "";
  document.getElementById("cfgSimUsd").value = baseSim;
  if (activeCurrency !== "ARS") {
    document.getElementById("simUsdInput").value = baseSim;
  }
  document.getElementById("cfgInterval").value = cfg.check_interval_minutes ?? 5;
  document.getElementById("cfgCooldown").value = cfg.cooldown_hours ?? 4;
  document.getElementById("cfgAutoEnabled").checked = Boolean(cfg.auto_alert_enabled);
  const onlyDropEl = document.getElementById("cfgOnlyOnDrop");
  if (onlyDropEl) onlyDropEl.checked = cfg.only_on_drop !== undefined ? Boolean(cfg.only_on_drop) : true;
  document.getElementById("cfgMarketHours").checked = Boolean(cfg.only_market_hours);
}

function renderHistory(items) {
  const box = document.getElementById("alertsHistoryBox");
  if (!items || !items.length) {
    box.innerHTML = `<p class="muted-empty">Nenhum alerta disparado ainda.</p>`;
    return;
  }
  box.innerHTML = items
    .map((it) => {
      const isArs = String(it.type || "").includes("ARS") || Number(it.price) < 0.05;
      return `
    <div class="history-item">
      <div>
        <strong>${fmtBRL(it.price, isArs ? 5 : 4)}</strong> — Score <strong>${it.score}/100</strong> (${it.verdict})
        <div style="font-size:0.74rem;color:#94a3b8">${it.timestamp} • Destino: ${maskPhoneDisplay(it.target)}</div>
      </div>
      <span class="source-tag">${it.type}</span>
    </div>
  `;
    })
    .join("");
}

let qrModalAutoOpened = false;
const WA_CACHE_KEY = "sdw_wa_connected_cache";

function openQrModal() {
  const modal = document.getElementById("qrModal");
  if (modal) modal.classList.remove("hidden");
}

function closeQrModal() {
  const modal = document.getElementById("qrModal");
  if (modal) modal.classList.add("hidden");
}

function renderConnectedState(userPhone) {
  const badge = document.getElementById("waStatusBadge");
  const connView = document.getElementById("waConnectedView");
  const qrView = document.getElementById("waQrView");
  const loadView = document.getElementById("waLoadingView");

  connView.classList.remove("hidden");
  qrView.classList.add("hidden");
  loadView.classList.add("hidden");

  badge.textContent = "🟢 Conectado";
  badge.style.color = "#34d399";
  document.getElementById("waUserPhone").textContent = maskPhoneDisplay(userPhone);
  closeQrModal();
  qrModalAutoOpened = false;
}

async function pollWhatsAppStatus() {
  try {
    const resp = await fetch("/api/whatsapp/status");
    const st = await resp.json();
    const badge = document.getElementById("waStatusBadge");
    const connView = document.getElementById("waConnectedView");
    const qrView = document.getElementById("waQrView");
    const loadView = document.getElementById("waLoadingView");
    const adminPanel = document.getElementById("waAdminPanel");

    if (st.status === "connected") {
      localStorage.setItem(
        WA_CACHE_KEY,
        JSON.stringify({
          connected: true,
          user_phone: st.user_phone || "",
          ts: Date.now(),
        })
      );
      renderConnectedState(st.user_phone);
    } else if (st.status === "qr_ready" && st.qr_data_url) {
      localStorage.removeItem(WA_CACHE_KEY);
      connView.classList.add("hidden");
      loadView.classList.add("hidden");
      qrView.classList.remove("hidden");

      badge.textContent = "📷 Aguardando QR";
      badge.style.color = "#fbbf24";
      document.getElementById("waQrImg").src = st.qr_data_url;
      const modalImg = document.getElementById("waQrModalImg");
      if (modalImg) modalImg.src = st.qr_data_url;

      // Só abre o modal automático se o painel admin estiver visível
      if (!qrModalAutoOpened && adminPanel && !adminPanel.classList.contains("hidden")) {
        openQrModal();
        qrModalAutoOpened = true;
      }
    } else {
      // Se já estava conectado em cache, mantém exibindo conectado sem piscar
      const cachedRaw = localStorage.getItem(WA_CACHE_KEY);
      if (cachedRaw) {
        try {
          const cached = JSON.parse(cachedRaw);
          if (cached && cached.connected) {
            renderConnectedState(cached.user_phone);
            return;
          }
        } catch (_) {}
      }
      connView.classList.add("hidden");
      qrView.classList.add("hidden");
      loadView.classList.remove("hidden");
      badge.textContent = "⏳ Conectando...";
      badge.style.color = "#94a3b8";
    }
  } catch (e) {
    console.error("Erro ao consultar status do WhatsApp:", e);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  // Carrega o cache de conectado instantaneamente ao abrir/atualizar a página
  try {
    const cachedRaw = localStorage.getItem(WA_CACHE_KEY);
    if (cachedRaw) {
      const cached = JSON.parse(cachedRaw);
      if (cached && cached.connected) {
        renderConnectedState(cached.user_phone);
      }
    }
  } catch (_) {}

  fetchDashboardData(false);
  pollWhatsAppStatus();

  setInterval(() => fetchDashboardData(false), 30000);
  setInterval(pollWhatsAppStatus, 4000);

  // Clique nas abas de moedas (USD, EUR, ARS)
  document.querySelectorAll(".currency-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const cur = tab.getAttribute("data-currency") || "USD";
      const simInput = document.getElementById("simUsdInput");
      if (simInput && activeCurrency) {
        const curVal = parseFloat(simInput.value);
        if (curVal > 0) simAmountsByCurrency[activeCurrency] = curVal;
      }
      activeCurrency = cur;
      document.querySelectorAll(".currency-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      if (simInput) {
        simInput.step = cur === "ARS" ? "10000" : "100";
        simInput.value = simAmountsByCurrency[cur] || (cur === "ARS" ? 100000 : 1000);
      }
      fetchDashboardData(false);
    });
  });

  const btnToggleWaAdmin = document.getElementById("btnToggleWaAdmin");
  const waAdminPanel = document.getElementById("waAdminPanel");
  if (btnToggleWaAdmin && waAdminPanel) {
    btnToggleWaAdmin.addEventListener("click", () => {
      waAdminPanel.classList.toggle("hidden");
    });
  }

  document.getElementById("btnRefresh").addEventListener("click", () => {
    fetchDashboardData(true);
  });

  document.getElementById("simUsdInput").addEventListener("change", () => {
    fetchDashboardData(false);
  });

  // Eventos do Modal QR Code Grande
  document.getElementById("waQrImg").addEventListener("click", openQrModal);
  document.getElementById("btnOpenQrModal").addEventListener("click", openQrModal);
  document.getElementById("btnCloseQrModal").addEventListener("click", closeQrModal);
  document.getElementById("btnCloseQrModalFooter").addEventListener("click", closeQrModal);
  document.getElementById("qrModal").addEventListener("click", (e) => {
    if (e.target.id === "qrModal") closeQrModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeQrModal();
  });
  document.getElementById("btnRegenerateQr").addEventListener("click", async () => {
    localStorage.removeItem(WA_CACHE_KEY);
    await fetch("/api/whatsapp/logout", { method: "POST" });
    setTimeout(pollWhatsAppStatus, 1500);
  });

  document.getElementById("btnSendZapNow").addEventListener("click", async () => {
    const btn = document.getElementById("btnSendZapNow");
    const oldText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "⏳ Enviando para o Zap...";
    try {
      const phone = document.getElementById("cfgPhone").value.trim() || null;
      const resp = await fetch("/api/whatsapp/send-now", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone, currency: activeCurrency }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Falha ao enviar");
      btn.textContent = "✅ Enviado no WhatsApp!";
      fetchDashboardData(false);
    } catch (err) {
      alert("Aviso: " + err.message);
      btn.textContent = oldText;
    } finally {
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = oldText;
      }, 2500);
    }
  });

  document.getElementById("btnWaLogout").addEventListener("click", async () => {
    if (!confirm("Deseja desconectar a sessão atual do WhatsApp e gerar novo QR Code?")) return;
    localStorage.removeItem(WA_CACHE_KEY);
    qrModalAutoOpened = false;
    await fetch("/api/whatsapp/logout", { method: "POST" });
    setTimeout(pollWhatsAppStatus, 1200);
  });

  // Carregar lista de grupos do WhatsApp
  const btnLoadGroups = document.getElementById("btnLoadGroups");
  const groupSelect = document.getElementById("groupSelect");
  if (btnLoadGroups && groupSelect) {
    btnLoadGroups.addEventListener("click", async () => {
      btnLoadGroups.textContent = "⏳...";
      try {
        const resp = await fetch("/api/whatsapp/groups");
        const data = await resp.json();
        const groups = data.groups || [];
        groupSelect.innerHTML = `<option value="">-- Escolha um grupo (${groups.length} encontrados) --</option>`;
        groups.forEach((g) => {
          const opt = document.createElement("option");
          opt.value = g.name;
          opt.textContent = `👥 ${g.name} (${g.participants} membros)`;
          groupSelect.appendChild(opt);
        });
        groupSelect.classList.remove("hidden");
      } catch (e) {
        alert("Erro ao buscar grupos: " + e.message);
      } finally {
        btnLoadGroups.textContent = "📋 Grupos";
      }
    });

    groupSelect.addEventListener("change", () => {
      if (groupSelect.value) {
        document.getElementById("cfgPhone").value = groupSelect.value;
      }
    });
  }

  document.getElementById("configForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const targetPriceRaw = document.getElementById("cfgTargetPrice").value.trim();
    const onlyDropEl = document.getElementById("cfgOnlyOnDrop");
    const payload = {
      target_phone: document.getElementById("cfgPhone").value.trim(),
      min_score_alert: parseInt(document.getElementById("cfgMinScore").value, 10) || 72,
      target_price_brl: targetPriceRaw ? parseFloat(targetPriceRaw) : null,
      simulation_amount_usd: parseFloat(document.getElementById("cfgSimUsd").value) || 1000,
      check_interval_minutes: parseInt(document.getElementById("cfgInterval").value, 10) || 5,
      cooldown_hours: parseFloat(document.getElementById("cfgCooldown").value) || 4,
      auto_alert_enabled: document.getElementById("cfgAutoEnabled").checked,
      only_on_drop: onlyDropEl ? onlyDropEl.checked : true,
      only_market_hours: document.getElementById("cfgMarketHours").checked,
      spreads: currentConfig?.spreads || undefined,
    };

    const resp = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (resp.ok) {
      const fb = document.getElementById("saveFeedback");
      fb.textContent = "✅ Configurações salvas!";
      document.getElementById("simUsdInput").value = payload.simulation_amount_usd;
      fetchDashboardData(false);
      setTimeout(() => (fb.textContent = ""), 3000);
    }
  });
});
