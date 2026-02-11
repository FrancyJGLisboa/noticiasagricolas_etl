/* Dashboard application logic */

const API_BASE = '';

async function fetchAPI(path) {
    try {
        const resp = await fetch(API_BASE + path);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (err) {
        console.error('API error:', err);
        return null;
    }
}

function fmt(val, decimals) {
    if (val == null) return '--';
    decimals = decimals !== undefined ? decimals : 2;
    return typeof val === 'number' ? val.toFixed(decimals) : val;
}

/* ── Overview page initialization ── */

let priceChart = null;

async function initOverview() {
    // Status stats
    const status = await fetchAPI('/v1/status');
    if (status) {
        document.getElementById('stat-records').textContent = (status.total_records || 0).toLocaleString();
        document.getElementById('stat-commodities').textContent = status.commodity_count || '--';
        document.getElementById('stat-indicators').textContent = status.indicator_count || '--';
        document.getElementById('stat-locations').textContent = status.location_count || '--';
        document.getElementById('stat-latest').textContent = status.last_date || '--';
    }

    // Commodities table
    const commodities = await fetchAPI('/v1/commodities');
    if (commodities && commodities.data) {
        const tbody = document.getElementById('commodities-tbody');
        if (tbody) {
            tbody.innerHTML = commodities.data.map(c => `
                <tr>
                    <td><strong>${c.commodity}</strong></td>
                    <td>--</td>
                    <td>${c.indicator_count}</td>
                    <td>${(c.record_count || 0).toLocaleString()}</td>
                    <td>${c.first_date || '--'} to ${c.last_date || '--'}</td>
                </tr>
            `).join('');
        }

        // Populate commodity filter
        const sel = document.getElementById('filter-commodity');
        if (sel) {
            sel.innerHTML = '<option value="">-- Select --</option>' +
                commodities.data.map(c => `<option value="${c.commodity}">${c.commodity}</option>`).join('');
            sel.addEventListener('change', loadIndicators);
        }
    }
}

async function loadIndicators() {
    const commodity = document.getElementById('filter-commodity').value;
    const sel = document.getElementById('filter-indicator');
    if (!commodity) {
        sel.innerHTML = '<option value="">Select commodity first</option>';
        return;
    }

    const data = await fetchAPI(`/v1/commodities/${commodity}/indicators`);
    if (data && data.indicators) {
        sel.innerHTML = '<option value="">All indicators</option>' +
            data.indicators.map(i => `<option value="${i.slug}">${i.name}</option>`).join('');
    }
}

async function loadPrices() {
    const params = new URLSearchParams();
    const commodity = document.getElementById('filter-commodity').value;
    const indicator = document.getElementById('filter-indicator').value;
    const state = document.getElementById('filter-state').value;
    const from = document.getElementById('filter-from').value;
    const to = document.getElementById('filter-to').value;

    if (commodity) params.set('commodity', commodity);
    if (indicator) params.set('indicator', indicator);
    if (state) params.set('state', state);
    if (from) params.set('date_from', from);
    if (to) params.set('date_to', to);
    params.set('measure', 'price');
    params.set('limit', '500');

    const data = await fetchAPI(`/v1/prices?${params}`);
    if (!data || !data.data) return;

    // Table
    const tbody = document.getElementById('price-tbody');
    tbody.innerHTML = data.data.map(r => `
        <tr>
            <td>${r.date}</td>
            <td>${r.location || '--'}</td>
            <td>${fmt(r.value)}</td>
            <td>${r.unit || ''}</td>
            <td>${r.currency || ''}</td>
            <td>--</td>
        </tr>
    `).join('');

    // Chart: time series
    if (indicator) {
        const tsData = await fetchAPI(`/v1/prices/timeseries?indicator=${indicator}${from ? '&date_from=' + from : ''}${to ? '&date_to=' + to : ''}`);
        if (tsData && tsData.series) {
            renderPriceChart(tsData);
        }
    } else if (data.data.length > 0) {
        // Simple chart from first data
        const grouped = {};
        data.data.forEach(r => {
            if (!grouped[r.date]) grouped[r.date] = [];
            grouped[r.date].push(r.value);
        });
        const dates = Object.keys(grouped).sort();
        const values = dates.map(d => {
            const vals = grouped[d].filter(v => v != null);
            return vals.length ? vals.reduce((a, b) => a + b) / vals.length : null;
        });

        if (priceChart) priceChart.destroy();
        priceChart = new Chart(document.getElementById('price-chart'), {
            type: 'line',
            data: {
                labels: dates,
                datasets: [{ label: 'Avg Price', data: values, borderColor: '#2d6a4f', tension: 0.3, pointRadius: 0 }]
            },
            options: { responsive: true, maintainAspectRatio: false }
        });
    }
}

function renderPriceChart(tsData) {
    const labels = tsData.series.map(s => s.date);
    const colors = ['#2d6a4f', '#d62828', '#f77f00', '#003049', '#9b2226', '#6a994e'];
    const datasets = tsData.locations.slice(0, 6).map((loc, i) => ({
        label: loc,
        data: tsData.series.map(s => s[loc]),
        borderColor: colors[i % colors.length],
        tension: 0.3,
        pointRadius: 0,
    }));

    if (priceChart) priceChart.destroy();
    priceChart = new Chart(document.getElementById('price-chart'), {
        type: 'line',
        data: { labels, datasets },
        options: { responsive: true, maintainAspectRatio: false }
    });
}

// Auto-init on overview page
if (document.getElementById('stats-row')) {
    initOverview();
}
