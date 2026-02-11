/* WebMCP tool registration for browser agent interaction.
 *
 * Registers tools that browser agents (Claude, ChatGPT, etc.) can call
 * to interact with the dashboard UI. Each tool calls the REST API and
 * updates the visible charts/tables.
 *
 * Graceful degradation: if navigator.ml is not supported, tools are
 * registered on window.__webmcp for future use.
 */

(function() {
    const tools = [
        {
            name: "filterPrices",
            description: "Filter the price table by commodity, state, date range. Updates the visible chart and table.",
            inputSchema: {
                type: "object",
                properties: {
                    commodity: { type: "string", description: "e.g. soja, milho, cafe" },
                    state: { type: "string", description: "2-letter BR state code, e.g. MT, PR" },
                    date_from: { type: "string", description: "Start date YYYY-MM-DD" },
                    date_to: { type: "string", description: "End date YYYY-MM-DD" },
                    measure: { type: "string", enum: ["price", "change_pct"] }
                },
                required: ["commodity"]
            },
            handler: async (params) => {
                if (params.commodity) document.getElementById('filter-commodity').value = params.commodity;
                if (params.state) document.getElementById('filter-state').value = params.state;
                if (params.date_from) document.getElementById('filter-from').value = params.date_from;
                if (params.date_to) document.getElementById('filter-to').value = params.date_to;
                await loadIndicators();
                await loadPrices();
                return { success: true, message: "Price table updated" };
            }
        },
        {
            name: "showBasis",
            description: "Show basis analysis (physical minus futures spread) for a commodity and location.",
            inputSchema: {
                type: "object",
                properties: {
                    commodity: { type: "string" },
                    physical_indicator: { type: "string" },
                    futures_indicator: { type: "string" },
                    location: { type: "string" }
                },
                required: ["commodity", "physical_indicator", "futures_indicator"]
            },
            handler: async (params) => {
                window.location.href = `/dashboard/basis`;
                return { success: true, message: "Navigated to basis view" };
            }
        },
        {
            name: "showFuturesCurve",
            description: "Show futures curve (all active contracts) for an indicator on a date.",
            inputSchema: {
                type: "object",
                properties: {
                    indicator: { type: "string" },
                    date: { type: "string" }
                },
                required: ["indicator"]
            },
            handler: async (params) => {
                window.location.href = `/dashboard/curve`;
                return { success: true, message: "Navigated to futures curve view" };
            }
        },
        {
            name: "showRegionalRankings",
            description: "Show locations ranked by price for an indicator, cheapest to most expensive.",
            inputSchema: {
                type: "object",
                properties: {
                    indicator: { type: "string" },
                    date: { type: "string" },
                    limit: { type: "integer" }
                },
                required: ["indicator"]
            },
            handler: async (params) => {
                window.location.href = `/dashboard/rankings`;
                return { success: true, message: "Navigated to rankings view" };
            }
        },
        {
            name: "exportCurrentView",
            description: "Export the current visible data as CSV download.",
            inputSchema: { type: "object", properties: {} },
            handler: async () => {
                const table = document.querySelector('table');
                if (!table) return { success: false, message: "No table visible" };
                const rows = Array.from(table.querySelectorAll('tr'));
                const csv = rows.map(r =>
                    Array.from(r.querySelectorAll('th,td')).map(c => '"' + c.textContent.replace(/"/g, '""') + '"').join(',')
                ).join('\n');
                const blob = new Blob([csv], { type: 'text/csv' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'export.csv';
                a.click();
                return { success: true, message: "CSV downloaded" };
            }
        }
    ];

    // Register with WebMCP API if available, otherwise store for future use
    if (typeof navigator !== 'undefined' && navigator.ml && navigator.ml.registerTool) {
        tools.forEach(tool => navigator.ml.registerTool(tool));
        console.log('WebMCP: registered', tools.length, 'tools');
    } else {
        window.__webmcp = { tools };
        console.log('WebMCP: stored', tools.length, 'tools (navigator.ml not available)');
    }
})();
